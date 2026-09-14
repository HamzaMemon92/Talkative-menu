from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ainza_restaurant.ai.db_models import AIConversation
from ainza_restaurant.availability.models import (
    AvailabilityProposal,
    AvailabilityProposalAffectedDish,
    DishAvailabilityOverride,
)
from ainza_restaurant.availability.schemas import AvailabilityProposalCreate
from ainza_restaurant.availability.service import AvailabilityService
from ainza_restaurant.billing.models import DiningInvoice
from ainza_restaurant.core.config import get_settings
from ainza_restaurant.customer_menu.service import CustomerMenuService
from ainza_restaurant.dining.models import DiningSession, RestaurantTable
from ainza_restaurant.dining.schemas import TableCreate
from ainza_restaurant.dining.service import DiningService
from ainza_restaurant.domain.enums import (
    AllergenStatus,
    AvailabilityAction,
    AvailabilityDurationMode,
    AvailabilityReasonCode,
    AvailabilityStatus,
    AvailabilityTargetType,
    DietaryClassification,
    ItemType,
    MenuStatus,
    MerchandisingStatus,
    OfferScopeType,
    OfferType,
    RestaurantType,
    ReviewStatus,
    SpiceLevel,
)
from ainza_restaurant.menu.models import (
    Category,
    Dish,
    DishIngredient,
    DishVariant,
    Ingredient,
    Menu,
    ModifierGroup,
    ModifierOption,
)
from ainza_restaurant.merchandising.models import FeaturedDish, Offer, TodaysSpecial
from ainza_restaurant.ordering.models import DiningOrder
from ainza_restaurant.restaurants.models import (
    OutletTaxProfile,
    Restaurant,
    RestaurantOutlet,
    WeeklyOperatingInterval,
)

E2E_DATABASE = "ainza_restaurant_e2e"
FIXTURE_SLUG = "urban-tadka-e2e"
NOW = datetime.now(UTC)


def _engine():
    url = make_url(get_settings().database_url).set(database=E2E_DATABASE)
    return create_async_engine(url, pool_pre_ping=True)


async def _require_e2e(session: AsyncSession) -> None:
    name = await session.scalar(text("SELECT current_database()"))
    if name != E2E_DATABASE:
        raise RuntimeError("refusing to seed a non-E2E database")


