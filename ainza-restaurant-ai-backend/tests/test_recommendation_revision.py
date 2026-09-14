from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.ai.db_models import AIConversation
from ainza_restaurant.ai.recommendation_draft import (
    RecommendationDraftService,
)
from ainza_restaurant.ai.tools.customer import (
    MealRecommendReviseInput,
    NoArgs,
    meal_recommend_accept,
    meal_recommend_revise,
)
from ainza_restaurant.customer_menu.service import CustomerMenuService
from ainza_restaurant.db.base import Base
from ainza_restaurant.domain.enums import DietaryClassification
from ainza_restaurant.ordering.service import CartService
from tests.test_ai_tools import customer_context, urban_tadka


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


@pytest.mark.asyncio
async def test_11_recommendation_draft_created(session: AsyncSession):
    data = await urban_tadka(session)
    context = customer_context(data)
    menu = await CustomerMenuService(session).get_menu(context.outlet_id)
    dishes = [dish for cat in menu.categories for dish in cat.dishes][:2]

    draft = RecommendationDraftService.create_draft(
        outlet_id=context.outlet_id,
        dining_session_id=data["dining_session"].id,
        recommended_dishes=dishes,
        currency_code="INR",
        party_size=2,
    )

    assert len(draft.items) == 2
    assert draft.currency_code == "INR"
    assert Decimal(draft.total) > 0
    assert draft.is_expired() is False


@pytest.mark.asyncio
async def test_12_replace_one_dish(session: AsyncSession):
    data = await urban_tadka(session)
    context = customer_context(data)
    menu = await CustomerMenuService(session).get_menu(context.outlet_id)
    all_dishes = [dish for cat in menu.categories for dish in cat.dishes]
    dish1 = all_dishes[0]
    dish2 = all_dishes[1]

    draft = RecommendationDraftService.create_draft(
        outlet_id=context.outlet_id,
        dining_session_id=data["dining_session"].id,
        recommended_dishes=[dish1],
        currency_code="INR",
    )

    revised, summary = RecommendationDraftService.revise(
        draft,
        menu,
        replace_target=dish1.name,
        replacement_query=dish2.name,
    )

    revised_dish_ids = {item.dish_id for item in revised.items}
    assert dish1.id not in revised_dish_ids
    assert dish2.id in revised_dish_ids
    assert "Replaced" in summary


@pytest.mark.asyncio
async def test_13_remove_one_dish(session: AsyncSession):
    data = await urban_tadka(session)
    context = customer_context(data)
    menu = await CustomerMenuService(session).get_menu(context.outlet_id)
    dishes = [dish for cat in menu.categories for dish in cat.dishes][:2]

    draft = RecommendationDraftService.create_draft(
        outlet_id=context.outlet_id,
        dining_session_id=data["dining_session"].id,
        recommended_dishes=dishes,
        currency_code="INR",
    )

    revised, summary = RecommendationDraftService.revise(
        draft,
        menu,
        remove_target=dishes[0].name,
    )

    assert len(revised.items) == 1
    assert revised.items[0].dish_id == dishes[1].id
    assert "Removed" in summary


@pytest.mark.asyncio
async def test_14_cheaper_revision(session: AsyncSession):
    data = await urban_tadka(session)
    context = customer_context(data)
    menu = await CustomerMenuService(session).get_menu(context.outlet_id)
    all_dishes = [dish for cat in menu.categories for dish in cat.dishes]
    sorted_dishes = sorted(
        all_dishes,
        key=lambda d: d.pricing.effective_price or Decimal("0"),
        reverse=True,
    )
    expensive_dish = sorted_dishes[0]

    draft = RecommendationDraftService.create_draft(
        outlet_id=context.outlet_id,
        dining_session_id=data["dining_session"].id,
        recommended_dishes=[expensive_dish],
        currency_code="INR",
    )
    initial_total = Decimal(draft.total)

    revised, summary = RecommendationDraftService.revise(
        draft,
        menu,
        make_cheaper=True,
    )

    assert Decimal(revised.total) <= initial_total
    assert "cheaper" in summary.lower() or Decimal(revised.total) <= initial_total


@pytest.mark.asyncio
async def test_15_dietary_revision(session: AsyncSession):
    data = await urban_tadka(session)
    context = customer_context(data)
    menu = await CustomerMenuService(session).get_menu(context.outlet_id)
    all_dishes = [dish for cat in menu.categories for dish in cat.dishes]

    draft = RecommendationDraftService.create_draft(
        outlet_id=context.outlet_id,
        dining_session_id=data["dining_session"].id,
        recommended_dishes=all_dishes[:2],
        currency_code="INR",
    )

    revised, summary = RecommendationDraftService.revise(
        draft,
        menu,
        dietary_filter=DietaryClassification.VEGETARIAN,
    )

    for item in revised.items:
        matching_dish = next(d for d in all_dishes if d.id == item.dish_id)
        assert matching_dish.dietary_classification == DietaryClassification.VEGETARIAN


