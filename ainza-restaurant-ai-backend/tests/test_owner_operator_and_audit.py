from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.ai.context import AIActorType, AIToolContext, ToolExecutionAuthorization
from ainza_restaurant.ai.tools.executor import AIToolExecutor
from ainza_restaurant.ai.tools.registry import build_default_registry
from ainza_restaurant.audit.models import AuditLog
from ainza_restaurant.availability.schemas import AvailabilityProposalCreate
from ainza_restaurant.availability.service import AvailabilityService
from ainza_restaurant.customer_menu.service import CustomerMenuService
from ainza_restaurant.db.base import Base
from ainza_restaurant.domain.enums import (
    AuditActionType,
    AvailabilityAction,
    AvailabilityDurationMode,
    AvailabilityStatus,
    AvailabilityTargetType,
    DietaryClassification,
    ItemType,
    OnboardingStatus,
    RestaurantType,
    ReviewStatus,
)
from ainza_restaurant.menu.schemas import CategoryCreate, DishCreate, MenuCreate, PublishRequest
from ainza_restaurant.menu.service import MenuCatalogService
from ainza_restaurant.restaurants.models import OutletTaxProfile, Restaurant, RestaurantOutlet

NOW = datetime(2026, 9, 10, 14, 30, tzinfo=UTC)


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


async def setup_restaurant_with_menu(session: AsyncSession) -> dict[str, object]:
    restaurant = Restaurant(
        name="Urban Tadka",
        slug=f"urban-tadka-{uuid4().hex}",
        onboarding_status=OnboardingStatus.READY_FOR_MENU,
    )
    session.add(restaurant)
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
    other_outlet = RestaurantOutlet(
        restaurant_id=restaurant.id,
        name="Urban Tadka - Adajan",
        address_line1="1 Adajan Road",
        city="Surat",
        state="Gujarat",
        postal_code="395009",
        timezone="Asia/Kolkata",
        currency_code="INR",
    )
    session.add(outlet)
    session.add(other_outlet)
    await session.flush()

    # Tax profile
    session.add(
        OutletTaxProfile(
            outlet_id=outlet.id,
            restaurant_type=RestaurantType.STANDALONE,
            gst_registered=True,
        )
    )
    session.add(
        OutletTaxProfile(
            outlet_id=other_outlet.id,
            restaurant_type=RestaurantType.STANDALONE,
            gst_registered=True,
        )
    )

    menu_service = MenuCatalogService(session)
    menu = await menu_service.create_menu(
        restaurant.id,
        MenuCreate(name="Main Menu", outlet_id=outlet.id, currency_code="INR"),
    )
    starters = await menu_service.create_category(menu.id, CategoryCreate(name="Starters"))
    mains = await menu_service.create_category(menu.id, CategoryCreate(name="Main Course"))

    dish_tikka = await menu_service.create_dish(
        menu.id,
        DishCreate(
            category_id=starters.id,
            name="Paneer Tikka",
            base_price=Decimal("280.00"),
            item_type=ItemType.FOOD,
            dietary_classification=DietaryClassification.VEGETARIAN,
            review_status=ReviewStatus.CONFIRMED,
        ),
    )
    dish_masala = await menu_service.create_dish(
        menu.id,
        DishCreate(
            category_id=mains.id,
            name="Paneer Butter Masala",
            base_price=Decimal("320.00"),
            item_type=ItemType.FOOD,
            dietary_classification=DietaryClassification.VEGETARIAN,
            review_status=ReviewStatus.CONFIRMED,
        ),
    )
    dish_biryani = await menu_service.create_dish(
        menu.id,
        DishCreate(
            category_id=mains.id,
            name="Dum Biryani",
            base_price=Decimal("350.00"),
            item_type=ItemType.FOOD,
            dietary_classification=DietaryClassification.NON_VEGETARIAN,
            review_status=ReviewStatus.CONFIRMED,
        ),
    )

    restaurant_id = restaurant.id
    outlet_id = outlet.id
    other_outlet_id = other_outlet.id
    menu_id = menu.id
    dish_tikka_id = dish_tikka.id
    dish_masala_id = dish_masala.id
    dish_biryani_id = dish_biryani.id

    # Publish menu
    await menu_service.publish(menu.id, PublishRequest(confirm=True))
    await session.commit()

    return {
        "restaurant_id": restaurant_id,
        "outlet_id": outlet_id,
        "other_outlet_id": other_outlet_id,
        "menu_id": menu_id,
        "dish_tikka_id": dish_tikka_id,
        "dish_masala_id": dish_masala_id,
        "dish_biryani_id": dish_biryani_id,
    }


