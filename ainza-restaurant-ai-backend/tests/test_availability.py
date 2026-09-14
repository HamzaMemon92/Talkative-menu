from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.availability.models import (
    AvailabilityProposal,
    AvailabilityProposalAffectedDish,
    DishAvailabilityOverride,
    IngredientAvailabilityOverride,
)
from ainza_restaurant.availability.schemas import AvailabilityProposalCreate
from ainza_restaurant.availability.service import AvailabilityConflict, AvailabilityService
from ainza_restaurant.db.base import Base
from ainza_restaurant.db.session import get_db_session
from ainza_restaurant.domain.enums import (
    AvailabilityAction,
    AvailabilityDurationMode,
    AvailabilityReasonCode,
    MenuStatus,
    ReviewStatus,
)
from ainza_restaurant.main import app
from ainza_restaurant.menu.models import Category, Dish, DishIngredient, Ingredient, Menu
from ainza_restaurant.restaurants.models import (
    Restaurant,
    RestaurantOutlet,
    WeeklyOperatingInterval,
)


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


def fixed_now() -> datetime:
    return datetime(2026, 9, 7, 15, 30, tzinfo=UTC)  # Monday 21:00 Asia/Kolkata.


async def _urban_tadka(session: AsyncSession, suffix: str = "") -> dict[str, object]:
    slug_suffix = f"-{suffix}" if suffix else ""
    restaurant = Restaurant(name=f"Urban Tadka {suffix}".strip(), slug=f"urban-tadka{slug_suffix}")
    session.add(restaurant)
    await session.flush()
    outlet = RestaurantOutlet(
        restaurant_id=restaurant.id,
        name="Urban Tadka Main",
        address_line1="1 Market Street",
        city="Pune",
        state="Maharashtra",
        postal_code="411001",
        timezone="Asia/Kolkata",
        is_primary=True,
    )
    session.add(outlet)
    await session.flush()
    session.add_all(
        [
            WeeklyOperatingInterval(
                outlet_id=outlet.id, weekday=0, opens_at=time(11), closes_at=time(15)
            ),
            WeeklyOperatingInterval(
                outlet_id=outlet.id, weekday=0, opens_at=time(18), closes_at=time(23, 30)
            ),
            WeeklyOperatingInterval(
                outlet_id=outlet.id, weekday=1, opens_at=time(11), closes_at=time(15)
            ),
        ]
    )
    menu = Menu(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="Main Menu",
        status=MenuStatus.PUBLISHED,
        published_at=fixed_now(),
    )
    session.add(menu)
    await session.flush()
    category = Category(menu_id=menu.id, name="Mains", slug="mains")
    paneer = Ingredient(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="Paneer",
        normalized_name="paneer",
    )
    session.add_all([category, paneer])
    await session.flush()
    dishes: list[Dish] = []
    for order, name in enumerate(
        [
            "Paneer Tikka",
            "Paneer Butter Masala",
            "Chilli Paneer",
            "Paneer Pizza",
            "Veg Burger",
        ]
    ):
        dish = Dish(
            menu_id=menu.id,
            category_id=category.id,
            name=name,
            base_price="250.00",
            is_active=True,
            display_order=order,
            review_status=ReviewStatus.CONFIRMED,
        )
        dishes.append(dish)
        session.add(dish)
    pending = Dish(
        menu_id=menu.id,
        category_id=category.id,
        name="Pending Paneer Roll",
        base_price="150.00",
        review_status=ReviewStatus.PENDING_REVIEW,
    )
    session.add(pending)
    await session.flush()
    session.add_all(
        [
            DishIngredient(
                dish_id=dish.id,
                ingredient_id=paneer.id,
                is_required_for_availability=index < 4,
            )
            for index, dish in enumerate(dishes)
        ]
        + [
            DishIngredient(
                dish_id=pending.id,
                ingredient_id=paneer.id,
                is_required_for_availability=True,
            )
        ]
    )
    await session.commit()
    return {
        "restaurant_id": restaurant.id,
        "outlet_id": outlet.id,
        "menu_id": menu.id,
        "category_id": category.id,
        "paneer_id": paneer.id,
        "dishes": dishes,
        "pending_dish_id": pending.id,
    }


