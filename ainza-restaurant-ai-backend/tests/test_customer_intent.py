from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.ai.context import AIActorType, AIToolContext
from ainza_restaurant.ai.customer_intent import (
    CartAddSlots,
    CartItemRequirement,
    CustomerIntentCartItem,
    CustomerIntentKind,
    CustomerIntentPlan,
    CustomerIntentPlanner,
    HierarchicalCustomerIntentPlanner,
    MealRecommendationGoal,
    MealRecommendationSlots,
    MenuSearchSlots,
)
from ainza_restaurant.ai.db_models import AIConversation
from ainza_restaurant.ai.grounded_response import GroundedResponseRenderer
from ainza_restaurant.ai.intent_compiler import CustomerIntentPlanCompiler
from ainza_restaurant.ai.models import AIMessage, AIModelResponse, AIToolResult
from ainza_restaurant.ai.schemas import (
    AIInteractionChoiceDimension,
    AIInteractionOptionRead,
    AIInteractionRead,
    AINavigationAction,
)
from ainza_restaurant.ai.service import CustomerAIConversationService
from ainza_restaurant.ai.tools.executor import AIToolExecutor
from ainza_restaurant.ai.tools.registry import build_default_registry
from ainza_restaurant.availability.models import DishAvailabilityOverride
from ainza_restaurant.db.base import Base
from ainza_restaurant.domain.enums import (
    AvailabilityReasonCode,
    AvailabilityStatus,
    DietaryClassification,
    HalalOverride,
    ReviewStatus,
    SpiceLevel,
)
from ainza_restaurant.menu.models import Category, Dish
from tests.test_ai_tools import NOW, customer_context, urban_tadka


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
    await engine.dispose()


@dataclass
class FixedResponseProvider:
    contents: list[str]

    async def generate(
        self,
        *,
        messages: list[AIMessage],
        tool_schemas: list[dict[str, object]],
        tool_results: list[dict[str, object]] | None = None,
    ) -> AIModelResponse:
        return AIModelResponse(message=AIMessage(role="assistant", content=self.contents.pop(0)))


@dataclass
class FixedPlanner:
    plan_value: CustomerIntentPlan | None

    async def plan(self, messages: list[AIMessage]) -> CustomerIntentPlan | None:
        return self.plan_value


@dataclass
class QueuePlanner:
    plans: list[CustomerIntentPlan | None]

    async def plan(self, messages: list[AIMessage]) -> CustomerIntentPlan | None:
        return self.plans.pop(0)


@pytest.mark.asyncio
async def test_planner_validates_json_and_repairs_once() -> None:
    planner = CustomerIntentPlanner(
        FixedResponseProvider(
            ["not json", '{"intent":"menu_search","text_query":"paneer","available_only":true}']
        )
    )

    plan = await planner.plan([AIMessage(role="user", content="Find paneer")])

    assert plan is not None
    assert plan.intent == CustomerIntentKind.MENU_SEARCH
    assert plan.text_query == "paneer"


@pytest.mark.asyncio
async def test_planner_projects_unknown_and_security_sensitive_fields() -> None:
    planner = CustomerIntentPlanner(
        FixedResponseProvider(
            [
                (
                    '{"intent":"menu_search","text_query":"paneer",'
                    '"dish_id":"untrusted","price":"1.00","confirmation":true,'
                    '"result":"untrusted"}'
                )
            ]
        )
    )

    plan = await planner.plan([AIMessage(role="user", content="Find paneer")])

    assert plan is not None
    assert plan.intent == CustomerIntentKind.MENU_SEARCH
    assert planner.last_discarded_field_names == ("confirmation", "dish_id", "price", "result")
    assert "dish_id" not in plan.model_dump()


@pytest.mark.asyncio
async def test_planner_rejects_invalid_or_conflicting_semantics() -> None:
    planner = CustomerIntentPlanner(
        FixedResponseProvider(
            [
                '{"intent":"menu_search","dietary_classification":"not-a-real-enum"}',
                '{"intent":"casual_conversation","dish_query":"not allowed"}',
            ]
        )
    )

    assert await planner.plan([AIMessage(role="user", content="Anything")]) is None


@pytest.mark.asyncio
async def test_hierarchical_planner_separates_menu_subject_and_filters() -> None:
    planner = HierarchicalCustomerIntentPlanner(
        FixedResponseProvider(
            [
                '{"intent":"menu_search"}',
                '{"text_query":"paneer","dietary_classification":"vegetarian","available_only":true}',
            ]
        )
    )

    plan = await planner.plan([AIMessage(role="user", content="Find suitable dishes")])

    assert plan is not None
    assert plan.intent == CustomerIntentKind.MENU_SEARCH
    assert plan.text_query == "paneer"
    assert plan.dietary_classification == DietaryClassification.VEGETARIAN
    assert plan.available_only is True
    assert "dish_query" not in MenuSearchSlots.model_fields


@pytest.mark.asyncio
async def test_cart_add_slots_reject_text_query_only() -> None:
    planner = HierarchicalCustomerIntentPlanner(
        FixedResponseProvider(
            [
                '{"intent":"cart_add"}',
                '{"text_query":"untrusted"}',
                '{"text_query":"untrusted"}',
            ]
        )
    )

    assert await planner.plan([AIMessage(role="user", content="Anything")]) is None
    assert "text_query" not in CartAddSlots.model_fields


@pytest.mark.asyncio
async def test_no_slot_intent_skips_second_model_call() -> None:
    provider = FixedResponseProvider(['{"intent":"menu_overview"}'])
    plan = await HierarchicalCustomerIntentPlanner(provider).plan(
        [AIMessage(role="user", content="Anything")]
    )

    assert plan is not None
    assert plan.intent == CustomerIntentKind.MENU_OVERVIEW
    assert provider.contents == []


def test_menu_search_prompt_keeps_unmentioned_filters_unspecified() -> None:
    planner = HierarchicalCustomerIntentPlanner(FixedResponseProvider([]))

    instruction = planner._slot_instruction(CustomerIntentKind.MENU_SEARCH)

    assert "optional filter null" in instruction
    assert "explicit negative constraint" in instruction


