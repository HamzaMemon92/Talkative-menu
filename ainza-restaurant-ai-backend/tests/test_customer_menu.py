from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.availability.models import (
    DishAvailabilityOverride,
    IngredientAvailabilityOverride,
)
from ainza_restaurant.customer_menu.schemas import CustomerMenuFilters
from ainza_restaurant.customer_menu.service import CustomerMenuNotFound, CustomerMenuService
from ainza_restaurant.db.base import Base
from ainza_restaurant.domain.enums import (
    AlcoholPolicy,
    AllergenStatus,
    AvailabilityReasonCode,
    AvailabilityStatus,
    BadgeCode,
    DietaryClassification,
    HalalCertificationStatus,
    HalalOverride,
    HalalPolicy,
    ImageApprovalStatus,
    ItemType,
    MenuStatus,
    MerchandisingStatus,
    OfferScopeType,
    OfferType,
    PorkPolicy,
    ReviewStatus,
    SpiceLevel,
)
from ainza_restaurant.menu.models import (
    Category,
    Cuisine,
    Dish,
    DishBadge,
    DishCuisine,
    DishImage,
    DishIngredient,
    DishVariant,
    Ingredient,
    Menu,
    ModifierGroup,
    ModifierOption,
)
from ainza_restaurant.merchandising.models import (
    FeaturedDish,
    Offer,
    OfferCategoryScope,
    OfferComboItem,
    TodaysSpecial,
)
from ainza_restaurant.restaurants.models import (
    OutletFoodPolicy,
    OutletTaxProfile,
    Restaurant,
    RestaurantOutlet,
)

NOW = datetime(2026, 9, 10, 7, 0, tzinfo=UTC)


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


