from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.availability.schemas import AvailabilityProposalCreate
from ainza_restaurant.availability.service import AvailabilityService
from ainza_restaurant.db.base import Base
from ainza_restaurant.domain.enums import (
    AvailabilityAction,
    AvailabilityDurationMode,
    AvailabilityReasonCode,
    BadgeCode,
    MenuStatus,
    OfferType,
    ReviewStatus,
)
from ainza_restaurant.menu.models import (
    Category,
    Dish,
    DishBadge,
    DishIngredient,
    DishVariant,
    Ingredient,
    Menu,
)
from ainza_restaurant.merchandising.schemas import (
    ComboItemInput,
    ComboItemsReplace,
    FeaturedCreate,
    OfferCreate,
    OfferPreviewRequest,
    PreviewItem,
    ScopeCategoryReplace,
    ScopeDishReplace,
    SpecialCreate,
)
from ainza_restaurant.merchandising.service import MerchandisingConflict, MerchandisingService
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


def monday_20() -> datetime:
    return datetime(2026, 9, 7, 14, 30, tzinfo=UTC)  # 20:00 Asia/Kolkata.


async def urban_tadka(session: AsyncSession) -> dict[str, object]:
    restaurant = Restaurant(name="Urban Tadka", slug="urban-tadka")
    session.add(restaurant)
    await session.flush()
    outlet = RestaurantOutlet(
        restaurant_id=restaurant.id,
        name="Urban Tadka Vesu",
        address_line1="1 Vesu Road",
        city="Surat",
        state="Gujarat",
        postal_code="395007",
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
                outlet_id=outlet.id, weekday=0, opens_at=time(18), closes_at=time(23)
            ),
            WeeklyOperatingInterval(
                outlet_id=outlet.id, weekday=4, opens_at=time(18), closes_at=time(2)
            ),
            WeeklyOperatingInterval(
                outlet_id=outlet.id, weekday=6, opens_at=time(20), closes_at=time(23)
            ),
        ]
    )
    menu = Menu(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="Main Menu",
        status=MenuStatus.PUBLISHED,
        published_at=monday_20(),
    )
    draft_menu = Menu(restaurant_id=restaurant.id, outlet_id=outlet.id, name="Draft")
    session.add_all([menu, draft_menu])
    await session.flush()
    mains = Category(menu_id=menu.id, name="Mains", slug="mains")
    desserts = Category(menu_id=menu.id, name="Desserts", slug="desserts")
    session.add_all([mains, desserts])
    paneer = Ingredient(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="Paneer",
        normalized_name="paneer",
    )
    session.add(paneer)
    await session.flush()

    def dish(name: str, price: str, category_id, review=ReviewStatus.CONFIRMED) -> Dish:
        item = Dish(
            menu_id=menu.id,
            category_id=category_id,
            name=name,
            base_price=Decimal(price),
            review_status=review,
        )
        session.add(item)
        return item

    tikka = dish("Paneer Tikka", "280.00", mains.id)
    biryani = dish("Paneer Biryani", "320.00", mains.id)
    chicken = dish("Butter Chicken", "390.00", mains.id)
    brownie = dish("Brownie With Ice Cream", "180.00", desserts.id)
    coffee = dish("Cold Coffee", "140.00", desserts.id)
    pending = dish("Pending Roll", "99.00", mains.id, ReviewStatus.PENDING_REVIEW)
    pizza = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Farmhouse Pizza",
        review_status=ReviewStatus.CONFIRMED,
    )
    draft_dish = Dish(
        menu_id=draft_menu.id,
        name="Draft Dish",
        base_price=Decimal("100.00"),
        review_status=ReviewStatus.CONFIRMED,
    )
    session.add_all([pizza, draft_dish])
    await session.flush()
    small = DishVariant(
        dish_id=pizza.id, name="Small", normalized_name="small", price=Decimal("249.00")
    )
    medium = DishVariant(
        dish_id=pizza.id, name="Medium", normalized_name="medium", price=Decimal("349.00")
    )
    large = DishVariant(
        dish_id=pizza.id, name="Large", normalized_name="large", price=Decimal("449.00")
    )
    session.add_all(
        [
            small,
            medium,
            large,
            DishBadge(dish_id=tikka.id, badge=BadgeCode.CHEF_RECOMMENDED),
            DishIngredient(
                dish_id=biryani.id,
                ingredient_id=paneer.id,
                is_required_for_availability=True,
            ),
        ]
    )
    await session.commit()
    return locals()