@pytest.mark.asyncio
async def test_35_customer_cannot_access_owner_intent_or_tool(session: AsyncSession):
    """Customer tokens and contexts must never be allowed to execute owner tools."""
    data = await setup_restaurant_with_menu(session)

    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    customer_context = AIToolContext(
        actor_type=AIActorType.CUSTOMER,
        outlet_id=data["outlet_id"],
        restaurant_id=data["restaurant_id"],
    )

    # Attempt to preview price change as customer
    res = await executor.execute(
        session,
        "owner_preview_price_change",
        {"dish_name": "Paneer Tikka", "new_price": "290.00"},
        customer_context,
    )
    assert not res.ok
    assert res.error.code == "ai_tool_forbidden"


@pytest.mark.asyncio
async def test_36_owner_can_mark_dish_unavailable(session: AsyncSession):
    """Owner can create an availability proposal to make a dish unavailable and confirm it."""
    data = await setup_restaurant_with_menu(session)
    outlet_id = data["outlet_id"]
    dish_biryani_id = data["dish_biryani_id"]

    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    owner_context = AIToolContext(
        actor_type=AIActorType.OWNER,
        outlet_id=outlet_id,
        restaurant_id=data["restaurant_id"],
    )

    # 1. Create proposal
    prop_res = await executor.execute(
        session,
        "owner_create_availability_proposal",
        {
            "target_type": AvailabilityTargetType.DISH.value,
            "target_id": str(dish_biryani_id),
            "action": AvailabilityAction.MARK_UNAVAILABLE.value,
            "duration_mode": AvailabilityDurationMode.INDEFINITE.value,
            "reason_note": "Sold out tonight",
        },
        owner_context,
    )
    assert prop_res.ok
    proposal_id = prop_res.data["id"]

    # 2. Confirm proposal
    confirm_res = await executor.execute(
        session,
        "owner_confirm_availability_proposal",
        {"proposal_id": proposal_id},
        owner_context,
        authorization=ToolExecutionAuthorization(explicit_user_confirmation=True),
    )
    assert confirm_res.ok

    # 3. Check customer menu reflects unavailability
    customer_menu = await CustomerMenuService(session).get_menu(outlet_id)
    mains = [c for c in customer_menu.categories if c.name == "Main Course"][0]
    biryani_item = [d for d in mains.dishes if d.name == "Dum Biryani"][0]
    assert not biryani_item.availability.available
    assert biryani_item.availability.status in {"sold_out", "not_available"}


@pytest.mark.asyncio
async def test_37_owner_can_restore_availability(session: AsyncSession):
    """Owner can restore availability of a previously unavailable dish."""
    data = await setup_restaurant_with_menu(session)
    outlet_id = data["outlet_id"]
    dish_biryani_id = data["dish_biryani_id"]

    avail_service = AvailabilityService(session)
    # First make unavailable
    p1 = await avail_service.create_proposal(
        outlet_id,
        AvailabilityProposalCreate(
            target_type=AvailabilityTargetType.DISH,
            target_id=dish_biryani_id,
            action=AvailabilityAction.MARK_UNAVAILABLE,
            duration_mode=AvailabilityDurationMode.INDEFINITE,
        ),
    )
    await avail_service.confirm_proposal(p1.id, confirm=True)

    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    owner_context = AIToolContext(
        actor_type=AIActorType.OWNER,
        outlet_id=outlet_id,
        restaurant_id=data["restaurant_id"],
    )

    # Restore via proposal
    prop_res = await executor.execute(
        session,
        "owner_create_availability_proposal",
        {
            "target_type": AvailabilityTargetType.DISH.value,
            "target_id": str(dish_biryani_id),
            "action": AvailabilityAction.RESTORE.value,
            "reason_note": "Restocked",
        },
        owner_context,
    )
    assert prop_res.ok

    confirm_res = await executor.execute(
        session,
        "owner_confirm_availability_proposal",
        {"proposal_id": prop_res.data["id"]},
        owner_context,
        authorization=ToolExecutionAuthorization(explicit_user_confirmation=True),
    )
    assert confirm_res.ok

    customer_menu = await CustomerMenuService(session).get_menu(outlet_id)
    biryani_item = [
        d for cat in customer_menu.categories for d in cat.dishes if d.name == "Dum Biryani"
    ][0]
    assert biryani_item.availability.status == AvailabilityStatus.AVAILABLE


@pytest.mark.asyncio
async def test_38_owner_price_change_preview(session: AsyncSession):
    """Owner preview returns typed old vs new price and requires confirmation."""
    data = await setup_restaurant_with_menu(session)

    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    owner_context = AIToolContext(
        actor_type=AIActorType.OWNER,
        outlet_id=data["outlet_id"],
        restaurant_id=data["restaurant_id"],
    )

    preview_res = await executor.execute(
        session,
        "owner_preview_price_change",
        {"dish_name": "Paneer Tikka", "new_price": "290.00"},
        owner_context,
    )
    assert preview_res.ok
    assert preview_res.data["dish_name"] == "Paneer Tikka"
    assert preview_res.data["old_price"] == "280.00"
    assert preview_res.data["new_price"] == "290.00"
    assert preview_res.data["confirmation_required"] is True