async def _urban_tadka(session: AsyncSession, *, bulk_count: int = 0) -> dict[str, object]:
    restaurant = Restaurant(name="Urban Tadka", slug=f"urban-tadka-{uuid4().hex}")
    inactive_restaurant = Restaurant(
        name="Closed Brand",
        slug=f"closed-brand-{uuid4().hex}",
        status="inactive",
    )
    session.add_all([restaurant, inactive_restaurant])
    await session.flush()
    outlet = RestaurantOutlet(
        restaurant_id=restaurant.id,
        name="Urban Tadka - Vesu",
        address_line1="1 Vesu Road",
        city="Surat",
        state="Gujarat",
        postal_code="395007",
        timezone="Asia/Kolkata",
        currency_code="INR",
        is_primary=True,
    )
    inactive_outlet = RestaurantOutlet(
        restaurant_id=restaurant.id,
        name="Inactive Outlet",
        address_line1="2 Vesu Road",
        city="Surat",
        state="Gujarat",
        postal_code="395007",
        timezone="Asia/Kolkata",
        is_active=False,
    )
    closed_brand_outlet = RestaurantOutlet(
        restaurant_id=inactive_restaurant.id,
        name="Closed Brand Outlet",
        address_line1="3 Vesu Road",
        city="Surat",
        state="Gujarat",
        postal_code="395007",
        timezone="Asia/Kolkata",
    )
    session.add_all([outlet, inactive_outlet, closed_brand_outlet])
    await session.flush()
    session.add_all(
        [
            OutletTaxProfile(outlet_id=outlet.id, prices_include_tax=True),
            OutletFoodPolicy(
                outlet_id=outlet.id,
                halal_policy=HalalPolicy.SELECTED_ITEMS_ONLY,
                halal_certification_status=HalalCertificationStatus.RESTAURANT_CLAIMS_CERTIFIED,
                pork_policy=PorkPolicy.NO,
                alcohol_policy=AlcoholPolicy.UNKNOWN,
                notes="Internal owner note",
                information_confirmed=True,
                confirmation=True,
                confirmed_at=NOW,
            ),
            OutletFoodPolicy(
                outlet_id=inactive_outlet.id,
                halal_policy=HalalPolicy.ALL_NONVEG_MEAT_RESTAURANT_DECLARED_HALAL,
                information_confirmed=False,
                confirmation=False,
            ),
        ]
    )
    menu = Menu(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="Published Menu",
        status=MenuStatus.PUBLISHED,
        published_at=NOW - timedelta(days=1),
    )
    draft_menu = Menu(restaurant_id=restaurant.id, outlet_id=outlet.id, name="Draft")
    archived_menu = Menu(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="Archived",
        status=MenuStatus.ARCHIVED,
    )
    session.add_all([menu, draft_menu, archived_menu])
    await session.flush()
    starters = Category(menu_id=menu.id, name="Starters", slug="starters", display_order=1)
    mains = Category(menu_id=menu.id, name="Main Course", slug="main-course", display_order=2)
    pizza_category = Category(menu_id=menu.id, name="Pizza", slug="pizza", display_order=3)
    desserts = Category(menu_id=menu.id, name="Desserts", slug="desserts", display_order=4)
    beverages = Category(menu_id=menu.id, name="Beverages", slug="beverages", display_order=5)
    inactive_category = Category(
        menu_id=menu.id, name="Hidden", slug="hidden", display_order=6, is_active=False
    )
    session.add_all([starters, mains, pizza_category, desserts, beverages, inactive_category])
    indian = Cuisine(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="Indian",
        slug="indian",
        normalized_slug="indian",
    )
    italian = Cuisine(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="Italian",
        slug="italian",
        normalized_slug="italian",
    )
    session.add_all([indian, italian])
    paneer = Ingredient(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="Paneer",
        normalized_name="paneer",
    )
    capsicum = Ingredient(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="Capsicum",
        normalized_name="capsicum",
    )
    session.add_all([paneer, capsicum])
    await session.flush()

    tikka = Dish(
        menu_id=menu.id,
        category_id=starters.id,
        name="Paneer Tikka",
        description="Tandoor grilled paneer starter",
        ingredient_description="Paneer cubes marinated with yogurt, capsicum and spices.",
        base_price=Decimal("280.00"),
        dietary_classification=DietaryClassification.VEGETARIAN,
        vegan_status=AvailabilityStatus.UNKNOWN,
        jain_status=AvailabilityStatus.AVAILABLE,
        halal_status=HalalOverride.UNKNOWN,
        spice_level=SpiceLevel.MEDIUM,
        allergen_information_status=AllergenStatus.UNKNOWN,
        review_status=ReviewStatus.CONFIRMED,
        display_order=1,
    )
    biryani = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Paneer Biryani",
        description="Fragrant rice with paneer",
        base_price=Decimal("320.00"),
        dietary_classification=DietaryClassification.VEGETARIAN,
        spice_level=SpiceLevel.MEDIUM,
        review_status=ReviewStatus.CONFIRMED,
        display_order=1,
    )
    pizza = Dish(
        menu_id=menu.id,
        category_id=pizza_category.id,
        name="Farmhouse Pizza",
        description="Vegetable pizza",
        review_status=ReviewStatus.CONFIRMED,
        display_order=1,
    )
    coffee = Dish(
        menu_id=menu.id,
        category_id=beverages.id,
        name="Cold Coffee",
        base_price=Decimal("140.00"),
        item_type=ItemType.BEVERAGE,
        review_status=ReviewStatus.CONFIRMED,
        display_order=1,
    )
    hidden = Dish(
        menu_id=menu.id,
        category_id=inactive_category.id,
        name="Hidden Dish",
        base_price=Decimal("99.00"),
        review_status=ReviewStatus.CONFIRMED,
    )
    pending = Dish(
        menu_id=menu.id,
        category_id=starters.id,
        name="Pending Roll",
        base_price=Decimal("99.00"),
        review_status=ReviewStatus.PENDING_REVIEW,
    )
    inactive = Dish(
        menu_id=menu.id,
        category_id=starters.id,
        name="Inactive Kebab",
        base_price=Decimal("99.00"),
        review_status=ReviewStatus.CONFIRMED,
        is_active=False,
    )
    draft_dish = Dish(
        menu_id=draft_menu.id,
        name="Draft Dish",
        base_price=Decimal("99.00"),
        review_status=ReviewStatus.CONFIRMED,
    )
    session.add_all([tikka, biryani, pizza, coffee, hidden, pending, inactive, draft_dish])
    await session.flush()
    small = DishVariant(
        dish_id=pizza.id,
        name="Small",
        normalized_name="small",
        price=Decimal("249.00"),
        display_order=1,
    )
    medium = DishVariant(
        dish_id=pizza.id,
        name="Medium",
        normalized_name="medium",
        price=Decimal("349.00"),
        display_order=2,
    )
    large = DishVariant(
        dish_id=pizza.id,
        name="Large",
        normalized_name="large",
        price=Decimal("449.00"),
        display_order=3,
    )
    inactive_variant = DishVariant(
        dish_id=pizza.id,
        name="Party",
        normalized_name="party",
        price=Decimal("799.00"),
        is_active=False,
    )
    group = ModifierGroup(dish_id=tikka.id, name="Add Extras", min_selections=0, max_selections=2)
    inactive_group = ModifierGroup(dish_id=tikka.id, name="Hidden Extras", is_active=False)
    session.add_all([small, medium, large, inactive_variant, group, inactive_group])
    await session.flush()
    session.add_all(
        [
            ModifierOption(group_id=group.id, name="Extra Cheese", price_delta=Decimal("40.00")),
            ModifierOption(group_id=group.id, name="Extra Dip", price_delta=Decimal("20.00")),
            ModifierOption(
                group_id=group.id,
                name="Hidden Option",
                price_delta=Decimal("5.00"),
                is_active=False,
            ),
            DishBadge(dish_id=tikka.id, badge=BadgeCode.CHEF_RECOMMENDED),
            DishBadge(dish_id=tikka.id, badge=BadgeCode.SIGNATURE),
            DishIngredient(
                dish_id=tikka.id,
                ingredient_id=paneer.id,
                is_required_for_availability=True,
            ),
            DishIngredient(
                dish_id=tikka.id,
                ingredient_id=capsicum.id,
                is_required_for_availability=False,
            ),
            DishIngredient(
                dish_id=biryani.id,
                ingredient_id=paneer.id,
                is_required_for_availability=True,
            ),
            DishCuisine(dish_id=tikka.id, cuisine_id=indian.id),
            DishCuisine(dish_id=biryani.id, cuisine_id=indian.id),
            DishCuisine(dish_id=pizza.id, cuisine_id=italian.id),
            DishImage(
                dish_id=tikka.id,
                storage_key="dish/paneer-tikka.jpg",
                alt_text="Paneer Tikka",
                is_primary=True,
                approval_status=ImageApprovalStatus.APPROVED,
            ),
            DishImage(
                dish_id=tikka.id,
                storage_key="dish/paneer-tikka-pending.jpg",
                approval_status=ImageApprovalStatus.PENDING,
            ),
            DishImage(
                dish_id=tikka.id,
                storage_key="dish/paneer-tikka-rejected.jpg",
                approval_status=ImageApprovalStatus.REJECTED,
            ),
            DishImage(
                dish_id=pizza.id,
                variant_id=large.id,
                storage_key="dish/farmhouse-large.jpg",
                is_primary=True,
                approval_status=ImageApprovalStatus.APPROVED,
            ),
        ]
    )
    proposal_id = uuid4()
    session.add_all(
        [
            IngredientAvailabilityOverride(
                ingredient_id=paneer.id,
                starts_at=NOW - timedelta(minutes=5),
                expires_at=None,
                reason_code=AvailabilityReasonCode.OUT_OF_STOCK,
                reason_note="Chef Rahul forgot to order paneer",
                source_proposal_id=proposal_id,
            ),
            DishAvailabilityOverride(
                dish_id=coffee.id,
                starts_at=NOW - timedelta(minutes=5),
                expires_at=NOW - timedelta(minutes=1),
                reason_code=AvailabilityReasonCode.OTHER,
                reason_note="Expired note",
                source_proposal_id=proposal_id,
            ),
        ]
    )
    special = TodaysSpecial(
        outlet_id=outlet.id,
        dish_id=biryani.id,
        special_price=Decimal("279.00"),
        starts_at=NOW - timedelta(hours=1),
        ends_at=NOW + timedelta(hours=2),
        status=MerchandisingStatus.ACTIVE,
        activation_confirmed=True,
        display_note="Lunch special",
    )
    expired_special = TodaysSpecial(
        outlet_id=outlet.id,
        dish_id=tikka.id,
        special_price=Decimal("249.00"),
        starts_at=NOW - timedelta(hours=3),
        ends_at=NOW - timedelta(hours=2),
        status=MerchandisingStatus.ACTIVE,
        activation_confirmed=True,
    )
    variant_special = TodaysSpecial(
        outlet_id=outlet.id,
        dish_id=pizza.id,
        variant_id=large.id,
        special_price=Decimal("399.00"),
        starts_at=NOW - timedelta(hours=1),
        ends_at=NOW + timedelta(hours=2),
        status=MerchandisingStatus.ACTIVE,
        activation_confirmed=True,
    )
    featured = FeaturedDish(
        outlet_id=outlet.id,
        dish_id=tikka.id,
        starts_at=NOW - timedelta(hours=1),
        status=MerchandisingStatus.ACTIVE,
        display_order=2,
        activation_confirmed=True,
    )
    offer = Offer(
        outlet_id=outlet.id,
        name="Diwali 20% Off",
        offer_type=OfferType.PERCENTAGE,
        scope_type=OfferScopeType.SELECTED_CATEGORIES,
        status=MerchandisingStatus.ACTIVE,
        starts_at=NOW - timedelta(days=1),
        ends_at=NOW + timedelta(days=1),
        minimum_subtotal=Decimal("1500.00"),
        discount_value=Decimal("20.00"),
        maximum_discount=Decimal("500.00"),
        activation_confirmed=True,
    )
    combo = Offer(
        outlet_id=outlet.id,
        name="Pizza Combo",
        offer_type=OfferType.COMBO_FIXED_PRICE,
        scope_type=OfferScopeType.ALL_ITEMS,
        status=MerchandisingStatus.ACTIVE,
        starts_at=NOW - timedelta(days=1),
        ends_at=NOW + timedelta(days=1),
        combo_price=Decimal("599.00"),
        activation_confirmed=True,
    )
    draft_offer = Offer(
        outlet_id=outlet.id,
        name="Draft Offer",
        offer_type=OfferType.FLAT,
        status=MerchandisingStatus.DRAFT,
        starts_at=NOW - timedelta(days=1),
        ends_at=NOW + timedelta(days=1),
        discount_value=Decimal("10.00"),
    )
    paused_offer = Offer(
        outlet_id=outlet.id,
        name="Paused Offer",
        offer_type=OfferType.FLAT,
        status=MerchandisingStatus.PAUSED,
        starts_at=NOW - timedelta(days=1),
        ends_at=NOW + timedelta(days=1),
        discount_value=Decimal("10.00"),
    )
    expired_offer = Offer(
        outlet_id=outlet.id,
        name="Expired Offer",
        offer_type=OfferType.FLAT,
        status=MerchandisingStatus.ACTIVE,
        starts_at=NOW - timedelta(days=2),
        ends_at=NOW - timedelta(days=1),
        discount_value=Decimal("10.00"),
    )
    session.add_all(
        [
            special,
            expired_special,
            variant_special,
            featured,
            offer,
            combo,
            draft_offer,
            paused_offer,
            expired_offer,
        ]
    )
    await session.flush()
    session.add_all(
        [
            OfferCategoryScope(offer_id=offer.id, category_id=starters.id),
            OfferComboItem(
                offer_id=combo.id,
                dish_id=pizza.id,
                variant_id=large.id,
                required_quantity=1,
            ),
            OfferComboItem(offer_id=combo.id, dish_id=coffee.id, required_quantity=1),
        ]
    )
    for index in range(bulk_count):
        dish = Dish(
            menu_id=menu.id,
            category_id=mains.id,
            name=f"Bulk Dish {index:03d}",
            base_price=Decimal("100.00"),
            review_status=ReviewStatus.CONFIRMED,
            display_order=10 + index,
        )
        session.add(dish)
    await session.commit()
    return locals()