@pytest.mark.asyncio
async def test_special_service_end_activation_price_and_expiry(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    service = MerchandisingService(session, now=monday_20)
    special = await service.create_special(
        data["outlet"].id,
        SpecialCreate(dish_id=data["biryani"].id, special_price=Decimal("279.00")),
    )
    assert special.status == "draft"
    assert special.effective_active is False
    assert special.starts_at == monday_20()
    assert special.ends_at == datetime(2026, 9, 7, 17, 30, tzinfo=UTC)
    activated = await service.activate_special(special.id, confirm=True)
    assert activated.effective_active is True
    dish = await session.get(Dish, data["biryani"].id)
    assert dish is not None and dish.base_price == Decimal("320.00")
    later = MerchandisingService(session, now=lambda: datetime(2026, 9, 7, 17, 31, tzinfo=UTC))
    assert (await later.get_special(special.id)).effective_active is False


@pytest.mark.asyncio
async def test_special_validation_variants_overlap_and_deactivate(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    service = MerchandisingService(session, now=monday_20)
    with pytest.raises(MerchandisingConflict):
        await service.create_special(
            data["outlet"].id,
            SpecialCreate(dish_id=data["pizza"].id, special_price=Decimal("349.00")),
        )
    first = await service.create_special(
        data["outlet"].id,
        SpecialCreate(
            dish_id=data["pizza"].id,
            variant_id=data["large"].id,
            special_price=Decimal("399.00"),
        ),
    )
    await service.activate_special(first.id, confirm=True)
    with pytest.raises(MerchandisingConflict) as overlap:
        second = await service.create_special(
            data["outlet"].id,
            SpecialCreate(dish_id=data["pizza"].id, variant_id=data["large"].id),
        )
        await service.activate_special(second.id, confirm=True)
    assert overlap.value.code == "overlapping_special"
    deactivated = await service.deactivate_special(first.id, confirm=True)
    assert deactivated.status == "deactivated"
    variant = await session.get(DishVariant, data["large"].id)
    assert variant is not None and variant.price == Decimal("449.00")


@pytest.mark.asyncio
async def test_service_end_edge_cases_and_24_7(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    outlet = data["outlet"]
    cases = [
        (datetime(2026, 9, 7, 8, 30, tzinfo=UTC), datetime(2026, 9, 7, 9, 30, tzinfo=UTC)),
        (datetime(2026, 9, 7, 10, 30, tzinfo=UTC), datetime(2026, 9, 7, 17, 30, tzinfo=UTC)),
        (datetime(2026, 9, 11, 15, 30, tzinfo=UTC), datetime(2026, 9, 11, 20, 30, tzinfo=UTC)),
        (datetime(2026, 9, 11, 19, 30, tzinfo=UTC), datetime(2026, 9, 11, 20, 30, tzinfo=UTC)),
        (datetime(2026, 9, 13, 18, 0, tzinfo=UTC), datetime(2026, 9, 14, 9, 30, tzinfo=UTC)),
    ]
    for now, expected_end in cases:
        service = MerchandisingService(session, now=lambda now=now: now)
        special = await service.create_special(outlet.id, SpecialCreate(dish_id=data["tikka"].id))
        assert special.ends_at == expected_end
    for interval in outlet.operating_intervals:
        interval.is_full_day = True
        interval.opens_at = None
        interval.closes_at = None
    for weekday in {1, 2, 3, 5}:
        session.add(WeeklyOperatingInterval(outlet_id=outlet.id, weekday=weekday, is_full_day=True))
    await session.commit()
    session.expire(outlet, ["operating_intervals"])
    with pytest.raises(MerchandisingConflict) as error:
        await MerchandisingService(session, now=monday_20).create_special(
            outlet.id, SpecialCreate(dish_id=data["tikka"].id)
        )
    assert error.value.code == "no_service_end_boundary"


@pytest.mark.asyncio
async def test_featured_independent_from_price_badge_and_availability(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    service = MerchandisingService(session, now=monday_20)
    featured = await service.create_featured(
        data["outlet"].id,
        FeaturedCreate(dish_id=data["tikka"].id, display_order=2),
    )
    with pytest.raises(MerchandisingConflict):
        await service.activate_featured(featured.id, confirm=False)
    active = await service.activate_featured(featured.id, confirm=True)
    assert active.effective_active is True
    assert active.display_order == 2
    dish = await session.get(Dish, data["tikka"].id)
    assert dish is not None and dish.base_price == Decimal("280.00")
    badges = (
        (await session.execute(select(DishBadge).where(DishBadge.dish_id == dish.id)))
        .scalars()
        .all()
    )
    assert [badge.badge for badge in badges] == [BadgeCode.CHEF_RECOMMENDED]


@pytest.mark.asyncio
async def test_percentage_offer_threshold_cap_and_amount_to_threshold(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    service = MerchandisingService(session, now=monday_20)
    offer = await service.create_offer(
        data["outlet"].id,
        OfferCreate(
            name="Diwali",
            offer_type=OfferType.PERCENTAGE,
            starts_at=monday_20(),
            ends_at=monday_20() + timedelta(days=5),
            minimum_subtotal=Decimal("1500.00"),
            discount_value=Decimal("20.00"),
            maximum_discount=Decimal("500.00"),
        ),
    )
    await service.activate_offer(offer.id, confirm=True)
    preview = await service.preview_offer(
        offer.id,
        OfferPreviewRequest(
            items=[
                PreviewItem(dish_id=data["chicken"].id, quantity=3),
                PreviewItem(dish_id=data["biryani"].id, quantity=2),
            ]
        ),
    )
    assert preview.regular_subtotal == Decimal("1810.00")
    assert preview.discount_amount == Decimal("362.00")
    under = await service.preview_offer(
        offer.id,
        OfferPreviewRequest(items=[PreviewItem(dish_id=data["chicken"].id, quantity=3)]),
    )
    assert under.eligible is False
    assert under.amount_to_threshold == Decimal("330.00")


@pytest.mark.asyncio
async def test_flat_dish_and_category_scope(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    service = MerchandisingService(session, now=monday_20)
    offer = await service.create_offer(
        data["outlet"].id,
        OfferCreate(
            name="Dessert",
            offer_type=OfferType.FLAT,
            starts_at=monday_20(),
            ends_at=monday_20() + timedelta(days=1),
            minimum_subtotal=Decimal("500.00"),
            discount_value=Decimal("200.00"),
        ),
    )
    await service.replace_offer_category_scope(
        offer.id, ScopeCategoryReplace(category_ids=[data["desserts"].id])
    )
    await service.activate_offer(offer.id, confirm=True)
    preview = await service.preview_offer(
        offer.id,
        OfferPreviewRequest(
            items=[
                PreviewItem(dish_id=data["brownie"].id, quantity=2),
                PreviewItem(dish_id=data["coffee"].id, quantity=1),
                PreviewItem(dish_id=data["chicken"].id, quantity=1),
            ]
        ),
    )
    assert preview.eligible_subtotal == Decimal("500.00")
    assert preview.discount_amount == Decimal("200.00")
    assert preview.post_discount_subtotal == Decimal("690.00")
    dish_offer = await service.create_offer(
        data["outlet"].id,
        OfferCreate(
            name="Tikka",
            offer_type=OfferType.FLAT,
            starts_at=monday_20(),
            ends_at=monday_20() + timedelta(days=1),
            discount_value=Decimal("500.00"),
        ),
    )
    await service.replace_offer_dish_scope(
        dish_offer.id, ScopeDishReplace(dish_ids=[data["tikka"].id])
    )
    await service.activate_offer(dish_offer.id, confirm=True)
    dish_preview = await service.preview_offer(
        dish_offer.id,
        OfferPreviewRequest(items=[PreviewItem(dish_id=data["tikka"].id, quantity=1)]),
    )
    assert dish_preview.discount_amount == Decimal("280.00")


@pytest.mark.asyncio
async def test_combo_offer_and_variant_specific_matching(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    service = MerchandisingService(session, now=monday_20)
    offer = await service.create_offer(
        data["outlet"].id,
        OfferCreate(
            name="Pizza combo",
            offer_type=OfferType.COMBO_FIXED_PRICE,
            starts_at=monday_20(),
            ends_at=monday_20() + timedelta(days=1),
            combo_price=Decimal("599.00"),
        ),
    )
    await service.replace_combo_items(
        offer.id,
        ComboItemsReplace(
            items=[
                ComboItemInput(
                    dish_id=data["pizza"].id,
                    variant_id=data["large"].id,
                    required_quantity=1,
                ),
                ComboItemInput(dish_id=data["coffee"].id, required_quantity=1),
                ComboItemInput(dish_id=data["brownie"].id, required_quantity=1),
            ]
        ),
    )
    await service.activate_offer(offer.id, confirm=True)
    preview = await service.preview_offer(
        offer.id,
        OfferPreviewRequest(
            items=[
                PreviewItem(dish_id=data["pizza"].id, variant_id=data["large"].id, quantity=2),
                PreviewItem(dish_id=data["coffee"].id, quantity=2),
                PreviewItem(dish_id=data["brownie"].id, quantity=2),
            ]
        ),
    )
    assert preview.complete_combo_count == 2
    assert preview.discount_amount == Decimal("340.00")
    partial = await service.preview_offer(
        offer.id,
        OfferPreviewRequest(
            items=[
                PreviewItem(dish_id=data["pizza"].id, variant_id=data["small"].id, quantity=1),
                PreviewItem(dish_id=data["coffee"].id, quantity=1),
                PreviewItem(dish_id=data["brownie"].id, quantity=1),
            ]
        ),
    )
    assert partial.complete_combo_count == 0
    assert partial.discount_amount == Decimal("0.00")


@pytest.mark.asyncio
async def test_special_price_precedes_offer_and_availability_is_reported(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    service = MerchandisingService(session, now=monday_20)
    special = await service.create_special(
        data["outlet"].id,
        SpecialCreate(dish_id=data["biryani"].id, special_price=Decimal("279.00")),
    )
    await service.activate_special(special.id, confirm=True)
    offer = await service.create_offer(
        data["outlet"].id,
        OfferCreate(
            name="Flat",
            offer_type=OfferType.FLAT,
            starts_at=monday_20(),
            ends_at=monday_20() + timedelta(days=1),
            discount_value=Decimal("50.00"),
        ),
    )
    await service.activate_offer(offer.id, confirm=True)
    availability = AvailabilityService(session, now=monday_20)
    proposal = await availability.create_proposal(
        data["outlet"].id,
        AvailabilityProposalCreate(
            target_type="ingredient",
            target_id=data["paneer"].id,
            action=AvailabilityAction.MARK_UNAVAILABLE,
            duration_mode=AvailabilityDurationMode.INDEFINITE,
            reason_code=AvailabilityReasonCode.OUT_OF_STOCK,
        ),
    )
    await availability.confirm_proposal(proposal.id, confirm=True)
    preview = await service.preview_offer(
        offer.id, OfferPreviewRequest(items=[PreviewItem(dish_id=data["biryani"].id, quantity=1)])
    )
    assert preview.line_items[0].unit_price == Decimal("279.00")
    assert preview.can_fulfill is False
    assert preview.tax_calculated is False
    assert preview.final_invoice_created is False


@pytest.mark.asyncio
async def test_catalog_safety_pending_draft_and_active_immutable(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    service = MerchandisingService(session, now=monday_20)
    with pytest.raises(MerchandisingConflict):
        await service.create_special(data["outlet"].id, SpecialCreate(dish_id=data["pending"].id))
    with pytest.raises(MerchandisingConflict):
        await service.create_featured(
            data["outlet"].id, FeaturedCreate(dish_id=data["draft_dish"].id)
        )
    offer = await service.create_offer(
        data["outlet"].id,
        OfferCreate(
            name="No edit",
            offer_type=OfferType.FLAT,
            starts_at=monday_20(),
            ends_at=monday_20() + timedelta(days=1),
            discount_value=Decimal("50.00"),
        ),
    )
    await service.activate_offer(offer.id, confirm=True)
    with pytest.raises(MerchandisingConflict) as error:
        await service.patch_offer(offer.id, OfferCreate)  # type: ignore[arg-type]
    assert error.value.code == "offer_active_immutable"


def test_no_manual_bestseller_endpoint_or_model() -> None:
    import ainza_restaurant.api.routes.merchandising as routes
    import ainza_restaurant.merchandising.models as models

    assert "bestseller" not in "\n".join(dir(routes)).lower()
    assert "bestseller" not in "\n".join(dir(models)).lower()