def _unavailable_payload(
    target_id: UUID, target_type: str = "ingredient"
) -> AvailabilityProposalCreate:
    return AvailabilityProposalCreate(
        target_type=target_type,
        target_id=target_id,
        action=AvailabilityAction.MARK_UNAVAILABLE,
        duration_mode=AvailabilityDurationMode.UNTIL_NEXT_OPENING,
        reason_code=AvailabilityReasonCode.OUT_OF_STOCK,
        reason_note="Paneer finished during dinner service",
    )


@pytest.mark.asyncio
async def test_realistic_paneer_preview_confirm_and_auto_expiry(session: AsyncSession) -> None:
    data = await _urban_tadka(session)
    service = AvailabilityService(session, now=fixed_now)

    proposal = await service.create_proposal(
        data["outlet_id"], _unavailable_payload(data["paneer_id"])
    )

    assert proposal.status == "pending"
    assert proposal.computed_expires_at == datetime(2026, 9, 8, 5, 30, tzinfo=UTC)
    assert [item.name for item in proposal.affected_dishes] == [
        "Paneer Tikka",
        "Paneer Butter Masala",
        "Chilli Paneer",
        "Paneer Pizza",
    ]
    override_count = await session.scalar(
        select(func.count()).select_from(IngredientAvailabilityOverride)
    )
    assert override_count == 0
    assert (await service.dish_availability(data["dishes"][0].id)).available is True

    confirmed = await service.confirm_proposal(proposal.id, confirm=True)

    assert confirmed.status == "confirmed"
    assert (await service.dish_availability(data["dishes"][0].id)).available is False
    assert (await service.dish_availability(data["dishes"][4].id)).available is True
    assert (await service.dish_availability(data["pending_dish_id"])).available is True
    snapshot_count = await session.scalar(
        select(func.count()).select_from(AvailabilityProposalAffectedDish)
    )
    assert snapshot_count == 4
    menu = await session.get(Menu, data["menu_id"])
    dish = await session.get(Dish, data["dishes"][0].id)
    assert menu is not None and menu.status == MenuStatus.PUBLISHED
    assert dish is not None and dish.is_active is True

    after_expiry = AvailabilityService(session, now=lambda: datetime(2026, 9, 8, 5, 31, tzinfo=UTC))
    assert (await after_expiry.dish_availability(data["dishes"][0].id)).available is True


@pytest.mark.asyncio
async def test_confirmation_required_cancelled_expired_and_double_confirm(
    session: AsyncSession,
) -> None:
    data = await _urban_tadka(session)
    service = AvailabilityService(session, now=fixed_now, proposal_ttl_minutes=15)
    proposal = await service.create_proposal(
        data["outlet_id"], _unavailable_payload(data["dishes"][0].id, "dish")
    )

    with pytest.raises(AvailabilityConflict, match="confirm=true"):
        await service.confirm_proposal(proposal.id, confirm=False)
    assert await session.scalar(select(func.count()).select_from(DishAvailabilityOverride)) == 0

    cancelled = await service.cancel_proposal(proposal.id)
    assert cancelled.status == "cancelled"
    with pytest.raises(AvailabilityConflict) as cancelled_error:
        await service.confirm_proposal(proposal.id, confirm=True)
    assert cancelled_error.value.code == "availability_proposal_cancelled"

    expiring = await service.create_proposal(
        data["outlet_id"], _unavailable_payload(data["dishes"][1].id, "dish")
    )
    late_service = AvailabilityService(
        session,
        now=lambda: fixed_now() + timedelta(minutes=16),
        proposal_ttl_minutes=15,
    )
    with pytest.raises(AvailabilityConflict) as expired_error:
        await late_service.confirm_proposal(expiring.id, confirm=True)
    assert expired_error.value.code == "availability_proposal_expired"

    fresh = await service.create_proposal(
        data["outlet_id"], _unavailable_payload(data["dishes"][2].id, "dish")
    )
    await service.confirm_proposal(fresh.id, confirm=True)
    await service.confirm_proposal(fresh.id, confirm=True)
    assert await session.scalar(select(func.count()).select_from(DishAvailabilityOverride)) == 1