@pytest.mark.asyncio
async def test_customer_menu_read_model_public_contract(session: AsyncSession) -> None:
    data = await _urban_tadka(session)
    service = CustomerMenuService(session, now=lambda: NOW)
    menu = await service.get_menu(data["outlet"].id)

    assert menu.outlet.currency_code == "INR"
    assert menu.menu.prices_include_tax is True
    assert menu.food_policy.information_confirmed is True
    assert menu.food_policy.platform_verified is False
    assert menu.food_policy.halal_policy == HalalPolicy.SELECTED_ITEMS_ONLY
    assert menu.food_policy.halal_certification_status == (
        HalalCertificationStatus.RESTAURANT_CLAIMS_CERTIFIED
    )
    all_dishes = [dish for category in menu.categories for dish in category.dishes]
    names = {dish.name for dish in all_dishes}
    assert {"Paneer Tikka", "Paneer Biryani", "Farmhouse Pizza", "Cold Coffee"} <= names
    assert "Hidden Dish" not in names
    assert "Pending Roll" not in names
    assert "Inactive Kebab" not in names
    assert "Draft Dish" not in names
    assert [category.name for category in menu.categories] == [
        "Starters",
        "Main Course",
        "Pizza",
        "Beverages",
    ]

    tikka = next(dish for dish in all_dishes if dish.name == "Paneer Tikka")
    biryani = next(dish for dish in all_dishes if dish.name == "Paneer Biryani")
    pizza = next(dish for dish in all_dishes if dish.name == "Farmhouse Pizza")
    coffee = next(dish for dish in all_dishes if dish.name == "Cold Coffee")

    assert tikka.pricing.catalog_price == Decimal("280.00")
    assert tikka.pricing.effective_price == Decimal("280.00")
    assert tikka.is_featured is True
    assert tikka.featured_display_order == 2
    assert tikka.is_todays_special is False
    assert tikka.available is False
    assert tikka.availability.status == "sold_out"
    assert tikka.availability.message == "Currently unavailable"
    assert "Chef Rahul" not in tikka.model_dump_json()
    assert tikka.badges == [BadgeCode.CHEF_RECOMMENDED, BadgeCode.SIGNATURE]
    assert tikka.dietary_classification == DietaryClassification.VEGETARIAN
    assert tikka.vegan_status == AvailabilityStatus.UNKNOWN
    assert tikka.jain_status == AvailabilityStatus.AVAILABLE
    assert tikka.halal_status == HalalOverride.UNKNOWN
    assert tikka.spice_level == SpiceLevel.MEDIUM
    assert tikka.allergen_information_status == AllergenStatus.UNKNOWN
    assert tikka.ingredient_description == (
        "Paneer cubes marinated with yogurt, capsicum and spices."
    )
    assert [ingredient.name for ingredient in tikka.ingredients] == ["Capsicum", "Paneer"]
    assert tikka.primary_image is not None
    assert tikka.primary_image.storage_key == "dish/paneer-tikka.jpg"
    assert len(tikka.images) == 1
    assert [group.name for group in tikka.modifiers] == ["Add Extras"]
    assert [option.price_delta for option in tikka.modifiers[0].options] == [
        Decimal("40.00"),
        Decimal("20.00"),
    ]

    assert biryani.pricing.catalog_price == Decimal("320.00")
    assert biryani.pricing.effective_price == Decimal("279.00")
    assert biryani.pricing.has_special_price is True
    assert biryani.is_todays_special is True
    assert biryani.available is False

    assert pizza.pricing.catalog_price is None
    assert pizza.pricing.starting_price == Decimal("249.00")
    assert [variant.name for variant in pizza.variants] == ["Small", "Medium", "Large"]
    large = next(variant for variant in pizza.variants if variant.name == "Large")
    small = next(variant for variant in pizza.variants if variant.name == "Small")
    assert large.catalog_price == Decimal("449.00")
    assert large.effective_price == Decimal("399.00")
    assert large.is_todays_special is True
    assert large.primary_image is not None
    assert small.effective_price == Decimal("249.00")
    assert small.primary_image is None

    assert coffee.available is True
    assert coffee.dietary_classification == DietaryClassification.UNKNOWN
    assert coffee.spice_level == SpiceLevel.UNKNOWN

    assert [dish.name for dish in menu.featured_dishes] == ["Paneer Tikka"]
    assert {offer.name for offer in menu.offers} == {"Diwali 20% Off", "Pizza Combo"}
    diwali = next(offer for offer in menu.offers if offer.name == "Diwali 20% Off")
    combo = next(offer for offer in menu.offers if offer.name == "Pizza Combo")
    assert diwali.stacking_applied is False
    assert diwali.auto_best_offer_selected is False
    assert [category.name for category in diwali.category_scope] == ["Starters"]
    assert combo.combo_price == Decimal("599.00")
    assert [(item.dish_name, item.variant_name) for item in combo.combo_items] == [
        ("Cold Coffee", None),
        ("Farmhouse Pizza", "Large"),
    ]

    assert await session.scalar(select(func.count()).select_from(Dish)) == 8


