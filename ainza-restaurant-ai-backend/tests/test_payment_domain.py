from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.ai.context import AIActorType
from ainza_restaurant.billing.models import DiningInvoice
from ainza_restaurant.core.config import get_settings
from ainza_restaurant.db.base import Base
from ainza_restaurant.domain.enums import (
    DiningInvoiceStatus,
    PaymentAttemptStatus,
    PaymentMode,
    PaymentStatus,
    RestaurantType,
)
from ainza_restaurant.payment.adapters.fake import FakeDeterministicPaymentAdapter
from ainza_restaurant.payment.service import PaymentConflict, PaymentService
from tests.test_ai_tools import urban_tadka


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        yield db
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def create_finalized_invoice(
    session: AsyncSession,
    data: dict[str, object],
    *,
    total: Decimal = Decimal("340.00"),
    currency_code: str = "INR",
) -> DiningInvoice:
    invoice = DiningInvoice(
        dining_session_id=data["dining_session"].id,
        outlet_id=data["outlet"].id,
        invoice_reference=f"INV-{uuid4().hex[:8]}",
        status=DiningInvoiceStatus.FINALIZED,
        currency_code=currency_code,
        subtotal_before_discount=total,
        discount_total=Decimal("0.00"),
        subtotal_after_discount=total,
        taxable_amount=total,
        tax_rate_snapshot=Decimal("5.00"),
        prices_include_tax_snapshot=True,
        tax_amount=Decimal("17.00"),
        invoice_total=total,
        restaurant_name_snapshot="Urban Tadka",
        outlet_name_snapshot="Urban Tadka - Vesu",
        legal_business_name_snapshot="Urban Tadka Hospitality LLP",
        restaurant_type_snapshot=RestaurantType.STANDALONE,
        gst_registered_snapshot=True,
        state_snapshot="Gujarat",
        country_code_snapshot="IN",
        idempotency_key=f"idem_{uuid4().hex}",
        finalized_at=datetime.now(UTC),
    )
    session.add(invoice)
    await session.commit()
    return invoice


@pytest.mark.asyncio
async def test_21_create_payment_intent_from_authoritative_bill(session: AsyncSession):
    data = await urban_tadka(session)
    payment_service = PaymentService(session)

    # 1. Attempt to create intent BEFORE finalized invoice exists -> must fail
    with pytest.raises(PaymentConflict) as exc:
        await payment_service.create_payment_intent(
            dining_session_id=data["dining_session"].id,
            payment_mode=PaymentMode.ONLINE,
            idempotency_key="pay_intent_1",
        )
    assert exc.value.code == "invoice_not_finalized"

    # 2. Finalize invoice and create intent
    invoice = await create_finalized_invoice(session, data, total=Decimal("450.00"))
    intent = await payment_service.create_payment_intent(
        dining_session_id=data["dining_session"].id,
        payment_mode=PaymentMode.ONLINE,
        idempotency_key="pay_intent_1",
    )

    assert intent.invoice_id == invoice.id
    assert intent.amount == Decimal("450.00")
    assert intent.currency_code == "INR"
    assert intent.status == PaymentStatus.PENDING


@pytest.mark.asyncio
async def test_22_exact_amount_currency_snapshot(session: AsyncSession):
    data = await urban_tadka(session)
    await create_finalized_invoice(session, data, total=Decimal("675.50"), currency_code="INR")

    payment_service = PaymentService(session)
    intent = await payment_service.create_payment_intent(
        dining_session_id=data["dining_session"].id,
        payment_mode=PaymentMode.ONLINE,
        idempotency_key="pay_intent_snapshot",
    )

    assert intent.amount == Decimal("675.50")
    assert intent.currency_code == "INR"


@pytest.mark.asyncio
async def test_23_online_pending_payment(session: AsyncSession):
    data = await urban_tadka(session)
    await create_finalized_invoice(session, data)

    payment_service = PaymentService(session)
    intent = await payment_service.create_payment_intent(
        dining_session_id=data["dining_session"].id,
        payment_mode=PaymentMode.ONLINE,
        idempotency_key="pay_online_1",
    )

    assert intent.payment_mode == PaymentMode.ONLINE
    assert intent.status == PaymentStatus.PENDING
    assert intent.provider == "fake"
    assert len(intent.attempts) == 1
    assert intent.attempts[0].status == PaymentAttemptStatus.INITIATED


@pytest.mark.asyncio
async def test_24_payment_qr_and_checkout_contract(session: AsyncSession):
    data = await urban_tadka(session)
    await create_finalized_invoice(session, data)

    payment_service = PaymentService(session)
    intent = await payment_service.create_payment_intent(
        dining_session_id=data["dining_session"].id,
        payment_mode=PaymentMode.ONLINE,
        idempotency_key="pay_qr_1",
    )

    # Must have payment QR distinct from table QR
    assert intent.qr_payload is not None
    assert str(intent.id) in intent.qr_payload
    assert intent.checkout_url is not None
    assert "checkout" in intent.checkout_url