@pytest.mark.asyncio
async def test_transactional_failure_leaves_no_partial_override(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await _urban_tadka(session)
    service = AvailabilityService(session, now=fixed_now)
    proposal = await service.create_proposal(
        data["outlet_id"], _unavailable_payload(data["dishes"][0].id, "dish")
    )
    original_commit = session.commit
    calls = 0

    async def fail_confirmation_commit() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("forced commit failure")
        await original_commit()

    monkeypatch.setattr(session, "commit", fail_confirmation_commit)
    with pytest.raises(RuntimeError, match="forced commit failure"):
        await service.confirm_proposal(proposal.id, confirm=True)
    await session.rollback()
    monkeypatch.setattr(session, "commit", original_commit)

    assert await session.scalar(select(func.count()).select_from(DishAvailabilityOverride)) == 0
    stored = await session.get(AvailabilityProposal, proposal.id)
    assert stored is not None
    assert stored.status == "pending"


@pytest.mark.asyncio
async def test_restore_revokes_history_and_multiple_blockers_remain(session: AsyncSession) -> None:
    data = await _urban_tadka(session)
    service = AvailabilityService(session, now=fixed_now)
    dish_id = data["dishes"][0].id
    ingredient_proposal = await service.create_proposal(
        data["outlet_id"], _unavailable_payload(data["paneer_id"])
    )
    dish_proposal = await service.create_proposal(
        data["outlet_id"], _unavailable_payload(dish_id, "dish")
    )
    await service.confirm_proposal(ingredient_proposal.id, confirm=True)
    await service.confirm_proposal(dish_proposal.id, confirm=True)

    blocked = await service.dish_availability(dish_id)
    assert blocked.available is False
    assert [cause.type for cause in blocked.blocking_causes] == ["dish", "ingredient"]

    restore_dish = await service.create_proposal(
        data["outlet_id"],
        AvailabilityProposalCreate(
            target_type="dish",
            target_id=dish_id,
            action=AvailabilityAction.RESTORE,
        ),
    )
    await service.confirm_proposal(restore_dish.id, confirm=True)
    still_blocked = await service.dish_availability(dish_id)
    assert still_blocked.available is False
    assert [cause.type for cause in still_blocked.blocking_causes] == ["ingredient"]

    restore_ingredient = await service.create_proposal(
        data["outlet_id"],
        AvailabilityProposalCreate(
            target_type="ingredient",
            target_id=data["paneer_id"],
            action=AvailabilityAction.RESTORE,
        ),
    )
    await service.confirm_proposal(restore_ingredient.id, confirm=True)
    assert (await service.dish_availability(dish_id)).available is True
    override = (
        await session.execute(
            select(DishAvailabilityOverride).where(DishAvailabilityOverride.dish_id == dish_id)
        )
    ).scalar_one()
    assert override.revoked_at is not None


@pytest.mark.asyncio
async def test_custom_expiry_indefinite_and_ingredient_endpoint(session: AsyncSession) -> None:
    data = await _urban_tadka(session)
    service = AvailabilityService(session, now=fixed_now)
    until = fixed_now() + timedelta(hours=2)
    proposal = await service.create_proposal(
        data["outlet_id"],
        AvailabilityProposalCreate(
            target_type="ingredient",
            target_id=data["paneer_id"],
            action="mark_unavailable",
            duration_mode="until_timestamp",
            requested_until=until,
            reason_code="other",
        ),
    )
    assert proposal.computed_expires_at == until

    with pytest.raises(AvailabilityConflict) as past_error:
        await service.create_proposal(
            data["outlet_id"],
            AvailabilityProposalCreate(
                target_type="ingredient",
                target_id=data["paneer_id"],
                action="mark_unavailable",
                duration_mode="until_timestamp",
                requested_until=fixed_now() - timedelta(minutes=1),
            ),
        )
    assert past_error.value.code == "invalid_expiry"

    indefinite = await service.create_proposal(
        data["outlet_id"],
        AvailabilityProposalCreate(
            target_type="ingredient",
            target_id=data["paneer_id"],
            action="mark_unavailable",
            duration_mode="indefinite",
        ),
    )
    assert indefinite.computed_expires_at is None
    await service.confirm_proposal(indefinite.id, confirm=True)
    ingredient = await service.ingredient_availability(data["paneer_id"])
    assert ingredient.available is False
    assert len(ingredient.active_overrides) == 1


@pytest.mark.asyncio
async def test_stale_proposal_and_newly_linked_required_dish(session: AsyncSession) -> None:
    data = await _urban_tadka(session)
    service = AvailabilityService(session, now=fixed_now)
    proposal = await service.create_proposal(
        data["outlet_id"], _unavailable_payload(data["paneer_id"])
    )
    new_dish = Dish(
        menu_id=data["menu_id"],
        category_id=data["category_id"],
        name="Paneer Biryani",
        base_price="300.00",
        review_status=ReviewStatus.CONFIRMED,
    )
    session.add(new_dish)
    await session.flush()
    session.add(
        DishIngredient(
            dish_id=new_dish.id,
            ingredient_id=data["paneer_id"],
            is_required_for_availability=True,
        )
    )
    await session.commit()

    with pytest.raises(AvailabilityConflict) as stale:
        await service.confirm_proposal(proposal.id, confirm=True)
    assert stale.value.code == "availability_proposal_stale"

    fresh = await service.create_proposal(
        data["outlet_id"], _unavailable_payload(data["paneer_id"])
    )
    await service.confirm_proposal(fresh.id, confirm=True)
    assert (await service.dish_availability(new_dish.id)).available is False


@pytest.mark.asyncio
async def test_operating_hours_changed_before_confirm_is_stale(session: AsyncSession) -> None:
    data = await _urban_tadka(session)
    service = AvailabilityService(session, now=fixed_now)
    proposal = await service.create_proposal(
        data["outlet_id"], _unavailable_payload(data["paneer_id"])
    )
    session.add(
        WeeklyOperatingInterval(
            outlet_id=data["outlet_id"], weekday=1, opens_at=time(9), closes_at=time(10)
        )
    )
    await session.commit()

    with pytest.raises(AvailabilityConflict) as stale:
        await service.confirm_proposal(proposal.id, confirm=True)
    assert stale.value.code == "availability_proposal_stale"


@pytest.mark.asyncio
async def test_cross_outlet_targets_are_rejected_and_names_are_not_inferred(
    session: AsyncSession,
) -> None:
    first = await _urban_tadka(session, "first")
    second = await _urban_tadka(session, "second")
    service = AvailabilityService(session, now=fixed_now)
    with pytest.raises(AvailabilityConflict) as wrong_dish:
        await service.create_proposal(
            first["outlet_id"], _unavailable_payload(second["dishes"][0].id, "dish")
        )
    assert wrong_dish.value.code == "availability_target_wrong_outlet"
    with pytest.raises(AvailabilityConflict) as wrong_ingredient:
        await service.create_proposal(first["outlet_id"], _unavailable_payload(second["paneer_id"]))
    assert wrong_ingredient.value.code == "availability_target_wrong_outlet"

    ingredient_proposal = await service.create_proposal(
        first["outlet_id"], _unavailable_payload(first["paneer_id"])
    )
    await service.confirm_proposal(ingredient_proposal.id, confirm=True)
    unrelated = Dish(
        menu_id=first["menu_id"],
        category_id=first["category_id"],
        name="Paneer Named Only",
        base_price="100.00",
        review_status=ReviewStatus.CONFIRMED,
    )
    session.add(unrelated)
    await session.commit()
    assert (await service.dish_availability(unrelated.id)).available is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("now", "intervals", "expected"),
    [
        (
            datetime(2026, 9, 7, 8, 30, tzinfo=UTC),
            [(0, time(11), time(15)), (0, time(18), time(23, 30))],
            datetime(2026, 9, 7, 12, 30, tzinfo=UTC),
        ),
        (
            datetime(2026, 9, 7, 10, 30, tzinfo=UTC),
            [(0, time(11), time(15)), (0, time(18), time(23, 30))],
            datetime(2026, 9, 7, 12, 30, tzinfo=UTC),
        ),
        (
            datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
            [(0, time(11), time(15)), (0, time(18), time(23, 30)), (1, time(11), time(15))],
            datetime(2026, 9, 8, 5, 30, tzinfo=UTC),
        ),
        (
            datetime(2026, 9, 11, 19, 30, tzinfo=UTC),
            [(4, time(18), time(2)), (5, time(18), time(22))],
            datetime(2026, 9, 12, 12, 30, tzinfo=UTC),
        ),
        (
            datetime(2026, 9, 7, 18, 0, tzinfo=UTC),
            [(0, time(11), time(15)), (2, time(9), time(12))],
            datetime(2026, 9, 9, 3, 30, tzinfo=UTC),
        ),
        (
            datetime(2026, 9, 13, 18, 0, tzinfo=UTC),
            [(6, time(20), time(23)), (0, time(9), time(12))],
            datetime(2026, 9, 14, 3, 30, tzinfo=UTC),
        ),
    ],
)
async def test_next_opening_edge_cases(
    session: AsyncSession,
    now: datetime,
    intervals: list[tuple[int, time, time]],
    expected: datetime,
) -> None:
    restaurant = Restaurant(name="Clock Cafe", slug=f"clock-cafe-{now.timestamp()}")
    session.add(restaurant)
    await session.flush()
    outlet = RestaurantOutlet(
        restaurant_id=restaurant.id,
        name="Clock",
        address_line1="1 Time Road",
        city="Pune",
        state="Maharashtra",
        postal_code="411001",
        timezone="Asia/Kolkata",
        is_primary=True,
    )
    session.add(outlet)
    await session.flush()
    for weekday, opens, closes in intervals:
        session.add(
            WeeklyOperatingInterval(
                outlet_id=outlet.id, weekday=weekday, opens_at=opens, closes_at=closes
            )
        )
    await session.commit()

    service = AvailabilityService(session, now=lambda: now)
    loaded = await service._outlet(outlet.id)
    assert await service._next_opening_utc(loaded, now) == expected