@pytest.mark.asyncio
async def test_39_confirmation_required(session: AsyncSession):
    """Consequential mutation without explicit confirmation must fail safely."""
    data = await setup_restaurant_with_menu(session)

    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    owner_context = AIToolContext(
        actor_type=AIActorType.OWNER,
        outlet_id=data["outlet_id"],
        restaurant_id=data["restaurant_id"],
    )

    # Calling owner_apply_price_change without authorization.explicit_user_confirmation
    res = await executor.execute(
        session,
        "owner_apply_price_change",
        {"dish_name": "Paneer Tikka", "new_price": "290.00"},
        owner_context,
        authorization=ToolExecutionAuthorization(explicit_user_confirmation=False),
    )
    assert not res.ok
    assert res.error.code == "ai_confirmation_required"


@pytest.mark.asyncio
async def test_40_owner_can_add_dish_through_deterministic_service(session: AsyncSession):
    """Owner can add a dish to the draft menu revision."""
    data = await setup_restaurant_with_menu(session)

    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    owner_context = AIToolContext(
        actor_type=AIActorType.OWNER,
        outlet_id=data["outlet_id"],
        restaurant_id=data["restaurant_id"],
    )

    res = await executor.execute(
        session,
        "owner_add_dish",
        {
            "category_name": "Breads",
            "dish_name": "Cheese Garlic Naan",
            "price": "150.00",
            "description": "Stuffed with melted cheese and topped with garlic",
        },
        owner_context,
    )
    assert res.ok
    assert res.data["dish_name"] == "Cheese Garlic Naan"
    assert res.data["price"] == "150.00"
    assert res.data["status"] == "created_in_draft"


@pytest.mark.asyncio
async def test_41_ambiguous_dish_asks_clarification(session: AsyncSession):
    """When a dish query matches multiple dishes ambiguously,
    return candidate list for clarification."""

    data = await setup_restaurant_with_menu(session)

    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    owner_context = AIToolContext(
        actor_type=AIActorType.OWNER,
        outlet_id=data["outlet_id"],
        restaurant_id=data["restaurant_id"],
    )

    # Searching for 'Paneer' matches both 'Paneer Tikka' and 'Paneer Butter Masala'
    res = await executor.execute(
        session,
        "owner_preview_price_change",
        {"dish_name": "Paneer", "new_price": "300.00"},
        owner_context,
    )
    assert res.ok
    assert res.data["error"] == "ambiguous_dish"
    assert "Paneer Tikka" in res.data["candidates"]
    assert "Paneer Butter Masala" in res.data["candidates"]


@pytest.mark.asyncio
async def test_42_cross_outlet_mutation_blocked(session: AsyncSession):
    """Owner of Outlet A cannot confirm or mutate an availability proposal belonging to Outlet B."""
    data = await setup_restaurant_with_menu(session)
    outlet_a_id = data["outlet_id"]
    outlet_b_id = data["other_outlet_id"]

    menu_service = MenuCatalogService(session)
    menu_b = await menu_service.create_menu(
        data["restaurant_id"],
        MenuCreate(name="B Menu", outlet_id=outlet_b_id, currency_code="INR"),
    )
    cat_b = await menu_service.create_category(menu_b.id, CategoryCreate(name="B Cat"))
    dish_b = await menu_service.create_dish(
        menu_b.id,
        DishCreate(
            category_id=cat_b.id,
            name="Dish B",
            base_price=Decimal("100.00"),
            item_type=ItemType.FOOD,
            dietary_classification=DietaryClassification.VEGETARIAN,
            review_status=ReviewStatus.CONFIRMED,
        ),
    )
    dish_b_id = dish_b.id
    await menu_service.publish(menu_b.id, PublishRequest(confirm=True))
    await session.commit()

    avail_service = AvailabilityService(session)
    proposal_b = await avail_service.create_proposal(
        outlet_b_id,
        AvailabilityProposalCreate(
            target_type=AvailabilityTargetType.DISH,
            target_id=dish_b_id,
            action=AvailabilityAction.MARK_UNAVAILABLE,
            duration_mode=AvailabilityDurationMode.INDEFINITE,
        ),
    )

    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    context_a = AIToolContext(
        actor_type=AIActorType.OWNER,
        outlet_id=outlet_a_id,
        restaurant_id=data["restaurant_id"],
    )

    res = await executor.execute(
        session,
        "owner_confirm_availability_proposal",
        {"proposal_id": str(proposal_b.id)},
        context_a,
        authorization=ToolExecutionAuthorization(explicit_user_confirmation=True),
    )
    assert not res.ok
    assert res.error.code == "ai_scope_violation"