@pytest.mark.asyncio
async def test_16_unavailable_replacement_rejected(session: AsyncSession):
    data = await urban_tadka(session)
    context = customer_context(data)
    menu = await CustomerMenuService(session).get_menu(context.outlet_id)
    all_dishes = [dish for cat in menu.categories for dish in cat.dishes]
    available_dish = next(d for d in all_dishes if d.available)

    draft = RecommendationDraftService.create_draft(
        outlet_id=context.outlet_id,
        dining_session_id=data["dining_session"].id,
        recommended_dishes=[available_dish],
        currency_code="INR",
    )

    # Attempt replacement with nonexistent/unavailable dish
    revised, summary = RecommendationDraftService.revise(
        draft,
        menu,
        replace_target=available_dish.name,
        replacement_query="NonExistentGhostDish123",
    )

    # Original dish must be preserved because replacement was unavailable
    assert len(revised.items) == 1
    assert revised.items[0].dish_id == available_dish.id
    assert "could not find" in summary.lower()


@pytest.mark.asyncio
async def test_17_no_cart_mutation_before_acceptance(session: AsyncSession):
    data = await urban_tadka(session)
    context = customer_context(data)
    menu = await CustomerMenuService(session).get_menu(context.outlet_id)
    dishes = [dish for cat in menu.categories for dish in cat.dishes][:2]

    # Create and revise draft
    draft = RecommendationDraftService.create_draft(
        outlet_id=context.outlet_id,
        dining_session_id=data["dining_session"].id,
        recommended_dishes=dishes,
        currency_code="INR",
    )
    RecommendationDraftService.revise(draft, menu, remove_target=dishes[0].name)

    # Cart must be completely empty!
    cart = await CartService(session).get_cart(context.dining_session_token)
    assert cart.item_count == 0
    assert cart.subtotal_before_offer == Decimal("0.00")


@pytest.mark.asyncio
async def test_18_accepted_recommendation_adds_correct_cart_state(session: AsyncSession):
    data = await urban_tadka(session)
    context = customer_context(data)
    menu = await CustomerMenuService(session).get_menu(context.outlet_id)
    available_dishes = [d for cat in menu.categories for d in cat.dishes if d.available][:2]

    # Create conversation
    ai_conv = AIConversation(
        dining_session_id=data["dining_session"].id,
        outlet_id=context.outlet_id,
        public_token=f"conv-{uuid4().hex}",
    )
    draft = RecommendationDraftService.create_draft(
        outlet_id=context.outlet_id,
        dining_session_id=data["dining_session"].id,
        recommended_dishes=available_dishes,
        currency_code="INR",
    )
    ai_conv.pending_recommendation_interaction_json = draft.model_dump(mode="json")
    session.add(ai_conv)
    await session.commit()

    # Now call meal_recommend_accept
    result = await meal_recommend_accept(session, context, NoArgs())
    assert result["accepted"] is True
    assert result["cart_item_count"] == len(available_dishes)

    # Verify cart has the items in DB
    cart = await CartService(session).get_cart(context.dining_session_token)
    assert cart.quantity_count == len(available_dishes)

    # Verify pending draft was cleared
    await session.refresh(ai_conv)
    assert ai_conv.pending_recommendation_interaction_json is None


@pytest.mark.asyncio
async def test_19_expired_draft_safe(session: AsyncSession):
    data = await urban_tadka(session)
    context = customer_context(data)
    menu = await CustomerMenuService(session).get_menu(context.outlet_id)
    dishes = [dish for cat in menu.categories for dish in cat.dishes][:1]

    ai_conv = AIConversation(
        dining_session_id=data["dining_session"].id,
        outlet_id=context.outlet_id,
        public_token=f"conv-{uuid4().hex}",
    )
    draft = RecommendationDraftService.create_draft(
        outlet_id=context.outlet_id,
        dining_session_id=data["dining_session"].id,
        recommended_dishes=dishes,
        currency_code="INR",
        ttl_minutes=0,  # Expired immediately
    )
    # Force created_at to 1 hour ago
    draft.created_at = datetime.now(UTC) - timedelta(hours=1)
    ai_conv.pending_recommendation_interaction_json = draft.model_dump(mode="json")
    session.add(ai_conv)
    await session.commit()

    result = await meal_recommend_accept(session, context, NoArgs())
    assert result.get("error") == "draft_expired"

    # Cart should remain empty
    cart = await CartService(session).get_cart(context.dining_session_token)
    assert cart.item_count == 0


