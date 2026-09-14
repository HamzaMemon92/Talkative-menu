from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ainza_restaurant.billing.models import (
    DiningInvoice,
    DiningInvoiceLine,
    DiningInvoiceLineModifier,
    DiningInvoiceOrder,
)
from ainza_restaurant.billing.schemas import (
    BillingRoundSummaryRead,
    BillingTaxConfigurationRead,
    BillPreviewRead,
    InvoiceFinalizeRequest,
    InvoiceLineModifierRead,
    InvoiceLineRead,
    InvoiceOrderRead,
    InvoiceRead,
)
from ainza_restaurant.dining.models import DiningSession, RestaurantTable
from ainza_restaurant.domain.enums import (
    DiningInvoiceStatus,
    DiningOrderStatus,
    DiningSessionStatus,
)
from ainza_restaurant.ordering.models import (
    CartItem,
    DiningCart,
    DiningOrder,
    DiningOrderItem,
)
from ainza_restaurant.restaurants.models import OutletTaxProfile, Restaurant, RestaurantOutlet


class BillingNotFound(LookupError):
    code = "invoice_not_found"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class BillingConflict(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "billing_conflict",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class _Context:
    session: DiningSession
    table: RestaurantTable
    outlet: RestaurantOutlet
    restaurant: Restaurant


@dataclass(frozen=True)
class _Totals:
    subtotal_before_discount: Decimal
    discount_total: Decimal
    subtotal_after_discount: Decimal
    taxable_amount: Decimal | None
    tax_amount: Decimal | None
    invoice_total: Decimal | None


MONEY = Decimal("0.01")


class BillingService:
    def __init__(self, session: AsyncSession, *, now: Callable[[], datetime] | None = None) -> None:
        self.session = session
        self._now = now or (lambda: datetime.now(UTC))

    def now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    async def get_preview(self, session_token: str) -> BillPreviewRead:
        context = await self._context(session_token)
        orders = await self._orders(context.session.id)
        cart_count = await self._cart_item_count(context.session.id)
        invoice = await self._invoice_for_session(context.session.id)
        tax_profile = await self._tax_profile(context.outlet.id)
        return self._preview(context, orders, cart_count, tax_profile, invoice)

    async def finalize_invoice(
        self, session_token: str, data: InvoiceFinalizeRequest
    ) -> InvoiceRead:
        context = await self._context(session_token)
        existing = await self._invoice_for_session(context.session.id)
        if existing is not None:
            if existing.idempotency_key == data.idempotency_key:
                return await self._invoice_read(existing.id)
            raise BillingConflict("invoice already finalized", code="invoice_already_finalized")
        if not data.confirm:
            raise BillingConflict(
                "invoice finalization requires confirm=true",
                code="invoice_confirmation_required",
            )
        orders = await self._orders(context.session.id)
        cart_count = await self._cart_item_count(context.session.id)
        tax_profile = await self._tax_profile(context.outlet.id)
        preview = self._preview(context, orders, cart_count, tax_profile, existing)
        if preview.billing_quote_token != data.billing_quote_token:
            raise BillingConflict(
                "billing quote is stale",
                code="billing_quote_stale",
                details={"current_billing_quote_token": preview.billing_quote_token},
            )
        if preview.blockers:
            raise BillingConflict(
                "invoice cannot be finalized",
                code=self._blocker_error_code(preview.blockers[0]),
                details={"blockers": preview.blockers},
            )
        if (
            preview.taxable_amount is None
            or preview.tax_amount is None
            or preview.invoice_total is None
            or tax_profile is None
            or tax_profile.configured_tax_rate_percent is None
            or tax_profile.prices_include_tax is None
            or tax_profile.restaurant_type is None
            or tax_profile.legal_business_name is None
        ):
            raise BillingConflict(
                "tax configuration is incomplete",
                code="tax_configuration_incomplete",
            )
        invoice = DiningInvoice(
            dining_session_id=context.session.id,
            outlet_id=context.outlet.id,
            invoice_reference=await self._unique_invoice_reference(),
            status=DiningInvoiceStatus.FINALIZED,
            currency_code=context.outlet.currency_code,
            subtotal_before_discount=preview.subtotal_before_discount,
            discount_total=preview.discount_total,
            subtotal_after_discount=preview.subtotal_after_discount,
            taxable_amount=preview.taxable_amount,
            tax_rate_snapshot=money(tax_profile.configured_tax_rate_percent),
            prices_include_tax_snapshot=tax_profile.prices_include_tax,
            tax_amount=preview.tax_amount,
            invoice_total=preview.invoice_total,
            restaurant_name_snapshot=context.restaurant.name,
            outlet_name_snapshot=context.outlet.name,
            legal_business_name_snapshot=tax_profile.legal_business_name,
            restaurant_type_snapshot=tax_profile.restaurant_type,
            gst_registered_snapshot=tax_profile.gst_registered,
            gstin_snapshot=tax_profile.gstin,
            state_snapshot=context.outlet.state,
            country_code_snapshot=context.outlet.country,
            idempotency_key=data.idempotency_key,
            finalized_at=self.now(),
        )
        self.session.add(invoice)
        await self.session.flush()
        try:
            await self._create_invoice_lines(invoice, orders)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            retry = await self._invoice_for_idempotency(context.session.id, data.idempotency_key)
            if retry is not None:
                return await self._invoice_read(retry.id)
            duplicate = await self._invoice_for_session(context.session.id)
            if duplicate is not None:
                raise BillingConflict(
                    "invoice already finalized", code="invoice_already_finalized"
                ) from exc
            raise BillingConflict(
                "invoice reference collision", code="invoice_reference_collision"
            ) from exc
        except Exception:
            await self.session.rollback()
            raise
        return await self._invoice_read(invoice.id)

    async def get_session_invoice(self, session_token: str) -> InvoiceRead:
        context = await self._context(session_token)
        invoice = await self._invoice_for_session(context.session.id)
        if invoice is None:
            raise BillingNotFound("invoice not found", code="invoice_not_found")
        return await self._invoice_read(invoice.id)

    async def get_invoice(self, invoice_id: UUID) -> InvoiceRead:
        invoice = await self.session.get(DiningInvoice, invoice_id)
        if invoice is None:
            raise BillingNotFound("invoice not found", code="invoice_not_found")
        return await self._invoice_read(invoice.id)

    async def _context(self, session_token: str) -> _Context:
        result = await self.session.execute(
            select(DiningSession, RestaurantTable, RestaurantOutlet, Restaurant)
            .join(RestaurantTable, RestaurantTable.id == DiningSession.table_id)
            .join(RestaurantOutlet, RestaurantOutlet.id == RestaurantTable.outlet_id)
            .join(Restaurant, Restaurant.id == RestaurantOutlet.restaurant_id)
            .where(DiningSession.public_session_token == session_token)
        )
        row = result.one_or_none()
        if row is None:
            raise BillingNotFound("dining session not found", code="billing_session_not_found")
        dining_session, table, outlet, restaurant = row
        return _Context(dining_session, table, outlet, restaurant)

    async def _orders(self, dining_session_id: UUID) -> list[DiningOrder]:
        result = await self.session.execute(
            select(DiningOrder)
            .options(
                selectinload(DiningOrder.items).selectinload(DiningOrderItem.modifiers),
            )
            .where(DiningOrder.dining_session_id == dining_session_id)
            .order_by(DiningOrder.round_number, DiningOrder.created_at, DiningOrder.id)
        )
        return list(result.scalars())

    async def _cart_item_count(self, dining_session_id: UUID) -> int:
        count = await self.session.scalar(
            select(func.count())
            .select_from(CartItem)
            .join(DiningCart, DiningCart.id == CartItem.cart_id)
            .where(DiningCart.dining_session_id == dining_session_id)
        )
        return int(count or 0)

    async def _tax_profile(self, outlet_id: UUID) -> OutletTaxProfile | None:
        return (
            await self.session.execute(
                select(OutletTaxProfile).where(OutletTaxProfile.outlet_id == outlet_id)
            )
        ).scalar_one_or_none()

    def _preview(
        self,
        context: _Context,
        orders: list[DiningOrder],
        cart_count: int,
        tax_profile: OutletTaxProfile | None,
        invoice: DiningInvoice | None,
    ) -> BillPreviewRead:
        subtotal_before = money(
            sum((order.subtotal_before_discount for order in orders), Decimal("0"))
        )
        discount_total = money(sum((order.discount_amount for order in orders), Decimal("0")))
        subtotal_after = money(
            sum((order.subtotal_after_discount for order in orders), Decimal("0"))
        )
        tax_configured = self._tax_complete(tax_profile)
        totals = self._totals(
            subtotal_before,
            discount_total,
            subtotal_after,
            tax_profile if tax_configured else None,
        )
        blockers = self._blockers(context, orders, cart_count, tax_configured, invoice)
        read_without_token = BillPreviewRead(
            dining_session_id=context.session.id,
            dining_session_token=context.session.public_session_token,
            outlet_id=context.outlet.id,
            outlet_name=context.outlet.name,
            currency_code=context.outlet.currency_code,
            round_summaries=[
                BillingRoundSummaryRead(
                    dining_order_id=order.id,
                    round_number=order.round_number,
                    status=order.status,
                    subtotal_before_discount=money(order.subtotal_before_discount),
                    discount_amount=money(order.discount_amount),
                    subtotal_after_discount=money(order.subtotal_after_discount),
                )
                for order in orders
            ],
            subtotal_before_discount=totals.subtotal_before_discount,
            discount_total=totals.discount_total,
            subtotal_after_discount=totals.subtotal_after_discount,
            tax_configuration=BillingTaxConfigurationRead(
                configured=tax_configured,
                tax_rate_percent=money(tax_profile.configured_tax_rate_percent)
                if tax_profile and tax_profile.configured_tax_rate_percent is not None
                else None,
                prices_include_tax=tax_profile.prices_include_tax if tax_profile else None,
                tax_configuration_confirmed=(
                    tax_profile.tax_configuration_confirmed if tax_profile else False
                ),
                gst_registered=tax_profile.gst_registered if tax_profile else None,
                gstin=tax_profile.gstin if tax_profile else None,
                legal_business_name=tax_profile.legal_business_name if tax_profile else None,
                restaurant_type=tax_profile.restaurant_type if tax_profile else None,
            ),
            taxable_amount=totals.taxable_amount,
            tax_amount=totals.tax_amount,
            invoice_total=totals.invoice_total,
            finalizable=not blockers,
            blockers=blockers,
            billing_quote_token="",
        )
        return read_without_token.model_copy(
            update={"billing_quote_token": billing_quote_token(read_without_token)}
        )

    def _blockers(
        self,
        context: _Context,
        orders: list[DiningOrder],
        cart_count: int,
        tax_configured: bool,
        invoice: DiningInvoice | None,
    ) -> list[str]:
        blockers: list[str] = []
        if context.session.status != DiningSessionStatus.OPEN:
            blockers.append("session_closed")
        if invoice is not None:
            blockers.append("invoice_already_finalized")
        if not orders:
            blockers.append("no_submitted_orders")
        if cart_count:
            blockers.append("cart_not_empty")
        if any(order.status != DiningOrderStatus.SERVED for order in orders):
            blockers.append("active_orders_not_served")
        if not tax_configured:
            blockers.append("tax_configuration_incomplete")
        return blockers

    def _tax_complete(self, profile: OutletTaxProfile | None) -> bool:
        if profile is None:
            return False
        if not profile.tax_configuration_confirmed:
            return False
        if not profile.tax_rates_confirmed:
            return False
        if profile.configured_tax_rate_percent is None:
            return False
        if profile.prices_include_tax is None:
            return False
        if not profile.legal_business_name:
            return False
        if profile.restaurant_type is None:
            return False
        if profile.gst_registered:
            return bool(profile.gstin and profile.gstin_confirmed and profile.gst_state_code)
        return profile.gstin is None

    def _totals(
        self,
        subtotal_before: Decimal,
        discount_total: Decimal,
        subtotal_after: Decimal,
        profile: OutletTaxProfile | None,
    ) -> _Totals:
        if profile is None or profile.configured_tax_rate_percent is None:
            return _Totals(subtotal_before, discount_total, subtotal_after, None, None, None)
        rate = Decimal(profile.configured_tax_rate_percent)
        if profile.prices_include_tax:
            divisor = Decimal("1") + (rate / Decimal("100"))
            taxable = money(subtotal_after / divisor)
            tax_amount = money(subtotal_after - taxable)
            total = subtotal_after
        else:
            taxable = subtotal_after
            tax_amount = money(taxable * rate / Decimal("100"))
            total = money(subtotal_after + tax_amount)
        return _Totals(subtotal_before, discount_total, subtotal_after, taxable, tax_amount, total)

    async def _create_invoice_lines(
        self, invoice: DiningInvoice, orders: list[DiningOrder]
    ) -> None:
        display_order = 1
        for order in orders:
            self.session.add(
                DiningInvoiceOrder(
                    invoice_id=invoice.id,
                    dining_order_id=order.id,
                    round_number_snapshot=order.round_number,
                )
            )
            for item in sorted(order.items, key=lambda value: (value.created_at, str(value.id))):
                line = DiningInvoiceLine(
                    invoice_id=invoice.id,
                    dining_order_id=order.id,
                    dining_order_item_id=item.id,
                    round_number_snapshot=order.round_number,
                    dish_name_snapshot=item.dish_name_snapshot,
                    variant_name_snapshot=item.variant_name_snapshot,
                    quantity=item.quantity,
                    configured_unit_price_snapshot=money(item.configured_unit_price_snapshot),
                    line_subtotal_snapshot=money(item.line_subtotal_snapshot),
                    customer_note_snapshot=item.customer_note_snapshot,
                    tax_category_code_snapshot=item.tax_category_code_snapshot,
                    display_order=display_order,
                )
                line.modifiers = [
                    DiningInvoiceLineModifier(
                        modifier_option_id=modifier.modifier_option_id,
                        modifier_group_name_snapshot=modifier.modifier_group_name_snapshot,
                        modifier_option_name_snapshot=modifier.modifier_option_name_snapshot,
                        price_delta_snapshot=money(modifier.price_delta_snapshot),
                    )
                    for modifier in item.modifiers
                ]
                self.session.add(line)
                display_order += 1
        await self.session.flush()

    async def _invoice_for_session(self, dining_session_id: UUID) -> DiningInvoice | None:
        return (
            await self.session.execute(
                select(DiningInvoice).where(DiningInvoice.dining_session_id == dining_session_id)
            )
        ).scalar_one_or_none()

    async def _invoice_for_idempotency(
        self, dining_session_id: UUID, idempotency_key: str
    ) -> DiningInvoice | None:
        return (
            await self.session.execute(
                select(DiningInvoice).where(
                    DiningInvoice.dining_session_id == dining_session_id,
                    DiningInvoice.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()

    async def _invoice_read(self, invoice_id: UUID) -> InvoiceRead:
        invoice = (
            await self.session.execute(
                select(DiningInvoice)
                .options(
                    selectinload(DiningInvoice.orders),
                    selectinload(DiningInvoice.lines).selectinload(DiningInvoiceLine.modifiers),
                )
                .where(DiningInvoice.id == invoice_id)
            )
        ).scalar_one_or_none()
        if invoice is None:
            raise BillingNotFound("invoice not found", code="invoice_not_found")
        return InvoiceRead(
            id=invoice.id,
            dining_session_id=invoice.dining_session_id,
            outlet_id=invoice.outlet_id,
            invoice_reference=invoice.invoice_reference,
            status=invoice.status,
            currency_code=invoice.currency_code,
            subtotal_before_discount=money(invoice.subtotal_before_discount),
            discount_total=money(invoice.discount_total),
            subtotal_after_discount=money(invoice.subtotal_after_discount),
            taxable_amount=money(invoice.taxable_amount),
            tax_rate_snapshot=money(invoice.tax_rate_snapshot),
            prices_include_tax_snapshot=invoice.prices_include_tax_snapshot,
            tax_amount=money(invoice.tax_amount),
            invoice_total=money(invoice.invoice_total),
            restaurant_name_snapshot=invoice.restaurant_name_snapshot,
            outlet_name_snapshot=invoice.outlet_name_snapshot,
            legal_business_name_snapshot=invoice.legal_business_name_snapshot,
            restaurant_type_snapshot=invoice.restaurant_type_snapshot,
            gst_registered_snapshot=invoice.gst_registered_snapshot,
            gstin_snapshot=invoice.gstin_snapshot,
            state_snapshot=invoice.state_snapshot,
            country_code_snapshot=invoice.country_code_snapshot,
            finalized_at=invoice.finalized_at,
            created_at=invoice.created_at,
            orders=[
                InvoiceOrderRead(
                    dining_order_id=order.dining_order_id,
                    round_number_snapshot=order.round_number_snapshot,
                )
                for order in sorted(invoice.orders, key=lambda value: value.round_number_snapshot)
            ],
            lines=[
                InvoiceLineRead(
                    id=line.id,
                    dining_order_id=line.dining_order_id,
                    dining_order_item_id=line.dining_order_item_id,
                    round_number_snapshot=line.round_number_snapshot,
                    dish_name_snapshot=line.dish_name_snapshot,
                    variant_name_snapshot=line.variant_name_snapshot,
                    quantity=line.quantity,
                    configured_unit_price_snapshot=money(line.configured_unit_price_snapshot),
                    line_subtotal_snapshot=money(line.line_subtotal_snapshot),
                    customer_note_snapshot=line.customer_note_snapshot,
                    tax_category_code_snapshot=line.tax_category_code_snapshot,
                    display_order=line.display_order,
                    modifiers=[
                        InvoiceLineModifierRead(
                            modifier_option_id=modifier.modifier_option_id,
                            modifier_group_name_snapshot=(modifier.modifier_group_name_snapshot),
                            modifier_option_name_snapshot=(modifier.modifier_option_name_snapshot),
                            price_delta_snapshot=money(modifier.price_delta_snapshot),
                        )
                        for modifier in sorted(
                            line.modifiers, key=lambda value: (value.created_at, str(value.id))
                        )
                    ],
                )
                for line in sorted(invoice.lines, key=lambda value: value.display_order)
            ],
        )

    def _blocker_error_code(self, blocker: str) -> str:
        return {
            "session_closed": "billing_session_closed",
            "invoice_already_finalized": "invoice_already_finalized",
            "no_submitted_orders": "billing_no_orders",
            "cart_not_empty": "billing_cart_not_empty",
            "active_orders_not_served": "billing_active_orders",
            "tax_configuration_incomplete": "tax_configuration_incomplete",
        }.get(blocker, "billing_conflict")

    async def _unique_invoice_reference(self) -> str:
        for _ in range(10):
            reference = f"INV-{secrets.token_urlsafe(12).replace('_', '').replace('-', '')[:16]}"
            exists = (
                await self.session.execute(
                    select(DiningInvoice.invoice_reference).where(
                        DiningInvoice.invoice_reference == reference
                    )
                )
            ).first()
            if exists is None:
                return reference
        raise BillingConflict(
            "could not generate unique invoice reference",
            code="invoice_reference_generation_failed",
        )


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def billing_quote_token(preview: BillPreviewRead) -> str:
    payload = preview.model_dump(mode="json")
    payload["billing_quote_token"] = ""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