@pytest.mark.asyncio
async def test_43_audit_record_created(session: AsyncSession):
    """Owner mutations must create durable AuditLog rows."""
    data = await setup_restaurant_with_menu(session)
    outlet_id = data["outlet_id"]

    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    owner_context = AIToolContext(
        actor_type=AIActorType.OWNER,
        outlet_id=outlet_id,
        restaurant_id=data["restaurant_id"],
    )

    # Apply price change with confirmation
    await executor.execute(
        session,
        "owner_apply_price_change",
        {"dish_name": "Paneer Tikka", "new_price": "290.00"},
        owner_context,
        authorization=ToolExecutionAuthorization(explicit_user_confirmation=True),
    )

    # Query audit logs
    stmt = select(AuditLog).where(
        AuditLog.outlet_id == outlet_id,
        AuditLog.action_type == AuditActionType.PRICE_CHANGE,
    )
    logs = (await session.scalars(stmt)).all()
    assert len(logs) >= 1
    log = logs[0]
    assert log.source == "owner_ai"
    assert log.target_type == "DISH"


@pytest.mark.asyncio
async def test_44_old_new_values_captured(session: AsyncSession):
    """Audit log must accurately capture previous_value and new_value."""
    data = await setup_restaurant_with_menu(session)
    outlet_id = data["outlet_id"]

    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    owner_context = AIToolContext(
        actor_type=AIActorType.OWNER,
        outlet_id=outlet_id,
        restaurant_id=data["restaurant_id"],
    )

    await executor.execute(
        session,
        "owner_apply_price_change",
        {"dish_name": "Paneer Tikka", "new_price": "295.00"},
        owner_context,
        authorization=ToolExecutionAuthorization(explicit_user_confirmation=True),
    )

    stmt = select(AuditLog).where(
        AuditLog.outlet_id == outlet_id,
        AuditLog.action_type == AuditActionType.PRICE_CHANGE,
    )
    log = (await session.scalars(stmt)).first()
    assert log is not None
    assert log.previous_value["price"] == "280.00"
    assert log.new_value["price"] == "295.00"
    assert log.previous_value["dish_name"] == "Paneer Tikka"


@pytest.mark.asyncio
async def test_45_bulk_dangerous_mutation_confirmation(session: AsyncSession):
    """Publishing a menu is a dangerous consequential mutation requiring confirmation."""
    data = await setup_restaurant_with_menu(session)

    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    owner_context = AIToolContext(
        actor_type=AIActorType.OWNER,
        outlet_id=data["outlet_id"],
        restaurant_id=data["restaurant_id"],
    )

    # Attempt to publish without confirmation authorization
    res = await executor.execute(
        session,
        "owner_publish_menu",
        {"confirm": True},
        owner_context,
        authorization=ToolExecutionAuthorization(explicit_user_confirmation=False),
    )
    assert not res.ok
    assert res.error.code == "ai_confirmation_required"


@pytest.mark.asyncio
async def test_46_published_menu_integrity_preserved(session: AsyncSession):
    """Modifying price in draft revision does NOT alter published menu until atomic publish."""
    data = await setup_restaurant_with_menu(session)
    outlet_id = data["outlet_id"]

    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    owner_context = AIToolContext(
        actor_type=AIActorType.OWNER,
        outlet_id=outlet_id,
        restaurant_id=data["restaurant_id"],
    )

    # Apply price change to draft
    res = await executor.execute(
        session,
        "owner_apply_price_change",
        {"dish_name": "Paneer Tikka", "new_price": "299.00"},
        owner_context,
        authorization=ToolExecutionAuthorization(explicit_user_confirmation=True),
    )
    assert res.ok

    # Customer menu still reflects published price (280.00)
    customer_menu = await CustomerMenuService(session).get_menu(outlet_id)
    paneer_tikka = [
        d for cat in customer_menu.categories for d in cat.dishes if d.name == "Paneer Tikka"
    ][0]
    assert paneer_tikka.pricing.effective_price == Decimal("280.00")

    # Now publish draft menu with confirmation
    publish_res = await executor.execute(
        session,
        "owner_publish_menu",
        {"confirm": True},
        owner_context,
        authorization=ToolExecutionAuthorization(explicit_user_confirmation=True),
    )
    assert publish_res.ok

    # Customer menu now reflects updated price (299.00)
    customer_menu_updated = await CustomerMenuService(session).get_menu(outlet_id)
    paneer_tikka_updated = [
        d
        for cat in customer_menu_updated.categories
        for d in cat.dishes
        if d.name == "Paneer Tikka"
    ][0]
    assert paneer_tikka_updated.pricing.effective_price == Decimal("299.00")