@pytest.mark.asyncio
async def test_customer_menu_filters_search_and_outlet_safety(session: AsyncSession) -> None:
    data = await _urban_tadka(session)
    service = CustomerMenuService(session, now=lambda: NOW)

    vegetarian = await service.get_menu(
        data["outlet"].id,
        filters=CustomerMenuFilters(dietary_classification=DietaryClassification.VEGETARIAN),
    )
    assert {dish.name for category in vegetarian.categories for dish in category.dishes} == {
        "Paneer Tikka",
        "Paneer Biryani",
    }
    vegan = await service.get_menu(
        data["outlet"].id,
        filters=CustomerMenuFilters(vegan_status=AvailabilityStatus.AVAILABLE),
    )
    assert [dish for category in vegan.categories for dish in category.dishes] == []
    mild = await service.get_menu(
        data["outlet"].id,
        filters=CustomerMenuFilters(spice_level=SpiceLevel.MILD),
    )
    assert [dish for category in mild.categories for dish in category.dishes] == []
    sold_out = await service.get_menu(
        data["outlet"].id,
        filters=CustomerMenuFilters(available=False),
    )
    assert {dish.name for category in sold_out.categories for dish in category.dishes} == {
        "Paneer Tikka",
        "Paneer Biryani",
    }
    combined = await service.get_menu(
        data["outlet"].id,
        filters=CustomerMenuFilters(
            dietary_classification=DietaryClassification.VEGETARIAN,
            available=False,
            spice_level=SpiceLevel.MEDIUM,
        ),
    )
    assert {dish.name for category in combined.categories for dish in category.dishes} == {
        "Paneer Tikka",
        "Paneer Biryani",
    }

    assert [dish.name for dish in await service.search(data["outlet"].id, q="paneer")] == [
        "Paneer Biryani",
        "Paneer Tikka",
    ]
    assert [dish.name for dish in await service.search(data["outlet"].id, q="TANDOOR")] == [
        "Paneer Tikka"
    ]
    assert [dish.name for dish in await service.search(data["outlet"].id, q="capsicum")] == [
        "Paneer Tikka"
    ]
    assert [dish.name for dish in await service.search(data["outlet"].id, q="italian")] == [
        "Farmhouse Pizza"
    ]
    filtered_without_text = await service.search(
        data["outlet"].id,
        filters=CustomerMenuFilters(
            dietary_classification=DietaryClassification.VEGETARIAN,
            price_min=Decimal("200.00"),
            price_max=Decimal("280.00"),
        ),
    )
    assert [(dish.name, dish.pricing.effective_price) for dish in filtered_without_text] == [
        ("Paneer Biryani", Decimal("279.00")),
        ("Paneer Tikka", Decimal("280.00")),
    ]

    dish = await service.get_dish(data["outlet"].id, data["tikka"].id)
    assert dish.name == "Paneer Tikka"
    with pytest.raises(CustomerMenuNotFound) as wrong_outlet:
        await service.get_dish(data["inactive_outlet"].id, data["tikka"].id)
    assert wrong_outlet.value.code == "customer_menu_not_available"
    with pytest.raises(CustomerMenuNotFound) as missing:
        await service.get_dish(data["outlet"].id, uuid4())
    assert missing.value.code == "customer_menu_dish_not_found"
    with pytest.raises(CustomerMenuNotFound):
        await service.get_menu(data["closed_brand_outlet"].id)