@pytest.mark.asyncio
async def test_25_duplicate_create_idempotency(session: AsyncSession):
    data = await urban_tadka(session)
    await create_finalized_invoice(session, data)

    payment_service = PaymentService(session)
    intent1 = await payment_service.create_payment_intent(
        dining_session_id=data["dining_session"].id,
        payment_mode=PaymentMode.ONLINE,
        idempotency_key="same_idempotency_key",
    )
    intent2 = await payment_service.create_payment_intent(
        dining_session_id=data["dining_session"].id,
        payment_mode=PaymentMode.ONLINE,
        idempotency_key="same_idempotency_key",
    )

    assert intent1.id == intent2.id


@pytest.mark.asyncio
async def test_26_verified_success(session: AsyncSession):
    data = await urban_tadka(session)
    _ = await create_finalized_invoice(session, data, total=Decimal("340.00"))

    payment_service = PaymentService(session)
    intent = await payment_service.create_payment_intent(
        dining_session_id=data["dining_session"].id,
        payment_mode=PaymentMode.ONLINE,
        idempotency_key="pay_success_1",
    )

    secret = get_settings().fake_payment_webhook_secret
    payload_dict = {
        "event_id": "evt_123",
        "payment_intent_id": str(intent.id),
        "amount": "340.00",
        "currency": "INR",
        "status": "success",
        "provider_reference": "ref_999",
    }
    raw_body = json.dumps(payload_dict).encode("utf-8")
    sig = FakeDeterministicPaymentAdapter.sign_payload(raw_body, secret)

    updated_intent, is_dup = await payment_service.handle_provider_webhook(
        "fake",
        raw_body,
        {"X-Ainza-Signature": sig},
        secret,
    )

    assert is_dup is False
    assert updated_intent.status == PaymentStatus.SUCCESS
    assert len(updated_intent.attempts) == 2
    assert updated_intent.attempts[-1].status == PaymentAttemptStatus.SUCCESS


@pytest.mark.asyncio
async def test_27_bad_signature_rejected(session: AsyncSession):
    data = await urban_tadka(session)
    await create_finalized_invoice(session, data)

    payment_service = PaymentService(session)
    intent = await payment_service.create_payment_intent(
        dining_session_id=data["dining_session"].id,
        payment_mode=PaymentMode.ONLINE,
        idempotency_key="pay_bad_sig",
    )

    payload_dict = {
        "event_id": "evt_bad_sig",
        "payment_intent_id": str(intent.id),
        "amount": "340.00",
        "currency": "INR",
        "status": "success",
    }
    raw_body = json.dumps(payload_dict).encode("utf-8")

    with pytest.raises(PaymentConflict) as exc:
        await payment_service.handle_provider_webhook(
            "fake",
            raw_body,
            {"X-Ainza-Signature": "invalid_forged_signature"},
            "secret",
        )
    assert exc.value.code == "bad_signature"

    # Intent must remain pending
    fresh_intent = await payment_service.get_payment_intent(intent.id)
    assert fresh_intent.status == PaymentStatus.PENDING


@pytest.mark.asyncio
async def test_28_wrong_amount_rejected(session: AsyncSession):
    data = await urban_tadka(session)
    await create_finalized_invoice(session, data, total=Decimal("340.00"))

    payment_service = PaymentService(session)
    intent = await payment_service.create_payment_intent(
        dining_session_id=data["dining_session"].id,
        payment_mode=PaymentMode.ONLINE,
        idempotency_key="pay_wrong_amt",
    )

    secret = get_settings().fake_payment_webhook_secret
    # Webhook claims only 100.00 was paid instead of 340.00
    payload_dict = {
        "event_id": "evt_wrong_amt",
        "payment_intent_id": str(intent.id),
        "amount": "100.00",
        "currency": "INR",
        "status": "success",
    }
    raw_body = json.dumps(payload_dict).encode("utf-8")
    sig = FakeDeterministicPaymentAdapter.sign_payload(raw_body, secret)

    with pytest.raises(PaymentConflict) as exc:
        await payment_service.handle_provider_webhook(
            "fake",
            raw_body,
            {"X-Ainza-Signature": sig},
            secret,
        )
    assert exc.value.code == "payment_amount_mismatch"

    fresh_intent = await payment_service.get_payment_intent(intent.id)
    assert fresh_intent.status != PaymentStatus.SUCCESS
    assert fresh_intent.attempts[-1].status == PaymentAttemptStatus.FAILED