async def seed() -> None:
    engine = _engine()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            await _require_e2e(session)
            existing = await session.scalar(
                select(Restaurant).where(Restaurant.slug == FIXTURE_SLUG)
            )
            if existing is not None:
                outlet_ids = list(
                    (
                        await session.execute(
                            select(RestaurantOutlet.id).where(
                                RestaurantOutlet.restaurant_id == existing.id
                            )
                        )
                    ).scalars()
                )
                dish_ids = list(
                    (
                        await session.execute(
                            select(Dish.id).join(Menu).where(Menu.outlet_id.in_(outlet_ids))
                        )
                    ).scalars()
                )
                proposal_ids = list(
                    (
                        await session.execute(
                            select(AvailabilityProposal.id).where(
                                AvailabilityProposal.outlet_id.in_(outlet_ids)
                            )
                        )
                    ).scalars()
                )
                table_ids = list(
                    (
                        await session.execute(
                            select(RestaurantTable.id).where(
                                RestaurantTable.outlet_id.in_(outlet_ids)
                            )
                        )
                    ).scalars()
                )
                session_ids = list(
                    (
                        await session.execute(
                            select(DiningSession.id).where(DiningSession.table_id.in_(table_ids))
                        )
                    ).scalars()
                )
                if session_ids:
                    await session.execute(
                        delete(AIConversation).where(
                            AIConversation.dining_session_id.in_(session_ids)
                        )
                    )
                    await session.execute(
                        delete(DiningInvoice).where(
                            DiningInvoice.dining_session_id.in_(session_ids)
                        )
                    )
                    await session.execute(
                        delete(DiningOrder).where(DiningOrder.dining_session_id.in_(session_ids))
                    )
                    await session.execute(
                        delete(DiningSession).where(DiningSession.id.in_(session_ids))
                    )
                if dish_ids:
                    await session.execute(
                        delete(DishAvailabilityOverride).where(
                            DishAvailabilityOverride.dish_id.in_(dish_ids)
                        )
                    )
                if proposal_ids:
                    await session.execute(
                        delete(AvailabilityProposalAffectedDish).where(
                            AvailabilityProposalAffectedDish.proposal_id.in_(proposal_ids)
                        )
                    )
                    await session.execute(
                        delete(AvailabilityProposal).where(
                            AvailabilityProposal.id.in_(proposal_ids)
                        )
                    )
                await session.execute(delete(Restaurant).where(Restaurant.id == existing.id))
                await session.commit()

            restaurant = Restaurant(name="Urban Tadka", slug=FIXTURE_SLUG)
            session.add(restaurant)
            await session.flush()
            outlet = RestaurantOutlet(
                restaurant_id=restaurant.id,
                name="Urban Tadka - Vesu",
                address_line1="Vesu",
                city="Surat",
                state="Gujarat",
                postal_code="395007",
                timezone="Asia/Kolkata",
                currency_code="INR",
                is_primary=True,
            )
            session.add(outlet)
            await session.flush()
            session.add(
                OutletTaxProfile(
                    outlet_id=outlet.id,
                    legal_business_name="Urban Tadka E2E Fixture",
                    restaurant_type=RestaurantType.STANDALONE,
                    configured_tax_rate_percent=Decimal("5.00"),
                    prices_include_tax=False,
                    tax_configuration_confirmed=True,
                    tax_rates_confirmed=True,
                    no_auto_tax_rates_confirmed=True,
                )
            )
            for weekday in range(7):
                session.add_all(
                    [
                        WeeklyOperatingInterval(
                            outlet_id=outlet.id,
                            weekday=weekday,
                            opens_at=time(11, 30),
                            closes_at=time(15, 30),
                        ),
                        WeeklyOperatingInterval(
                            outlet_id=outlet.id,
                            weekday=weekday,
                            opens_at=time(18, 30),
                            closes_at=time(23),
                        ),
                    ]
                )
            menu = Menu(
                restaurant_id=restaurant.id,
                outlet_id=outlet.id,
                name="Urban Tadka E2E",
                status=MenuStatus.PUBLISHED,
                published_at=NOW,
            )
            session.add(menu)
            await session.flush()
            categories = {}
            for order, name in enumerate(
                ("STARTERS", "MAINS", "RICE", "BREADS", "DRINKS", "DESSERTS")
            ):
                category = Category(
                    menu_id=menu.id, name=name.title(), slug=name.casefold(), display_order=order
                )
                session.add(category)
                categories[name] = category
            await session.flush()
            dishes = {}
            fixtures = [
                (
                    "STARTERS",
                    "Paneer Tikka",
                    "280.00",
                    DietaryClassification.VEGETARIAN,
                    SpiceLevel.MILD,
                    AvailabilityStatus.UNKNOWN,
                ),
                (
                    "STARTERS",
                    "Hara Bhara Kebab",
                    "240.00",
                    DietaryClassification.VEGETARIAN,
                    SpiceLevel.HOT,
                    AvailabilityStatus.AVAILABLE,
                ),
                (
                    "STARTERS",
                    "Crispy Corn",
                    "220.00",
                    DietaryClassification.VEGETARIAN,
                    SpiceLevel.UNKNOWN,
                    AvailabilityStatus.UNKNOWN,
                ),
                (
                    "MAINS",
                    "Paneer Butter Masala",
                    "320.00",
                    DietaryClassification.VEGETARIAN,
                    SpiceLevel.MILD,
                    AvailabilityStatus.UNKNOWN,
                ),
                (
                    "MAINS",
                    "Dal Makhani",
                    "290.00",
                    DietaryClassification.VEGETARIAN,
                    SpiceLevel.MILD,
                    AvailabilityStatus.UNKNOWN,
                ),
                (
                    "MAINS",
                    "Veg Kolhapuri",
                    "300.00",
                    DietaryClassification.VEGETARIAN,
                    SpiceLevel.HOT,
                    AvailabilityStatus.UNKNOWN,
                ),
                (
                    "MAINS",
                    "Butter Chicken",
                    "380.00",
                    DietaryClassification.NON_VEGETARIAN,
                    SpiceLevel.UNKNOWN,
                    AvailabilityStatus.UNKNOWN,
                ),
                (
                    "RICE",
                    "Veg Biryani",
                    "260.00",
                    DietaryClassification.VEGETARIAN,
                    SpiceLevel.MILD,
                    AvailabilityStatus.UNKNOWN,
                ),
                (
                    "RICE",
                    "Jeera Rice",
                    "180.00",
                    DietaryClassification.VEGETARIAN,
                    SpiceLevel.UNKNOWN,
                    AvailabilityStatus.UNKNOWN,
                ),
                (
                    "BREADS",
                    "Butter Naan",
                    "60.00",
                    DietaryClassification.VEGETARIAN,
                    SpiceLevel.UNKNOWN,
                    AvailabilityStatus.UNKNOWN,
                ),
                (
                    "BREADS",
                    "Tandoori Roti",
                    "45.00",
                    DietaryClassification.VEGETARIAN,
                    SpiceLevel.UNKNOWN,
                    AvailabilityStatus.UNKNOWN,
                ),
                (
                    "DRINKS",
                    "Masala Chaas",
                    "90.00",
                    DietaryClassification.VEGETARIAN,
                    SpiceLevel.MILD,
                    AvailabilityStatus.UNKNOWN,
                ),
                (
                    "DRINKS",
                    "Cold Coffee",
                    "160.00",
                    DietaryClassification.VEGETARIAN,
                    SpiceLevel.UNKNOWN,
                    AvailabilityStatus.UNKNOWN,
                ),
                (
                    "DRINKS",
                    "Fresh Lime Soda",
                    "110.00",
                    DietaryClassification.VEGETARIAN,
                    SpiceLevel.MILD,
                    AvailabilityStatus.UNKNOWN,
                ),
                (
                    "DESSERTS",
                    "Gulab Jamun",
                    "120.00",
                    DietaryClassification.VEGETARIAN,
                    SpiceLevel.UNKNOWN,
                    AvailabilityStatus.UNKNOWN,
                ),
            ]
            for order, (category, name, price, dietary, spice, jain) in enumerate(fixtures):
                dish = Dish(
                    menu_id=menu.id,
                    category_id=categories[category].id,
                    name=name,
                    base_price=Decimal(price),
                    item_type=ItemType.FOOD,
                    dietary_classification=dietary,
                    spice_level=spice,
                    jain_status=jain,
                    vegan_status=AvailabilityStatus.UNKNOWN,
                    allergen_information_status=AllergenStatus.UNKNOWN,
                    review_status=ReviewStatus.CONFIRMED,
                    display_order=order,
                )
                session.add(dish)
                dishes[name] = dish
            await session.flush()
            ingredient = Ingredient(
                restaurant_id=restaurant.id,
                outlet_id=outlet.id,
                name="Fixture paneer",
                normalized_name="fixture-paneer",
            )
            session.add(ingredient)
            await session.flush()
            session.add(
                DishIngredient(
                    dish_id=dishes["Paneer Tikka"].id,
                    ingredient_id=ingredient.id,
                    is_required_for_availability=True,
                )
            )
            biryani = dishes["Veg Biryani"]
            session.add_all(
                [
                    DishVariant(dish_id=biryani.id, name="Regular", price=Decimal("260.00")),
                    DishVariant(dish_id=biryani.id, name="Large", price=Decimal("340.00")),
                ]
            )
            group = ModifierGroup(
                dish_id=dishes["Paneer Tikka"].id, name="Add-ons", max_selections=2
            )
            session.add(group)
            await session.flush()
            session.add_all(
                [
                    ModifierOption(
                        group_id=group.id, name="Extra Mint Chutney", price_delta=Decimal("20.00")
                    ),
                    ModifierOption(
                        group_id=group.id, name="Extra Paneer", price_delta=Decimal("50.00")
                    ),
                ]
            )
            session.add_all(
                [
                    TodaysSpecial(
                        outlet_id=outlet.id,
                        dish_id=dishes["Paneer Butter Masala"].id,
                        special_price=Decimal("299.00"),
                        starts_at=NOW - timedelta(days=1),
                        ends_at=NOW + timedelta(days=1),
                        status=MerchandisingStatus.ACTIVE,
                        activation_confirmed=True,
                        activated_at=NOW,
                    ),
                    FeaturedDish(
                        outlet_id=outlet.id,
                        dish_id=dishes["Paneer Tikka"].id,
                        starts_at=NOW - timedelta(days=1),
                        status=MerchandisingStatus.ACTIVE,
                        activation_confirmed=True,
                        activated_at=NOW,
                    ),
                    Offer(
                        outlet_id=outlet.id,
                        name="E2E Vegetarian 10%",
                        offer_type=OfferType.PERCENTAGE,
                        scope_type=OfferScopeType.ALL_ITEMS,
                        starts_at=NOW - timedelta(days=1),
                        ends_at=NOW + timedelta(days=1),
                        discount_value=Decimal("10.00"),
                        status=MerchandisingStatus.ACTIVE,
                        activation_confirmed=True,
                        activated_at=NOW,
                    ),
                ]
            )
            await session.commit()
            availability = AvailabilityService(session)
            proposal = await availability.create_proposal(
                outlet.id,
                AvailabilityProposalCreate(
                    target_type=AvailabilityTargetType.DISH,
                    target_id=dishes["Crispy Corn"].id,
                    action=AvailabilityAction.MARK_UNAVAILABLE,
                    duration_mode=AvailabilityDurationMode.INDEFINITE,
                    reason_code=AvailabilityReasonCode.OUT_OF_STOCK,
                ),
            )
            await availability.confirm_proposal(proposal.id, confirm=True)
            dining = DiningService(session)
            for order, label in enumerate(("T1", "T2", "T3")):
                await dining.create_table(outlet.id, TableCreate(label=label, display_order=order))
            customer_menu = await CustomerMenuService(session).get_menu(outlet.id)
            assert len(customer_menu.categories) == 6
            assert any(
                dish.name == "Crispy Corn" and not dish.available
                for category in customer_menu.categories
                for dish in category.dishes
            )
            print("[PASS] E2E database safety check")
            print("[PASS] Urban Tadka published fixture: 6 categories, 15 dishes, T1/T2/T3")
            print("[PASS] Availability proposal confirmed: Crispy Corn unavailable")
            print("[PASS] Customer menu composition")
            print("TEST FIXTURE TAX RATE - NOT LEGAL OR TAX ADVICE.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