def test_cart_add_slots_normalize_legacy_and_canonical_multi_item_shapes() -> None:
    legacy = CartAddSlots.model_validate({"dish_query": "Paneer Tikka", "quantity": 2})
    multi = CartAddSlots.model_validate(
        {
            "items": [
                {"dish_query": "Veg Kolhapuri", "quantity": 1},
                {"dish_query": "Butter Naan", "quantity": 2},
            ]
        }
    )

    assert len(legacy.items) == 1
    assert legacy.items[0].dish_query == "Paneer Tikka"
    assert legacy.items[0].quantity == 2
    assert len(multi.items) == 2
    assert [item.dish_query for item in multi.items] == ["Veg Kolhapuri", "Butter Naan"]


@pytest.mark.asyncio
async def test_hierarchical_cart_planner_preserves_multi_item_semantics_through_compiler(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    extra_dishes = [
        Dish(
            menu_id=data["menu"].id,
            category_id=data["mains"].id,
            name="Veg Kolhapuri",
            base_price=Decimal("240"),
            review_status=ReviewStatus.CONFIRMED,
            dietary_classification=DietaryClassification.VEGETARIAN,
        ),
        Dish(
            menu_id=data["menu"].id,
            category_id=data["mains"].id,
            name="Tandoori Roti",
            base_price=Decimal("35"),
            review_status=ReviewStatus.CONFIRMED,
            dietary_classification=DietaryClassification.VEGETARIAN,
        ),
    ]
    session.add_all(extra_dishes)
    await session.flush()
    planner = HierarchicalCustomerIntentPlanner(
        FixedResponseProvider(
            [
                '{"intent":"cart_add"}',
                (
                    '{"items":['
                    '{"dish_query":"Veg Kolhapuri","quantity":1},'
                    '{"dish_query":"Tandoori Roti","quantity":2},'
                    '{"dish_query":"Butter Naan","quantity":1}'
                    ']}'
                ),
            ]
        )
    )

    plan = await planner.plan(
        [AIMessage(role="user", content="add veg kolhapuri, 2 tandoori roti and one butter naan")]
    )
    assert plan is not None
    assert [item.dish_query for item in plan.items] == [
        "Veg Kolhapuri",
        "Tandoori Roti",
        "Butter Naan",
    ]
    assert [item.quantity for item in plan.items] == [1, 2, 1]

    compiled = await CustomerIntentPlanCompiler().compile(
        session,
        customer_context(data),
        plan,
        original_message="add veg kolhapuri, 2 tandoori roti and one butter naan",
    )
    assert compiled.tool_name == "cart_add_items"
    assert compiled.arguments is not None
    compiled_items = compiled.arguments["items"]
    assert [item["requested_reference"] for item in compiled_items] == [
        "Veg Kolhapuri",
        "Tandoori Roti",
        "Butter Naan",
    ]
    assert [item["quantity"] for item in compiled_items] == [1, 2, 1]


@pytest.mark.asyncio
async def test_hierarchical_conditional_cart_planner_selects_batch_capability(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    planner = HierarchicalCustomerIntentPlanner(
        FixedResponseProvider(
            [
                '{"intent":"cart_add"}',
                (
                    '{"items":[{"dish_query":"buttermilk","quantity":1,'
                    '"requirement":"conditional"}]}'
                ),
            ]
        )
    )

    plan = await planner.plan(
        [AIMessage(role="user", content="also add buttermilk if available")]
    )
    assert plan is not None
    assert len(plan.items) == 1
    assert plan.items[0].dish_query == "buttermilk"
    assert plan.items[0].requirement == CartItemRequirement.CONDITIONAL

    compiled = await CustomerIntentPlanCompiler().compile(
        session,
        customer_context(data),
        plan,
        original_message="also add buttermilk if available",
    )
    assert compiled.tool_name == "cart_add_items"
    assert compiled.arguments == {
        "items": [
            {
                "dish_id": None,
                "quantity": 1,
                "modifier_option_ids": [],
                "required": False,
                "requested_reference": "buttermilk",
            }
        ]
    }


@pytest.mark.asyncio
async def test_hierarchical_single_cart_item_remains_canonical_and_safe(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    planner = HierarchicalCustomerIntentPlanner(
        FixedResponseProvider(
            [
                '{"intent":"cart_add"}',
                '{"items":[{"dish_query":"Paneer Tikka","quantity":1}]}' ,
            ]
        )
    )

    plan = await planner.plan([AIMessage(role="user", content="add one Paneer Tikka")])
    assert plan is not None
    assert len(plan.items) == 1
    assert plan.items[0].dish_query == "Paneer Tikka"
    compiled = await CustomerIntentPlanCompiler().compile(
        session, customer_context(data), plan, original_message="add one Paneer Tikka"
    )
    assert compiled.tool_name == "cart_add_items"
    assert compiled.arguments is not None
    assert compiled.arguments["items"][0]["quantity"] == 1


@pytest.mark.skip(
    reason=(
        "_pending_interaction_payload and _resolve_pending_recommendation_choice were removed "
        "from CustomerAIConversationService during the agentic migration. "
        "This interaction flow is now handled by the agentic tool loop."
    )
)
@pytest.mark.asyncio
async def test_pending_choice_matching_prefers_specific_typed_option(
    session: AsyncSession,
) -> None:
    service = CustomerAIConversationService(
        session, provider=FixedResponseProvider([]), now=lambda: NOW
    )
    base = CustomerIntentPlan(intent=CustomerIntentKind.MEAL_RECOMMENDATION)
    interaction = AIInteractionRead(
        question="What would you prefer?",
        choice_dimension=AIInteractionChoiceDimension.DIETARY_CLASSIFICATION,
        options=[
            AIInteractionOptionRead(label="Vegetarian", semantic_value="vegetarian"),
            AIInteractionOptionRead(label="Non-vegetarian", semantic_value="non_vegetarian"),
            AIInteractionOptionRead(label="No preference", semantic_value="no_preference"),
        ],
    )
    pending = service._pending_interaction_payload(base, interaction)

    for options in (pending.options, list(reversed(pending.options))):
        pending.options = options
        assert (
            service._resolve_pending_recommendation_choice(pending, "vegetarian")
            .dietary_classification
            == DietaryClassification.VEGETARIAN
        )
        assert (
            service._resolve_pending_recommendation_choice(pending, "non vegetarian")
            .dietary_classification
            == DietaryClassification.NON_VEGETARIAN
        )
        assert (
            service._resolve_pending_recommendation_choice(pending, "I prefer non vegetarian")
            .dietary_classification
            == DietaryClassification.NON_VEGETARIAN
        )
        assert (
            service._resolve_pending_recommendation_choice(pending, "no preference")
            .dietary_classification
            is None
        )


def test_menu_search_supports_filter_only_and_price_constraints() -> None:
    vegetarian = CustomerIntentPlan(
        intent=CustomerIntentKind.MENU_SEARCH,
        dietary_classification=DietaryClassification.VEGETARIAN,
    )
    price_range = MenuSearchSlots(price_min=Decimal("200"), price_max=Decimal("400"))

    assert vegetarian.text_query is None
    assert price_range.text_query is None
    assert price_range.price_min == Decimal("200")
    assert price_range.price_max == Decimal("400")
    with pytest.raises(ValidationError):
        CustomerIntentPlan(intent=CustomerIntentKind.MENU_SEARCH)
    with pytest.raises(ValidationError):
        CustomerIntentPlan(
            intent=CustomerIntentKind.MENU_SEARCH,
            price_min=Decimal("400"),
            price_max=Decimal("200"),
        )


def test_unknown_customer_semantic_sentinels_are_not_constraints() -> None:
    plan = CustomerIntentPlan(
        intent=CustomerIntentKind.MENU_SEARCH,
        text_query="dinner",
        dietary_classification=DietaryClassification.UNKNOWN,
        spice_level=SpiceLevel.UNKNOWN,
        jain_status=AvailabilityStatus.UNKNOWN,
        vegan_status=AvailabilityStatus.UNKNOWN,
        halal_status=HalalOverride.UNKNOWN,
    )

    assert plan.dietary_classification is None
    assert plan.spice_level is None
    assert plan.jain_status is None
    assert plan.vegan_status is None
    assert plan.halal_status is None


def test_explicit_customer_semantic_constraints_remain_intact() -> None:
    plan = CustomerIntentPlan(
        intent=CustomerIntentKind.MENU_SEARCH,
        text_query="dinner",
        dietary_classification=DietaryClassification.VEGETARIAN,
        spice_level=SpiceLevel.MILD,
        jain_status=AvailabilityStatus.AVAILABLE,
        vegan_status=AvailabilityStatus.NOT_AVAILABLE,
        halal_status=HalalOverride.RESTAURANT_CONFIRMED_HALAL,
    )

    assert plan.dietary_classification == DietaryClassification.VEGETARIAN
    assert plan.spice_level == SpiceLevel.MILD
    assert plan.jain_status == AvailabilityStatus.AVAILABLE
    assert plan.vegan_status == AvailabilityStatus.NOT_AVAILABLE
    assert plan.halal_status == HalalOverride.RESTAURANT_CONFIRMED_HALAL


def test_meal_recommendation_validates_budget_and_party_size() -> None:
    plan = CustomerIntentPlan(
        intent=CustomerIntentKind.MEAL_RECOMMENDATION,
        party_size=3,
        budget_max=Decimal("1500"),
    )
    assert plan.party_size == 3
    assert MealRecommendationSlots(party_size=3, budget_max=Decimal("1500")).budget_max == Decimal(
        "1500"
    )
    with pytest.raises(ValidationError):
        MealRecommendationSlots(party_size=0)
    with pytest.raises(ValidationError):
        CustomerIntentPlan(
            intent=CustomerIntentKind.MEAL_RECOMMENDATION,
            budget_min=Decimal("500"),
            budget_max=Decimal("100"),
        )


@pytest.mark.asyncio
async def test_menu_search_plan_compiles_structured_filters(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    compiler = CustomerIntentPlanCompiler()
    compiled = await compiler.compile(
        session,
        customer_context(data),
        CustomerIntentPlan(
            intent=CustomerIntentKind.MENU_SEARCH,
            text_query="paneer",
            dietary_classification=DietaryClassification.VEGETARIAN,
            available_only=True,
        ),
    )

    assert compiled.tool_name == "menu_search"
    assert compiled.arguments == {
        "text_query": "paneer",
        "filters": {"dietary_classification": "vegetarian", "available": True},
    }


@pytest.mark.asyncio
async def test_money_intents_compile_to_their_distinct_authoritative_tools(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    context = customer_context(data)
    compiler = CustomerIntentPlanCompiler()

    current_total = await compiler.compile(
        session,
        context,
        CustomerIntentPlan(intent=CustomerIntentKind.CURRENT_TOTAL),
    )
    cart_get = await compiler.compile(
        session,
        context,
        CustomerIntentPlan(intent=CustomerIntentKind.CART_GET),
    )
    bill_preview = await compiler.compile(
        session,
        context,
        CustomerIntentPlan(intent=CustomerIntentKind.BILL_PREVIEW),
    )

    assert current_total.tool_name == "customer_total_summary"
    assert cart_get.tool_name == "cart_get"
    assert bill_preview.tool_name == "bill_get_preview"


@pytest.mark.asyncio
async def test_multi_item_compiler_resolves_required_and_skips_missing_optional(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    compiled = await CustomerIntentPlanCompiler().compile(
        session,
        customer_context(data),
        CustomerIntentPlan(
            intent=CustomerIntentKind.CART_ADD,
            items=[
                CustomerIntentCartItem(dish_query="Paneer Tikka", quantity=1),
                CustomerIntentCartItem(
                    dish_query="Buttermilk",
                    requirement=CartItemRequirement.CONDITIONAL,
                ),
            ],
        ),
    )
    assert compiled.tool_name == "cart_add_items"
    assert compiled.arguments is not None
    assert compiled.arguments["items"][0]["dish_id"] == str(data["tikka"].id)
    assert compiled.arguments["items"][1]["dish_id"] is None
    assert compiled.arguments["items"][1]["required"] is False


@pytest.mark.asyncio
async def test_menu_search_plan_compiles_filter_only_and_price_bounds(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    compiled = await CustomerIntentPlanCompiler().compile(
        session,
        customer_context(data),
        CustomerIntentPlan(
            intent=CustomerIntentKind.MENU_SEARCH,
            dietary_classification=DietaryClassification.VEGETARIAN,
            price_min=Decimal("200"),
            price_max=Decimal("400"),
        ),
    )

    assert compiled.tool_name == "menu_search"
    assert compiled.arguments == {
        "text_query": None,
        "filters": {
            "dietary_classification": "vegetarian",
            "price_min": Decimal("200"),
            "price_max": Decimal("400"),
        },
    }
    result = await AIToolExecutor(build_default_registry(), now=lambda: NOW).execute(
        session,
        compiled.tool_name,
        compiled.arguments,
        customer_context(data),
    )
    assert result.ok is True
    assert [dish["name"] for dish in result.data] == ["Paneer Tikka"]


@pytest.mark.asyncio
async def test_meal_recommendation_compiles_and_stays_within_budget(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    compiled = await CustomerIntentPlanCompiler().compile(
        session,
        customer_context(data),
        CustomerIntentPlan(
            intent=CustomerIntentKind.MEAL_RECOMMENDATION,
            party_size=3,
            budget_max=Decimal("1500"),
        ),
    )

    assert compiled.tool_name == "meal_recommend"
    assert compiled.arguments is not None
    result = await AIToolExecutor(build_default_registry(), now=lambda: NOW).execute(
        session, compiled.tool_name, compiled.arguments, customer_context(data)
    )
    assert result.ok is True
    assert result.data["total"] <= Decimal("1500")
    assert result.data["items"]
    assert {item["name"] for item in result.data["items"]}.isdisjoint({"Other Paneer"})


@pytest.mark.asyncio
async def test_soft_preference_query_is_not_forwarded_as_enforced_tool_input(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    compiled = await CustomerIntentPlanCompiler().compile(
        session,
        customer_context(data),
        CustomerIntentPlan(
            intent=CustomerIntentKind.MEAL_RECOMMENDATION,
            preference_query="something special",
        ),
    )

    assert compiled.arguments is not None
    assert "preference_query" not in compiled.arguments


@pytest.mark.asyncio
async def test_meal_recommendation_low_budget_returns_no_plan(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    result = await AIToolExecutor(build_default_registry(), now=lambda: NOW).execute(
        session,
        "meal_recommend",
        {"party_size": 3, "budget_max": "1.00"},
        customer_context(data),
    )

    assert result.ok is True
    assert result.data["no_plan"] is True
    assert result.data["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "goal",
    [
        MealRecommendationGoal.GENERAL_RECOMMENDATION,
        MealRecommendationGoal.BALANCED_MEAL,
        MealRecommendationGoal.FULL_MEAL,
    ],
)
async def test_broad_recommendation_prefers_main_over_cheap_accompaniment_and_drink(
    session: AsyncSession,
    goal: MealRecommendationGoal,
) -> None:
    data = await urban_tadka(session)
    menu = data["menu"]
    data["mains"].name = "Breads"
    starter = Category(menu_id=menu.id, name="Starters", slug="starters")
    main = Category(menu_id=menu.id, name="Mains", slug="meal-mains")
    bread = Category(menu_id=menu.id, name="Breads", slug="breads")
    drink = Category(menu_id=menu.id, name="Drinks", slug="drinks")
    session.add_all([starter, main, bread, drink])
    await session.flush()
    session.add_all(
        [
            Dish(
                menu_id=menu.id,
                category_id=starter.id,
                name="Starter",
                base_price=Decimal("250"),
                review_status=ReviewStatus.CONFIRMED,
            ),
            Dish(
                menu_id=menu.id,
                category_id=main.id,
                name="Main",
                base_price=Decimal("400"),
                review_status=ReviewStatus.CONFIRMED,
            ),
            Dish(
                menu_id=menu.id,
                category_id=bread.id,
                name="Bread",
                base_price=Decimal("45"),
                review_status=ReviewStatus.CONFIRMED,
            ),
            Dish(
                menu_id=menu.id,
                category_id=drink.id,
                name="Drink",
                base_price=Decimal("90"),
                review_status=ReviewStatus.CONFIRMED,
            ),
        ]
    )
    await session.flush()

    result = await AIToolExecutor(build_default_registry(), now=lambda: NOW).execute(
        session,
        "meal_recommend",
        {"party_size": 2, "recommendation_goal": goal},
        customer_context(data),
    )

    assert result.ok is True
    names = {item["name"] for item in result.data["items"]}
    assert "Main" in names
    assert names != {"Bread", "Drink"}


def test_meal_recommendation_prompt_protects_current_turn_constraints() -> None:
    planner = HierarchicalCustomerIntentPlanner(FixedResponseProvider([]))

    instruction = planner._slot_instruction(CustomerIntentKind.MEAL_RECOMMENDATION)

    assert "do not inherit a prior search filter" in instruction
    assert "never use 0 as an unknown-budget placeholder" in instruction


def test_planner_prompt_preserves_interaction_choice_as_current_turn_context() -> None:
    planner = CustomerIntentPlanner(FixedResponseProvider([]))

    prompt = planner._prompt(repair=0)

    assert "current recommendation only" in prompt
    assert "permanent customer preferences" in prompt


def test_interaction_and_navigation_contracts_are_typed() -> None:
    interaction = AIInteractionRead(
        question="What would you prefer?",
        choice_dimension=AIInteractionChoiceDimension.DIETARY_CLASSIFICATION,
        options=[AIInteractionOptionRead(label="Vegetarian", semantic_value="vegetarian")],
    )

    assert interaction.options[0].semantic_value == "vegetarian"
    assert AINavigationAction.BROWSE_CATEGORIES.value == "browse_categories"


@pytest.mark.asyncio
async def test_temporary_search_filter_is_not_required_for_next_recommendation() -> None:
    planner = HierarchicalCustomerIntentPlanner(
        FixedResponseProvider(
            [
                '{"intent":"meal_recommendation"}',
                '{"party_size":3,"budget_max":1500}',
            ]
        )
    )

    plan = await planner.plan(
        [
            AIMessage(role="user", content="Show non vegetarian dishes"),
            AIMessage(role="assistant", content="I found matching dishes."),
            AIMessage(role="user", content="Budget 1500 for 3 people, what should we order?"),
        ]
    )

    assert plan is not None
    assert plan.dietary_classification is None
    assert plan.party_size == 3


@pytest.mark.asyncio
async def test_unmentioned_budget_remains_null_for_broad_recommendation() -> None:
    planner = HierarchicalCustomerIntentPlanner(
        FixedResponseProvider(['{"intent":"meal_recommendation"}', "{}"])
    )

    plan = await planner.plan([AIMessage(role="user", content="What should we eat?")])

    assert plan is not None
    assert plan.budget_min is None
    assert plan.budget_max is None


@pytest.mark.asyncio
async def test_prior_budget_is_not_copied_into_independent_recommendation() -> None:
    planner = HierarchicalCustomerIntentPlanner(
        FixedResponseProvider(['{"intent":"meal_recommendation"}', "{}"])
    )

    plan = await planner.plan(
        [
            AIMessage(role="user", content="Suggest a meal under 900"),
            AIMessage(role="assistant", content="Here is a meal within 900."),
            AIMessage(role="user", content="What should we eat now?"),
        ]
    )

    assert plan is not None
    assert plan.budget_min is None
    assert plan.budget_max is None


def test_no_plan_renderer_only_mentions_budget_when_authoritatively_present() -> None:
    renderer = GroundedResponseRenderer()
    no_budget = renderer.render(
        [
            AIToolResult(
                ok=True,
                tool="meal_recommend",
                data={"items": [], "budget_min": None, "budget_max": None},
                generated_at=NOW,
            )
        ]
    )
    with_budget = renderer.render(
        [
            AIToolResult(
                ok=True,
                tool="meal_recommend",
                data={"items": [], "budget_min": None, "budget_max": Decimal("100")},
                generated_at=NOW,
            )
        ]
    )

    assert "budget" not in no_budget.casefold()
    assert "budget" in with_budget.casefold()


@pytest.mark.asyncio
async def test_explicit_user_restriction_can_be_represented_for_recommendation() -> None:
    planner = HierarchicalCustomerIntentPlanner(
        FixedResponseProvider(
            [
                '{"intent":"meal_recommendation"}',
                '{"party_size":3,"budget_max":1500,"dietary_classification":"vegetarian"}',
            ]
        )
    )

    plan = await planner.plan(
        [
            AIMessage(role="user", content="I am vegetarian"),
            AIMessage(role="user", content="Budget 1500 for 3 people, what should we order?"),
        ]
    )

    assert plan is not None
    assert plan.dietary_classification == DietaryClassification.VEGETARIAN


@pytest.mark.asyncio
async def test_follow_up_vegetarian_plan_does_not_filter_unknown_spice(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    planner = HierarchicalCustomerIntentPlanner(
        FixedResponseProvider(
            [
                '{"intent":"meal_recommendation"}',
                (
                    '{"dietary_classification":"vegetarian",'
                    '"spice_level":"unknown","party_size":2}'
                ),
            ]
        )
    )

    plan = await planner.plan(
        [
            AIMessage(
                role="assistant",
                content="What would you prefer - vegetarian or non-vegetarian?",
            ),
            AIMessage(role="user", content="vegetarian"),
        ]
    )

    assert plan is not None
    assert plan.dietary_classification == DietaryClassification.VEGETARIAN
    assert plan.spice_level is None

    compiled = await CustomerIntentPlanCompiler().compile(
        session,
        customer_context(data),
        plan,
    )

    assert compiled.arguments is not None
    assert compiled.arguments["filters"] == {
        "dietary_classification": DietaryClassification.VEGETARIAN,
    }
    result = await AIToolExecutor(build_default_registry(), now=lambda: NOW).execute(
        session,
        compiled.tool_name or "",
        compiled.arguments,
        customer_context(data),
    )

    assert result.ok is True
    assert "Paneer Tikka" in {item["name"] for item in result.data["items"]}


@pytest.mark.asyncio
async def test_cart_add_plan_resolves_authoritative_dish_id(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    compiler = CustomerIntentPlanCompiler()
    compiled = await compiler.compile(
        session,
        customer_context(data),
        CustomerIntentPlan(
            intent=CustomerIntentKind.CART_ADD,
            dish_query="Paneer Tikka",
            quantity=1,
        ),
    )

    assert compiled.tool_name == "cart_add_item"
    assert compiled.arguments is not None
    assert compiled.arguments["dish_id"] == str(data["tikka"].id)
    assert "dish_query" not in compiled.arguments
    result = await AIToolExecutor(build_default_registry(), now=lambda: NOW).execute(
        session,
        compiled.tool_name,
        compiled.arguments,
        customer_context(data),
    )
    assert result.ok is True
    assert result.data["items"][0]["dish_name"] == "Paneer Tikka"


@pytest.mark.asyncio
async def test_entity_fallback_matches_one_authoritative_dish_name(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    compiled = await CustomerIntentPlanCompiler().compile(
        session,
        customer_context(data),
        CustomerIntentPlan(
            intent=CustomerIntentKind.CART_ADD,
            dish_query="please add it",
            quantity=1,
        ),
        original_message="Please add one Paneer Tikka.",
    )

    assert compiled.arguments is not None
    assert compiled.arguments["dish_id"] == str(data["tikka"].id)


@pytest.mark.asyncio
async def test_ambiguous_or_missing_dish_never_compiles_cart_mutation(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    compiler = CustomerIntentPlanCompiler()
    context = AIToolContext(
        actor_type=AIActorType.CUSTOMER,
        outlet_id=data["outlet"].id,
        dining_session_token=data["dining_session"].public_session_token,
    )
    ambiguous = await compiler.compile(
        session,
        context,
        CustomerIntentPlan(intent=CustomerIntentKind.CART_ADD, dish_query="a"),
    )
    missing = await compiler.compile(
        session,
        context,
        CustomerIntentPlan(intent=CustomerIntentKind.CART_ADD, dish_query="Not On The Menu"),
    )

    assert ambiguous.tool_name is None
    assert "multiple" in (ambiguous.clarification or "")
    assert missing.tool_name is None
    assert "couldn't find" in (missing.clarification or "")


@pytest.mark.asyncio
async def test_previous_grounded_list_reference_resolves_authoritative_order(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    compiled = await CustomerIntentPlanCompiler().compile(
        session,
        customer_context(data),
        CustomerIntentPlan(
            intent=CustomerIntentKind.CART_ADD,
            reference_to_previous_result=1,
        ),
        previous_assistant_text="I found: Paneer Tikka; Butter Naan.",
    )

    assert compiled.tool_name == "cart_add_item"
    assert compiled.arguments is not None
    assert compiled.arguments["dish_id"] == str(data["tikka"].id)


@pytest.mark.skip(reason="Legacy intent planner service tests deprecated in favor of agentic AI conversation service")
@pytest.mark.asyncio
async def test_service_uses_typed_plan_for_grounded_tool_execution(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    service = CustomerAIConversationService(
        session,
        provider=FixedResponseProvider([]),
        intent_planner=FixedPlanner(CustomerIntentPlan(intent=CustomerIntentKind.MENU_OVERVIEW)),
        now=lambda: NOW,
    )
    conversation = await service.create_conversation(data["dining_session"].public_session_token)

    response = await service.send_message(
        conversation.conversation_token,
        client_message_id="typed-menu",
        message="irrelevant natural language",
    )

    assert response.tools_used == ["menu_get"]
    assert "Paneer Tikka" in response.assistant_message
    assert response.discovery is not None
    assert [category.id for category in response.discovery.categories] == [data["mains"].id]
    assert [item.action for item in response.navigation] == [AINavigationAction.BROWSE_CATEGORIES]


@pytest.mark.skip(reason="Legacy intent planner service tests deprecated in favor of agentic AI conversation service")
@pytest.mark.asyncio
async def test_service_allows_casual_plan_without_restaurant_tool(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    service = CustomerAIConversationService(
        session,
        provider=FixedResponseProvider(["Hello! How can I help today?"]),
        intent_planner=FixedPlanner(
            CustomerIntentPlan(intent=CustomerIntentKind.CASUAL_CONVERSATION)
        ),
        now=lambda: NOW,
    )
    conversation = await service.create_conversation(data["dining_session"].public_session_token)

    response = await service.send_message(
        conversation.conversation_token,
        client_message_id="typed-casual",
        message="irrelevant natural language",
    )

    assert response.tools_used == []
    assert response.assistant_message == "Hello! How can I help today?"


@pytest.mark.skip(reason="Legacy intent planner service tests deprecated in favor of agentic AI conversation service")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answer", "expected_dish"),
    [
        ("vegetarian", "Paneer Tikka"),
        ("non vegetarian", "Chicken Curry"),
    ],
)
async def test_pending_recommendation_answer_takes_priority_before_generic_menu_search(
    session: AsyncSession,
    answer: str,
    expected_dish: str,
) -> None:
    data = await urban_tadka(session)
    session.add(
        Dish(
            menu_id=data["menu"].id,
            category_id=data["mains"].id,
            name="Chicken Curry",
            base_price=Decimal("350"),
            review_status=ReviewStatus.CONFIRMED,
            dietary_classification=DietaryClassification.NON_VEGETARIAN,
        )
    )
    await session.flush()

    base = CustomerIntentPlan(
        intent=CustomerIntentKind.MEAL_RECOMMENDATION,
        party_size=2,
        recommendation_goal=MealRecommendationGoal.BALANCED_MEAL,
    )
    conversation_token = (
        await CustomerAIConversationService(
            session,
            provider=FixedResponseProvider([]),
            intent_planner=QueuePlanner([base]),
            now=lambda: NOW,
        ).create_conversation(data["dining_session"].public_session_token)
    ).conversation_token

    await CustomerAIConversationService(
        session,
        provider=FixedResponseProvider([]),
        intent_planner=QueuePlanner([base]),
        now=lambda: NOW,
    ).send_message(conversation_token, client_message_id="recommendation-start", message="dinner")

    second_service = CustomerAIConversationService(
        session,
        provider=FixedResponseProvider([]),
        intent_planner=QueuePlanner([
            CustomerIntentPlan(intent=CustomerIntentKind.MENU_SEARCH, text_query="vegetarian")
        ]),
        now=lambda: NOW,
    )
    second = await second_service.send_message(
        conversation_token, client_message_id="recommendation-answer", message=answer
    )

    assert second.tools_used == ["meal_recommend"]
    assert expected_dish in second.assistant_message
    stored = await session.scalar(
        select(AIConversation).where(AIConversation.public_token == conversation_token)
    )
    assert stored is not None
    assert stored.pending_recommendation_interaction_json is None


@pytest.mark.skip(reason="Legacy intent planner service tests deprecated in favor of agentic AI conversation service")
@pytest.mark.asyncio
async def test_pending_recommendation_is_persisted_consumed_and_not_reused(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    session.add(
        Dish(
            menu_id=data["menu"].id,
            category_id=data["mains"].id,
            name="Chicken Curry",
            base_price=Decimal("350"),
            review_status=ReviewStatus.CONFIRMED,
            dietary_classification=DietaryClassification.NON_VEGETARIAN,
        )
    )
    await session.flush()
    initial = CustomerIntentPlan(
        intent=CustomerIntentKind.MEAL_RECOMMENDATION,
        party_size=2,
        recommendation_goal=MealRecommendationGoal.BALANCED_MEAL,
    )
    vegetarian = CustomerIntentPlan(
        intent=CustomerIntentKind.MEAL_RECOMMENDATION,
        dietary_classification=DietaryClassification.VEGETARIAN,
    )
    conversation_token = (
        await CustomerAIConversationService(
            session,
            provider=FixedResponseProvider([]),
            intent_planner=QueuePlanner([initial, vegetarian]),
            now=lambda: NOW,
        ).create_conversation(data["dining_session"].public_session_token)
    ).conversation_token

    first_service = CustomerAIConversationService(
        session,
        provider=FixedResponseProvider([]),
        intent_planner=QueuePlanner([initial, vegetarian]),
        now=lambda: NOW,
    )
    first = await first_service.send_message(
        conversation_token, client_message_id="recommendation-start", message="dinner"
    )
    assert first.interaction is not None
    stored = await session.scalar(
        select(AIConversation).where(AIConversation.public_token == conversation_token)
    )
    assert stored is not None
    assert stored.pending_recommendation_interaction_json is not None
    assert stored.pending_recommendation_interaction_json["base_plan"]["party_size"] == 2
    assert (
        stored.pending_recommendation_interaction_json["base_plan"]["recommendation_goal"]
        == "balanced_meal"
    )

    second_service = CustomerAIConversationService(
        session,
        provider=FixedResponseProvider([]),
        intent_planner=QueuePlanner([vegetarian]),
        now=lambda: NOW,
    )
    second = await second_service.send_message(
        conversation_token, client_message_id="recommendation-answer", message="vegetarian"
    )
    assert second.tools_used == ["meal_recommend"]
    assert stored.pending_recommendation_interaction_json is None

    third_service = CustomerAIConversationService(
        session,
        provider=FixedResponseProvider([]),
        intent_planner=QueuePlanner([initial]),
        now=lambda: NOW,
    )
    third = await third_service.send_message(
        conversation_token, client_message_id="recommendation-new", message="dinner again"
    )
    assert third.interaction is not None
    assert stored.pending_recommendation_interaction_json is not None
    assert stored.pending_recommendation_interaction_json["base_plan"]["budget_max"] is None


@pytest.mark.skip(reason="Legacy intent planner service tests deprecated in favor of agentic AI conversation service")
@pytest.mark.asyncio
async def test_pending_no_preference_keeps_base_constraints_only(session: AsyncSession) -> None:
    base = CustomerIntentPlan(
        intent=CustomerIntentKind.MEAL_RECOMMENDATION,
        party_size=2,
        budget_max=Decimal("900"),
        recommendation_goal=MealRecommendationGoal.FULL_MEAL,
    )
    interaction = AIInteractionRead(
        question="What would you prefer?",
        choice_dimension=AIInteractionChoiceDimension.DIETARY_CLASSIFICATION,
        options=[
            AIInteractionOptionRead(label="Vegetarian", semantic_value="vegetarian"),
            AIInteractionOptionRead(label="No preference", semantic_value="no_preference"),
        ],
    )
    service = CustomerAIConversationService(
        session,
        provider=FixedResponseProvider([]),
        now=lambda: NOW,
    )
    state = service._pending_interaction_payload(
        base, interaction
    )

    merged = CustomerAIConversationService._merge_pending_recommendation(
        state,
        CustomerIntentPlan(intent=CustomerIntentKind.MEAL_RECOMMENDATION),
    )

    assert merged is not None
    assert merged.dietary_classification is None
    assert merged.party_size == 2
    assert merged.budget_max == Decimal("900")
    assert merged.recommendation_goal == MealRecommendationGoal.FULL_MEAL


@pytest.mark.skip(reason="Legacy intent planner service tests deprecated in favor of agentic AI conversation service")
@pytest.mark.asyncio
async def test_expired_pending_recommendation_is_cleared_and_replanned(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    session.add(
        Dish(
            menu_id=data["menu"].id,
            category_id=data["mains"].id,
            name="Chicken Curry",
            base_price=Decimal("350"),
            review_status=ReviewStatus.CONFIRMED,
            dietary_classification=DietaryClassification.NON_VEGETARIAN,
        )
    )
    await session.flush()
    plan = CustomerIntentPlan(intent=CustomerIntentKind.MEAL_RECOMMENDATION, party_size=2)
    service = CustomerAIConversationService(
        session,
        provider=FixedResponseProvider([]),
        intent_planner=QueuePlanner([plan]),
        now=lambda: NOW,
    )
    token = (
        await service.create_conversation(data["dining_session"].public_session_token)
    ).conversation_token
    conversation = await session.scalar(
        select(AIConversation).where(AIConversation.public_token == token)
    )
    assert conversation is not None
    conversation.pending_recommendation_interaction_json = {
        "base_plan": {
            "party_size": 2,
            "budget_min": None,
            "budget_max": None,
            "dietary_classification": None,
            "spice_level": None,
            "jain_status": None,
            "vegan_status": None,
            "halal_status": None,
            "preference_query": None,
            "recommendation_goal": "general_recommendation",
        },
        "choice_dimension": "dietary_classification",
        "options": [{"semantic_value": "vegetarian", "label": "Vegetarian"}],
        "created_at": "2026-09-12T00:00:00Z",
        "expires_at": "2026-09-12T00:01:00Z",
    }
    await session.commit()

    response = await service.send_message(token, client_message_id="expired", message="dinner")

    assert response.interaction is not None
    assert conversation.pending_recommendation_interaction_json is not None


@pytest.mark.skip(reason="Legacy intent planner service tests deprecated in favor of agentic AI conversation service")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "goal",
    [
        MealRecommendationGoal.GENERAL_RECOMMENDATION,
        MealRecommendationGoal.BALANCED_MEAL,
        MealRecommendationGoal.FULL_MEAL,
        MealRecommendationGoal.LIGHT_MEAL,
    ],
)
async def test_broad_meal_goals_use_authoritative_dietary_interaction(
    session: AsyncSession,
    goal: MealRecommendationGoal,
) -> None:
    data = await urban_tadka(session)
    session.add(
        Dish(
            menu_id=data["menu"].id,
            category_id=data["mains"].id,
            name="Chicken Curry",
            base_price=Decimal("350"),
            review_status=ReviewStatus.CONFIRMED,
            dietary_classification=DietaryClassification.NON_VEGETARIAN,
        )
    )
    await session.flush()
    service = CustomerAIConversationService(session, provider=FixedResponseProvider([]))

    interaction = await service._recommendation_interaction(
        data["outlet"].id,
        CustomerIntentPlan(
            intent=CustomerIntentKind.MEAL_RECOMMENDATION,
            party_size=2,
            recommendation_goal=goal,
        ),
    )

    assert interaction is not None
    assert interaction.choice_dimension == AIInteractionChoiceDimension.DIETARY_CLASSIFICATION
    assert [option.semantic_value for option in interaction.options] == [
        "vegetarian",
        "non_vegetarian",
        "no_preference",
    ]


@pytest.mark.skip(reason="Legacy intent planner service tests deprecated in favor of agentic AI conversation service")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "goal",
    [MealRecommendationGoal.DESSERT, MealRecommendationGoal.DRINKS, MealRecommendationGoal.SNACK],
)
async def test_specialized_meal_goals_skip_generic_interaction(
    session: AsyncSession,
    goal: MealRecommendationGoal,
) -> None:
    data = await urban_tadka(session)
    session.add(
        Dish(
            menu_id=data["menu"].id,
            category_id=data["mains"].id,
            name="Chicken Curry",
            base_price=Decimal("350"),
            review_status=ReviewStatus.CONFIRMED,
            dietary_classification=DietaryClassification.NON_VEGETARIAN,
        )
    )
    await session.flush()
    service = CustomerAIConversationService(session, provider=FixedResponseProvider([]))

    interaction = await service._recommendation_interaction(
        data["outlet"].id,
        CustomerIntentPlan(
            intent=CustomerIntentKind.MEAL_RECOMMENDATION,
            recommendation_goal=goal,
        ),
    )

    assert interaction is None


@pytest.mark.skip(reason="Legacy intent planner service tests deprecated in favor of agentic AI conversation service")
@pytest.mark.asyncio
async def test_broad_recommendation_uses_actual_category_options_when_needed(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    starter = Category(menu_id=data["menu"].id, name="Starters", slug="starters")
    session.add(starter)
    await session.flush()
    session.add(
        Dish(
            menu_id=data["menu"].id,
            category_id=starter.id,
            name="Veg Kebab",
            base_price=Decimal("180"),
            review_status=ReviewStatus.CONFIRMED,
            dietary_classification=DietaryClassification.VEGETARIAN,
        )
    )
    await session.flush()
    service = CustomerAIConversationService(session, provider=FixedResponseProvider([]))

    interaction = await service._recommendation_interaction(
        data["outlet"].id,
        CustomerIntentPlan(intent=CustomerIntentKind.MEAL_RECOMMENDATION),
    )

    assert interaction is not None
    assert interaction.choice_dimension == AIInteractionChoiceDimension.CATEGORY
    assert {option.label for option in interaction.options} == {
        "Mains",
        "Starters",
        "No preference",
    }
    assert {option.reference_id for option in interaction.options if option.reference_id} == {
        data["mains"].id,
        starter.id,
    }


@pytest.mark.skip(reason="Legacy intent planner service tests deprecated in favor of agentic AI conversation service")
@pytest.mark.asyncio
async def test_constrained_recommendation_does_not_ask_follow_up(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    service = CustomerAIConversationService(session, provider=FixedResponseProvider([]))

    interaction = await service._recommendation_interaction(
        data["outlet"].id,
        CustomerIntentPlan(
            intent=CustomerIntentKind.MEAL_RECOMMENDATION,
            dietary_classification=DietaryClassification.VEGETARIAN,
            party_size=3,
            budget_max=Decimal("900"),
        ),
    )

    assert interaction is None


@pytest.mark.skip(reason="Legacy intent planner service tests deprecated in favor of agentic AI conversation service")
@pytest.mark.asyncio
async def test_category_search_exposes_authoritative_browse_payload(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    service = CustomerAIConversationService(
        session,
        provider=FixedResponseProvider([]),
        intent_planner=FixedPlanner(
            CustomerIntentPlan(intent=CustomerIntentKind.MENU_SEARCH, category_query="Mains")
        ),
        now=lambda: NOW,
    )
    conversation = await service.create_conversation(data["dining_session"].public_session_token)

    response = await service.send_message(
        conversation.conversation_token,
        client_message_id="browse-mains",
        message="show mains",
    )

    assert response.discovery is not None
    assert response.discovery.category is not None
    assert response.discovery.category.id == data["mains"].id
    assert [category.id for category in response.discovery.categories] == [data["mains"].id]
    assert {item.dish.name for item in response.discovery.category.dishes} == {
        "Paneer Tikka",
        "Butter Naan",
    }
    assert all(item.addable for item in response.discovery.category.dishes)
    assert {item.action for item in response.navigation} == {
        AINavigationAction.BROWSE_CATEGORIES,
        AINavigationAction.BROWSE_CATEGORY,
    }


@pytest.mark.skip(reason="Legacy intent planner service tests deprecated in favor of agentic AI conversation service")
@pytest.mark.asyncio
async def test_category_browse_marks_unavailable_dishes_not_addable(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    now = datetime.now(UTC)
    session.add(
        DishAvailabilityOverride(
            dish_id=data["naan"].id,
            starts_at=now - timedelta(minutes=1),
            expires_at=None,
            reason_code=AvailabilityReasonCode.OUT_OF_STOCK,
            source_proposal_id=uuid4(),
        )
    )
    await session.commit()
    service = CustomerAIConversationService(
        session,
        provider=FixedResponseProvider([]),
        intent_planner=FixedPlanner(
            CustomerIntentPlan(intent=CustomerIntentKind.MENU_SEARCH, category_query="Mains")
        ),
        now=lambda: NOW,
    )
    conversation = await service.create_conversation(data["dining_session"].public_session_token)

    response = await service.send_message(
        conversation.conversation_token,
        client_message_id="browse-unavailable-mains",
        message="show mains",
    )

    assert response.discovery is not None
    assert response.discovery.category is not None
    addability = {item.dish.name: item.addable for item in response.discovery.category.dishes}
    assert addability["Butter Naan"] is False
    assert addability["Paneer Tikka"] is True


@pytest.mark.skip(reason="Legacy intent planner service tests deprecated in favor of agentic AI conversation service")
@pytest.mark.asyncio
async def test_successful_cart_add_exposes_authoritative_navigation(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    service = CustomerAIConversationService(
        session,
        provider=FixedResponseProvider([]),
        intent_planner=FixedPlanner(
            CustomerIntentPlan(intent=CustomerIntentKind.CART_ADD, dish_query="Butter Naan")
        ),
        now=lambda: NOW,
    )
    conversation = await service.create_conversation(data["dining_session"].public_session_token)

    response = await service.send_message(
        conversation.conversation_token,
        client_message_id="add-naan",
        message="add one naan",
    )

    assert {item.action for item in response.navigation} == {
        AINavigationAction.BROWSE_CATEGORIES,
        AINavigationAction.ADD_MORE_CURRENT_CATEGORY,
        AINavigationAction.VIEW_CART,
    }
    add_more = next(
        item
        for item in response.navigation
        if item.action == AINavigationAction.ADD_MORE_CURRENT_CATEGORY
    )
    assert add_more.category_id == data["mains"].id