@pytest.mark.asyncio
async def test_29_duplicate_webhook_ignored_safely(session: AsyncSession):
    data = await urban_tadka(session)
    await create_finalized_invoice(session, data, total=Decimal("340.00"))

    payment_service = PaymentService(session)
    intent = await payment_service.create_payment_intent(
        dining_session_id=data["dining_session"].id,
        payment_mode=PaymentMode.ONLINE,
        idempotency_key="pay_dup_hook",
    )

    secret = get_settings().fake_payment_webhook_secret
    payload_dict = {
        "event_id": "evt_dup",
        "payment_intent_id": str(intent.id),
        "amount": "340.00",
        "currency": "INR",
        "status": "success",
    }
    raw_body = json.dumps(payload_dict).encode("utf-8")
    sig = FakeDeterministicPaymentAdapter.sign_payload(raw_body, secret)

    # First delivery
    intent1, is_dup1 = await payment_service.handle_provider_webhook(
        "fake", raw_body, {"X-Ainza-Signature": sig}, secret
    )
    assert is_dup1 is False
    assert intent1.status == PaymentStatus.SUCCESS

    # Second delivery
    intent2, is_dup2 = await payment_service.handle_provider_webhook(
        "fake", raw_body, {"X-Ainza-Signature": sig}, secret
    )
    assert is_dup2 is True
    assert intent2.status == PaymentStatus.SUCCESS


@pytest.mark.asyncio
async def test_30_failed_payment_remains_unpaid(session: AsyncSession):
    data = await urban_tadka(session)
    await create_finalized_invoice(session, data, total=Decimal("340.00"))

    payment_service = PaymentService(session)
    intent = await payment_service.create_payment_intent(
        dining_session_id=data["dining_session"].id,
        payment_mode=PaymentMode.ONLINE,
        idempotency_key="pay_fail_remains_unpaid",
    )

    secret = get_settings().fake_payment_webhook_secret
    payload_dict = {
        "event_id": "evt_fail",
        "payment_intent_id": str(intent.id),
        "amount": "340.00",
        "currency": "INR",
        "status": "failed",
    }
    raw_body = json.dumps(payload_dict).encode("utf-8")
    sig = FakeDeterministicPaymentAdapter.sign_payload(raw_body, secret)

    updated_intent, _ = await payment_service.handle_provider_webhook(
        "fake", raw_body, {"X-Ainza-Signature": sig}, secret
    )
    assert updated_intent.status == PaymentStatus.FAILED
    assert updated_intent.status != PaymentStatus.SUCCESS


@pytest.mark.asyncio
async def test_31_pay_at_table_pending_workflow(session: AsyncSession):
    data = await urban_tadka(session)
    await create_finalized_invoice(session, data, total=Decimal("250.00"))

    payment_service = PaymentService(session)
    intent = await payment_service.create_payment_intent(
        dining_session_id=data["dining_session"].id,
        payment_mode=PaymentMode.PAY_AT_TABLE,
        idempotency_key="pay_table_1",
    )

    assert intent.payment_mode == PaymentMode.PAY_AT_TABLE
    assert intent.status == PaymentStatus.PENDING
    assert "manual" in intent.qr_payload


@pytest.mark.asyncio
async def test_32_authorized_staff_marks_external_table_payment_complete(session: AsyncSession):
    data = await urban_tadka(session)
    await create_finalized_invoice(session, data, total=Decimal("250.00"))

    payment_service = PaymentService(session)
    intent = await payment_service.create_payment_intent(
        dining_session_id=data["dining_session"].id,
        payment_mode=PaymentMode.PAY_AT_TABLE,
        idempotency_key="pay_table_confirm",
    )

    confirmed = await payment_service.confirm_manual_payment(
        intent.id,
        actor_type=AIActorType.STAFF,
        staff_actor_id="waiter_07",
        notes="Cash received at table 2",
    )

    assert confirmed.status == PaymentStatus.SUCCESS
    assert confirmed.attempts[-1].provider_reference == "staff_waiter_07"


@pytest.mark.asyncio
async def test_33_unauthorized_customer_cannot_confirm_table_payment(session: AsyncSession):
    data = await urban_tadka(session)
    await create_finalized_invoice(session, data, total=Decimal("250.00"))

    payment_service = PaymentService(session)
    intent = await payment_service.create_payment_intent(
        dining_session_id=data["dining_session"].id,
        payment_mode=PaymentMode.PAY_AT_TABLE,
        idempotency_key="pay_cust_forbid",
    )

    with pytest.raises(PaymentConflict) as exc:
        await payment_service.confirm_manual_payment(
            intent.id,
            actor_type=AIActorType.CUSTOMER,
            staff_actor_id="customer_attempt",
        )
    assert exc.value.code == "payment_confirmation_forbidden"


@pytest.mark.asyncio
async def test_34_invoice_session_lifecycle_remains_correct(session: AsyncSession):
    data = await urban_tadka(session)
    invoice = await create_finalized_invoice(session, data, total=Decimal("200.00"))

    payment_service = PaymentService(session)
    intent = await payment_service.create_payment_intent(
        dining_session_id=data["dining_session"].id,
        payment_mode=PaymentMode.ONLINE,
        idempotency_key="pay_lifecycle_test",
    )

    assert intent.invoice_id == invoice.id
    assert intent.amount == invoice.invoice_total
    assert intent.currency_code == invoice.currency_code