@pytest.mark.asyncio
async def test_customer_menu_reflects_availability_restore_and_no_mutation(
    session: AsyncSession,
) -> None:
    data = await _urban_tadka(session)
    service = CustomerMenuService(session, now=lambda: NOW)
    before = await session.scalar(select(func.count()).select_from(IngredientAvailabilityOverride))
    menu = await service.get_menu(data["outlet"].id)
    after = await session.scalar(select(func.count()).select_from(IngredientAvailabilityOverride))
    assert before == after
    biryani = next(
        dish
        for category in menu.categories
        for dish in category.dishes
        if dish.name == "Paneer Biryani"
    )
    assert biryani.available is False
    overrides = (
        await session.execute(
            select(IngredientAvailabilityOverride).where(
                IngredientAvailabilityOverride.ingredient_id == data["paneer"].id
            )
        )
    ).scalars()
    for override in overrides:
        override.revoked_at = NOW
    await session.commit()
    restored = await service.get_menu(data["outlet"].id)
    biryani_restored = next(
        dish
        for category in restored.categories
        for dish in category.dishes
        if dish.name == "Paneer Biryani"
    )
    assert biryani_restored.available is True


@pytest.mark.asyncio
async def test_customer_menu_bulk_read_avoids_obvious_n_plus_one() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    statements = 0

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def count_queries(*_args: object) -> None:
        nonlocal statements
        statements += 1

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            data = await _urban_tadka(session, bulk_count=60)
            statements = 0
            menu = await CustomerMenuService(session, now=lambda: NOW).get_menu(data["outlet"].id)
            dish_count = sum(len(category.dishes) for category in menu.categories)
            assert dish_count == 64
            assert statements < 35
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()
