"""Owner analytics AI tools — read-only SQL aggregations for business insights.

Analytics are computed from *submitted* ``DiningOrder`` / ``DiningOrderItem`` records
(i.e. orders that have been placed, not live carts).  All queries are scoped to the
authenticated outlet via ``AIToolContext.outlet_id`` through the ``DiningSession`` join.

All tools are tagged ``READ_ONLY`` and ``requires_confirmation=False``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.ai.context import AIActorType, AIToolContext
from ainza_restaurant.ai.models import AIToolSafetyLevel
from ainza_restaurant.ai.tools.definitions import AIToolDefinition
from ainza_restaurant.dining.models import DiningSession
from ainza_restaurant.domain.enums import DiningOrderStatus
from ainza_restaurant.ordering.models import (
    DiningOrder,
    DiningOrderItem,
    DiningOrderItemModifier,
)

OWNER = frozenset({AIActorType.OWNER})


# ── Input schemas ──────────────────────────────────────────────────────────────


class AnalyticsPeriodInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_back: int = Field(
        default=30, ge=1, le=90,
        description="Days of history to analyse (1–90, default 30)",
    )


class DishPerformanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_back: int = Field(default=30, ge=1, le=90)
    limit: int = Field(default=20, ge=1, le=50, description="Max dishes to return")
    sort_by: str = Field(
        default="revenue",
        description="Sort key: 'revenue' (default), 'units_sold'",
    )


class CategoryMixInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_back: int = Field(default=30, ge=1, le=90)


class PeakHoursInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_back: int = Field(default=30, ge=1, le=90)


class ModifierUsageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_back: int = Field(default=30, ge=1, le=90)
    limit: int = Field(default=20, ge=1, le=50)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _cutoff(days_back: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days_back)


def _dec(value: Any) -> str | None:
    if value is None:
        return None
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


def _completed_orders_for_outlet(outlet_id: object, cutoff: datetime):
    """Base subquery filter: submitted orders for this outlet after cutoff."""
    return (
        DiningOrder.status != DiningOrderStatus.CANCELLED,
        DiningOrder.submitted_at >= cutoff,
        DiningOrder.dining_session_id.in_(
            select(DiningSession.id).where(DiningSession.outlet_id == outlet_id)
        ),
    )


# ── Tool handlers ──────────────────────────────────────────────────────────────


async def owner_orders_summary(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> dict[str, Any]:
    """Total orders, revenue, average order value, and cancellation rate."""
    data = cast(AnalyticsPeriodInput, payload)
    cutoff = _cutoff(data.days_back)
    outlet_sessions = select(DiningSession.id).where(
        DiningSession.outlet_id == context.outlet_id
    )

    # All orders in period (including cancelled) for rate calculation
    all_rows = await session.execute(
        select(
            func.count(DiningOrder.id).label("total"),
            func.count(DiningOrder.id)
            .filter(DiningOrder.status == DiningOrderStatus.CANCELLED)
            .label("cancelled"),
        ).where(
            DiningOrder.submitted_at >= cutoff,
            DiningOrder.dining_session_id.in_(outlet_sessions),
        )
    )
    all_row = all_rows.one()
    total = all_row.total or 0
    cancelled = all_row.cancelled or 0

    # Revenue from completed orders only
    rev_rows = await session.execute(
        select(
            func.sum(DiningOrder.subtotal_after_discount).label("gross_revenue"),
            func.avg(DiningOrder.subtotal_after_discount).label("avg_order_value"),
        ).where(
            DiningOrder.submitted_at >= cutoff,
            DiningOrder.status != DiningOrderStatus.CANCELLED,
            DiningOrder.dining_session_id.in_(outlet_sessions),
        )
    )
    rev_row = rev_rows.one()

    return {
        "period_days": data.days_back,
        "total_orders": total,
        "cancelled_orders": cancelled,
        "completed_orders": total - cancelled,
        "completion_rate_pct": round((total - cancelled) / total * 100, 1) if total else None,
        "gross_revenue": _dec(rev_row.gross_revenue),
        "avg_order_value": _dec(rev_row.avg_order_value),
    }


async def owner_dish_performance(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> list[dict[str, Any]]:
    """Per-dish units sold, revenue, and order count for completed orders."""
    data = cast(DishPerformanceInput, payload)
    cutoff = _cutoff(data.days_back)

    sort_col = (
        func.sum(DiningOrderItem.line_subtotal_snapshot).desc()
        if data.sort_by != "units_sold"
        else func.sum(DiningOrderItem.quantity).desc()
    )

    rows = await session.execute(
        select(
            DiningOrderItem.dish_name_snapshot.label("dish_name"),
            func.sum(DiningOrderItem.quantity).label("units_sold"),
            func.sum(DiningOrderItem.line_subtotal_snapshot).label("revenue"),
            func.count(DiningOrderItem.order_id.distinct()).label("order_count"),
        )
        .join(DiningOrder, DiningOrderItem.order_id == DiningOrder.id)
        .where(
            DiningOrder.submitted_at >= cutoff,
            DiningOrder.status != DiningOrderStatus.CANCELLED,
            DiningOrder.dining_session_id.in_(
                select(DiningSession.id).where(DiningSession.outlet_id == context.outlet_id)
            ),
        )
        .group_by(DiningOrderItem.dish_name_snapshot)
        .order_by(sort_col)
        .limit(data.limit)
    )

    return [
        {
            "dish": row.dish_name,
            "units_sold": row.units_sold,
            "revenue": _dec(row.revenue),
            "order_count": row.order_count,
        }
        for row in rows
    ]


async def owner_category_mix(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> list[dict[str, Any]]:
    """Revenue and unit share by menu category for completed orders."""
    from ainza_restaurant.menu.models import Category, Dish, DishVariant

    data = cast(CategoryMixInput, payload)
    cutoff = _cutoff(data.days_back)

    rows = await session.execute(
        select(
            Category.name.label("category_name"),
            func.sum(DiningOrderItem.quantity).label("units_sold"),
            func.sum(DiningOrderItem.line_subtotal_snapshot).label("revenue"),
        )
        .join(DiningOrder, DiningOrderItem.order_id == DiningOrder.id)
        .join(Dish, DiningOrderItem.dish_id == Dish.id)
        .join(Category, Dish.category_id == Category.id)
        .where(
            DiningOrder.submitted_at >= cutoff,
            DiningOrder.status != DiningOrderStatus.CANCELLED,
            DiningOrder.dining_session_id.in_(
                select(DiningSession.id).where(DiningSession.outlet_id == context.outlet_id)
            ),
        )
        .group_by(Category.id, Category.name)
        .order_by(func.sum(DiningOrderItem.line_subtotal_snapshot).desc())
    )

    results = [
        {
            "category": row.category_name,
            "units_sold": row.units_sold,
            "revenue": _dec(row.revenue),
        }
        for row in rows
    ]
    total_rev = sum(float(r["revenue"]) for r in results if r["revenue"] is not None)
    for r in results:
        r["revenue_share_pct"] = (
            round(float(r["revenue"]) / total_rev * 100, 1)  # type: ignore[arg-type]
            if r["revenue"] and total_rev
            else None
        )

    return results


async def owner_peak_hours(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> list[dict[str, Any]]:
    """Order count by hour of day (0–23 UTC) across the period."""
    data = cast(PeakHoursInput, payload)
    cutoff = _cutoff(data.days_back)

    rows = await session.execute(
        select(
            func.strftime("%H", DiningOrder.submitted_at).label("hour"),
            func.count(DiningOrder.id).label("order_count"),
        )
        .where(
            DiningOrder.submitted_at >= cutoff,
            DiningOrder.status != DiningOrderStatus.CANCELLED,
            DiningOrder.dining_session_id.in_(
                select(DiningSession.id).where(DiningSession.outlet_id == context.outlet_id)
            ),
        )
        .group_by(func.strftime("%H", DiningOrder.submitted_at))
        .order_by(func.strftime("%H", DiningOrder.submitted_at))
    )

    hour_map = {int(row.hour): row.order_count for row in rows if row.hour is not None}
    return [
        {"hour": h, "label": f"{h:02d}:00", "order_count": hour_map.get(h, 0)}
        for h in range(24)
    ]


async def owner_modifier_usage(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> list[dict[str, Any]]:
    """Most chosen modifier options (e.g. 'Extra Spicy', 'No Onion') for the period."""
    data = cast(ModifierUsageInput, payload)
    cutoff = _cutoff(data.days_back)

    rows = await session.execute(
        select(
            DiningOrderItemModifier.modifier_option_name_snapshot.label("modifier"),
            func.count(DiningOrderItemModifier.id).label("times_chosen"),
        )
        .join(DiningOrderItem, DiningOrderItemModifier.order_item_id == DiningOrderItem.id)
        .join(DiningOrder, DiningOrderItem.order_id == DiningOrder.id)
        .where(
            DiningOrder.submitted_at >= cutoff,
            DiningOrder.status != DiningOrderStatus.CANCELLED,
            DiningOrder.dining_session_id.in_(
                select(DiningSession.id).where(DiningSession.outlet_id == context.outlet_id)
            ),
        )
        .group_by(DiningOrderItemModifier.modifier_option_name_snapshot)
        .order_by(func.count(DiningOrderItemModifier.id).desc())
        .limit(data.limit)
    )

    return [{"modifier": row.modifier, "times_chosen": row.times_chosen} for row in rows]


# ── Tool definitions ───────────────────────────────────────────────────────────

OWNER_ANALYTICS_TOOLS: list[AIToolDefinition] = [
    AIToolDefinition(
        name="owner_orders_summary",
        description=(
            "Returns total order count, gross revenue, average order value, and "
            "cancellation rate for the outlet over the last N days (default 30, max 90). "
            "Call this first when the owner asks for a business overview or revenue summary."
        ),
        input_model=AnalyticsPeriodInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=owner_orders_summary,
    ),
    AIToolDefinition(
        name="owner_dish_performance",
        description=(
            "Returns top dishes ranked by revenue (default) or units sold over the last N days. "
            "Use to identify best-sellers and underperforming menu items."
        ),
        input_model=DishPerformanceInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=owner_dish_performance,
    ),
    AIToolDefinition(
        name="owner_category_mix",
        description=(
            "Returns revenue and unit share across menu categories over the last N days. "
            "Use to understand which sections of the menu drive the most business."
        ),
        input_model=CategoryMixInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=owner_category_mix,
    ),
    AIToolDefinition(
        name="owner_peak_hours",
        description=(
            "Returns order count by hour of day (0–23 UTC) for the last N days. "
            "Use to identify busy and slow periods for staffing and food prep planning."
        ),
        input_model=PeakHoursInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=owner_peak_hours,
    ),
    AIToolDefinition(
        name="owner_modifier_usage",
        description=(
            "Returns the most frequently chosen modifier options (e.g. 'Extra Spicy', 'No Onion') "
            "over the last N days. Use to optimise modifier menus and ingredient prep."
        ),
        input_model=ModifierUsageInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=owner_modifier_usage,
    ),
]