@pytest.mark.asyncio
async def test_continuous_24_7_has_no_next_opening_boundary(session: AsyncSession) -> None:
    restaurant = Restaurant(name="Always Open", slug="always-open")
    session.add(restaurant)
    await session.flush()
    outlet = RestaurantOutlet(
        restaurant_id=restaurant.id,
        name="Always",
        address_line1="1 Road",
        city="Pune",
        state="Maharashtra",
        postal_code="411001",
        timezone="Asia/Kolkata",
        is_primary=True,
    )
    session.add(outlet)
    await session.flush()
    for weekday in range(7):
        session.add(WeeklyOperatingInterval(outlet_id=outlet.id, weekday=weekday, is_full_day=True))
    await session.commit()

    service = AvailabilityService(session, now=fixed_now)
    with pytest.raises(AvailabilityConflict) as error:
        await service._next_opening_utc(await service._outlet(outlet.id), fixed_now())
    assert error.value.code == "no_next_opening_boundary"


def test_availability_api_smoke_path() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def setup() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            await _urban_tadka(db)

    async def teardown() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    async def override_db():
        async with sessions() as db:
            yield db

    import asyncio

    asyncio.run(setup())
    app.dependency_overrides[get_db_session] = override_db
    try:
        with TestClient(app) as client:
            outlet = client.get("/api/v1/restaurants").json()[0]
            restaurant_id = outlet["id"]
            outlet_id = client.get(f"/api/v1/restaurants/{restaurant_id}/outlets").json()[0]["id"]
            ingredient_id = client.get(f"/api/v1/outlets/{outlet_id}/ingredients").json()[0]["id"]
            proposal = client.post(
                f"/api/v1/outlets/{outlet_id}/availability/proposals",
                json={
                    "target_type": "ingredient",
                    "target_id": ingredient_id,
                    "action": "mark_unavailable",
                    "duration_mode": "indefinite",
                    "reason_code": "out_of_stock",
                },
            )
            assert proposal.status_code == 201
            assert len(proposal.json()["affected_dishes"]) == 4
            confirm = client.post(
                f"/api/v1/availability-proposals/{proposal.json()['id']}/confirm",
                json={"confirm": True},
            )
            assert confirm.status_code == 200
            assert (
                client.get(f"/api/v1/ingredients/{ingredient_id}/availability").json()["available"]
                is False
            )
            unavailable = client.get(f"/api/v1/outlets/{outlet_id}/availability?available=false")
            assert unavailable.status_code == 200
            assert len(unavailable.json()["dishes"]) == 4
    finally:
        app.dependency_overrides.clear()
        asyncio.run(teardown())