@pytest.mark.asyncio
async def test_20_cross_session_draft_isolation(session: AsyncSession):
    data = await urban_tadka(session)
    context1 = customer_context(data)
    context2 = customer_context(data)

    # Session 1 conversation has draft
    menu = await CustomerMenuService(session).get_menu(context1.outlet_id)
    dishes = [dish for cat in menu.categories for dish in cat.dishes][:1]

    ai_conv1 = AIConversation(
        dining_session_id=data["dining_session"].id,
        outlet_id=context1.outlet_id,
        public_token=f"conv1-{uuid4().hex}",
    )
    draft1 = RecommendationDraftService.create_draft(
        outlet_id=context1.outlet_id,
        dining_session_id=data["dining_session"].id,
        recommended_dishes=dishes,
        currency_code="INR",
    )
    ai_conv1.pending_recommendation_interaction_json = draft1.model_dump(mode="json")

    # Session 2 conversation has NO draft
    ai_conv2 = AIConversation(
        dining_session_id=data["other_session"].id,
        outlet_id=context2.outlet_id,
        public_token=f"conv2-{uuid4().hex}",
    )
    session.add_all([ai_conv1, ai_conv2])
    await session.commit()

    # Session 2 attempts revision
    from ainza_restaurant.ai.context import AIActorType, AIToolContext

    context_session2 = AIToolContext(
        actor_type=AIActorType.CUSTOMER,
        outlet_id=context2.outlet_id,
        dining_session_token=data["other_session"].public_session_token,
    )
    res2 = await meal_recommend_revise(
        session,
        context_session2,
        MealRecommendReviseInput(remove_target=dishes[0].name),
    )
    assert res2.get("error") == "no_active_recommendation"


@pytest.mark.asyncio
async def test_recommendation_revision_phrase_compilation_contract(session: AsyncSession) -> None:
    """Proves that recommendation revision phrases compile correctly from plan to tool arguments."""
    from ainza_restaurant.ai.customer_intent import CustomerIntentKind, CustomerIntentPlan
    from ainza_restaurant.ai.intent_compiler import CustomerIntentPlanCompiler

    data = await urban_tadka(session)
    context = customer_context(data)
    compiler = CustomerIntentPlanCompiler()

    # 1. "replace the main with something spicy"
    plan_replace = CustomerIntentPlan(
        intent=CustomerIntentKind.RECOMMENDATION_REVISE,
        revision_target="main",
        replacement_query="something spicy",
    )
    compiled_replace = await compiler.compile(session, context, plan_replace)
    assert compiled_replace.tool_name == "meal_recommend_revise"
    assert compiled_replace.arguments is not None
    assert compiled_replace.arguments["revision_target"] == "main"
    assert compiled_replace.arguments["replacement_query"] == "something spicy"

    # 2. "remove dessert"
    plan_remove = CustomerIntentPlan(
        intent=CustomerIntentKind.RECOMMENDATION_REVISE,
        remove_target="dessert",
    )
    compiled_remove = await compiler.compile(session, context, plan_remove)
    assert compiled_remove.tool_name == "meal_recommend_revise"
    assert compiled_remove.arguments is not None
    assert compiled_remove.arguments["remove_target"] == "dessert"

    # 3. "add a drink"
    plan_add = CustomerIntentPlan(
        intent=CustomerIntentKind.RECOMMENDATION_REVISE,
        add_query="drink",
    )
    compiled_add = await compiler.compile(session, context, plan_add)
    assert compiled_add.tool_name == "meal_recommend_revise"
    assert compiled_add.arguments is not None
    assert compiled_add.arguments["add_query"] == "drink"

    # 4. "make it cheaper"
    plan_cheaper = CustomerIntentPlan(
        intent=CustomerIntentKind.RECOMMENDATION_REVISE,
        make_cheaper=True,
    )
    compiled_cheaper = await compiler.compile(session, context, plan_cheaper)
    assert compiled_cheaper.tool_name == "meal_recommend_revise"
    assert compiled_cheaper.arguments is not None
    assert compiled_cheaper.arguments["make_cheaper"] is True

    # 5. "make it Jain"
    plan_jain = CustomerIntentPlan(
        intent=CustomerIntentKind.RECOMMENDATION_REVISE,
        is_jain=True,
    )
    compiled_jain = await compiler.compile(session, context, plan_jain)
    assert compiled_jain.tool_name == "meal_recommend_revise"
    assert compiled_jain.arguments is not None
    assert compiled_jain.arguments["is_jain"] is True


@pytest.mark.asyncio
async def test_null_and_empty_model_response_handling() -> None:
    """Proves customer_intent planner and tool_router safely handle None / empty model content."""
    from ainza_restaurant.ai.customer_intent import HierarchicalCustomerIntentPlanner
    from ainza_restaurant.ai.models import AIMessage, AIModelResponse
    from ainza_restaurant.ai.tool_router import CustomerToolCandidateRouter
    from ainza_restaurant.ai.tools.registry import build_default_registry

    class NullContentProvider:
        async def generate(
            self,
            *,
            messages: list[AIMessage],
            tool_schemas: list[dict[str, object]],
            tool_results: list[dict[str, object]] | None = None,
        ) -> AIModelResponse:
            return AIModelResponse(
                message=AIMessage(role="assistant", content=None),
                tool_calls=[],
            )

    null_provider = NullContentProvider()

    # 1. Customer intent planner with None content
    planner = HierarchicalCustomerIntentPlanner(provider=null_provider)  # type: ignore[arg-type]
    plan = await planner.plan(messages=[AIMessage(role="user", content="hello")])
    assert plan is None

    # 2. Tool candidate router with None content
    registry = build_default_registry()
    router = CustomerToolCandidateRouter(registry=registry, provider=null_provider)  # type: ignore[arg-type]
    route = await router.route(messages=[AIMessage(role="user", content="hello")])
    assert route.fallback_used is True
    assert route.needs_tools is True
    assert len(route.tools) > 0
