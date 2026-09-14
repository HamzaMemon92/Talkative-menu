from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.ai.category_roles import MenuCategoryRole, category_role
from ainza_restaurant.ai.context import AIToolContext
from ainza_restaurant.ai.customer_intent import (
    CustomerIntentKind,
    CustomerIntentPlan,
)
from ainza_restaurant.customer_menu.schemas import CustomerDishRead
from ainza_restaurant.customer_menu.service import CustomerMenuService
from ainza_restaurant.ordering.service import CartService


@dataclass(frozen=True)
class CompiledCustomerIntent:
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    clarification: str | None = None
    unsupported: bool = False


class CustomerIntentPlanCompiler:
    """Compiles semantic plans into existing approved customer tool arguments."""

    async def compile(
        self,
        session: AsyncSession,
        context: AIToolContext,
        plan: CustomerIntentPlan,
        *,
        previous_assistant_text: str | None = None,
        original_message: str | None = None,
    ) -> CompiledCustomerIntent:
        if plan.needs_clarification:
            return CompiledCustomerIntent(clarification="Could you clarify what you would like?")
        if plan.intent == CustomerIntentKind.CASUAL_CONVERSATION:
            return CompiledCustomerIntent()
        if plan.intent in {CustomerIntentKind.UNSUPPORTED, CustomerIntentKind.OUT_OF_DOMAIN}:
            return CompiledCustomerIntent(unsupported=True)
        if plan.intent == CustomerIntentKind.RECOMMENDATION_ACCEPT:
            return CompiledCustomerIntent(tool_name="meal_recommend_accept", arguments={})
        if plan.intent == CustomerIntentKind.RECOMMENDATION_REVISE:
            return CompiledCustomerIntent(
                tool_name="meal_recommend_revise",
                arguments={
                    "revision_target": plan.revision_target,
                    "replacement_query": plan.replacement_query,
                    "remove_target": plan.remove_target,
                    "add_query": plan.add_query,
                    "make_cheaper": plan.make_cheaper,
                    "dietary_filter": plan.dietary_filter,
                    "is_jain": plan.is_jain,
                    "is_less_spicy": plan.is_less_spicy,
                },
            )
        simple = {
            CustomerIntentKind.MENU_OVERVIEW: "menu_get",
            CustomerIntentKind.OFFERS_GET: "offers_get_effective",
            CustomerIntentKind.CART_GET: "cart_get",
            CustomerIntentKind.CART_SUBMIT: "cart_submit",
            CustomerIntentKind.ORDERS_GET: "orders_get_session",
            CustomerIntentKind.BILL_PREVIEW: "bill_get_preview",
            CustomerIntentKind.CURRENT_TOTAL: "customer_total_summary",
        }
        if plan.intent in simple:
            return CompiledCustomerIntent(tool_name=simple[plan.intent], arguments={})
        if plan.intent == CustomerIntentKind.MENU_SEARCH:
            filters: dict[str, object] = {
                key: value
                for key, value in {
                    "dietary_classification": plan.dietary_classification,
                    "spice_level": plan.spice_level,
                    "jain_status": plan.jain_status,
                    "vegan_status": plan.vegan_status,
                    "halal_status": plan.halal_status,
                    "available": plan.available_only,
                    "price_min": plan.price_min,
                    "price_max": plan.price_max,
                }.items()
                if value is not None
            }
            if plan.category_query:
                category_id = await self._resolve_category_id(session, context, plan.category_query)
                if category_id is None:
                    return CompiledCustomerIntent(
                        clarification="I couldn't find that menu category."
                    )
                filters["category_id"] = str(category_id)
            if plan.category_role:
                category_id = await self._resolve_category_role_id(
                    session, context, plan.category_role
                )
                if category_id is None:
                    return CompiledCustomerIntent(
                        clarification="I couldn't find that menu category."
                    )
                filters["category_id"] = str(category_id)
            return CompiledCustomerIntent(
                tool_name="menu_search",
                arguments={"text_query": plan.text_query, "filters": filters or None},
            )
        if plan.intent == CustomerIntentKind.MEAL_RECOMMENDATION:
            filters = {
                key: value
                for key, value in {
                    "dietary_classification": plan.dietary_classification,
                    "spice_level": plan.spice_level,
                    "jain_status": plan.jain_status,
                    "vegan_status": plan.vegan_status,
                    "halal_status": plan.halal_status,
                }.items()
                if value is not None
            }
            return CompiledCustomerIntent(
                tool_name="meal_recommend",
                arguments={
                    "party_size": plan.party_size,
                    "budget_min": plan.budget_min,
                    "budget_max": plan.budget_max,
                    "filters": filters or None,
                    "recommendation_goal": plan.recommendation_goal,
                },
            )
        if plan.intent == CustomerIntentKind.CART_ADD and plan.items:
            compiled_items: list[dict[str, object]] = []
            for item_plan in plan.items:
                dish, clarification = await self._resolve_dish(
                    session,
                    context,
                    item_plan.dish_query,
                    original_message=original_message,
                )
                if clarification:
                    if item_plan.requirement.value == "conditional":
                        compiled_items.append(
                            {
                                "dish_id": None,
                                "quantity": item_plan.quantity,
                                "modifier_option_ids": [],
                                "required": False,
                                "requested_reference": item_plan.dish_query,
                            }
                        )
                        continue
                    return CompiledCustomerIntent(clarification=clarification)
                assert dish is not None
                variant_id: str | None = None
                if item_plan.variant_query:
                    variants = [
                        variant
                        for variant in dish.variants
                        if _normalize(variant.name) == _normalize(item_plan.variant_query or "")
                    ]
                    if len(variants) != 1:
                        return CompiledCustomerIntent(
                            clarification="Please choose an available variant for that dish."
                        )
                    variant_id = str(variants[0].id)
                modifier_ids: list[str] = []
                for query in item_plan.modifier_queries:
                    options = [
                        option
                        for group in dish.modifiers
                        for option in group.options
                        if _normalize(option.name) == _normalize(query)
                    ]
                    if len(options) != 1:
                        return CompiledCustomerIntent(
                            clarification="Please clarify the modifier you would like."
                        )
                    modifier_ids.append(str(options[0].id))
                compiled_items.append(
                    {
                        "dish_id": str(dish.id),
                        "variant_id": variant_id,
                        "quantity": item_plan.quantity,
                        "modifier_option_ids": modifier_ids,
                        "customer_note": item_plan.customer_note,
                        "required": item_plan.requirement.value == "required",
                        "requested_reference": item_plan.dish_query,
                    }
                )
            return CompiledCustomerIntent(
                tool_name="cart_add_items",
                arguments={"items": compiled_items},
            )
        if plan.intent in {
            CustomerIntentKind.DISH_DETAIL,
            CustomerIntentKind.DISH_AVAILABILITY,
            CustomerIntentKind.CART_ADD,
        }:
            dish, clarification = await self._resolve_dish(
                session,
                context,
                plan.dish_query,
                reference_index=plan.reference_to_previous_result,
                previous_assistant_text=previous_assistant_text,
                original_message=original_message,
            )
            if clarification:
                return CompiledCustomerIntent(clarification=clarification)
            assert dish is not None
            if plan.intent == CustomerIntentKind.DISH_DETAIL:
                return CompiledCustomerIntent("menu_get_dish", {"dish_id": str(dish.id)})
            if plan.intent == CustomerIntentKind.DISH_AVAILABILITY:
                return CompiledCustomerIntent("dish_get_availability", {"dish_id": str(dish.id)})
            return await self._compile_cart_add(dish, plan)
        if plan.intent in {CustomerIntentKind.CART_UPDATE, CustomerIntentKind.CART_REMOVE}:
            return await self._compile_cart_item(session, context, plan)
        return CompiledCustomerIntent(unsupported=True)

    async def _resolve_category_id(
        self, session: AsyncSession, context: AIToolContext, query: str
    ) -> UUID | None:
        normalized = " ".join(query.casefold().split())
        categories = (await CustomerMenuService(session).get_menu(context.outlet_id)).categories
        matches = [
            category
            for category in categories
            if " ".join(category.name.casefold().split()) == normalized
        ]
        return matches[0].id if len(matches) == 1 else None

    async def _resolve_category_role_id(
        self, session: AsyncSession, context: AIToolContext, role: MenuCategoryRole
    ) -> UUID | None:
        categories = (await CustomerMenuService(session).get_menu(context.outlet_id)).categories
        matches = [category for category in categories if category_role(category.name) == role]
        return matches[0].id if len(matches) == 1 else None

    async def _resolve_dish(
        self,
        session: AsyncSession,
        context: AIToolContext,
        query: str | None,
        *,
        reference_index: int | None = None,
        previous_assistant_text: str | None = None,
        original_message: str | None = None,
    ) -> tuple[CustomerDishRead | None, str | None]:
        menu = await CustomerMenuService(session).get_menu(context.outlet_id)
        dishes = [dish for category in menu.categories for dish in category.dishes]
        if reference_index is not None and not query:
            exposed = sorted(
                (
                    (previous_assistant_text.find(dish.name), dish)
                    for dish in dishes
                    if previous_assistant_text and dish.name in previous_assistant_text
                ),
                key=lambda value: value[0],
            )
            if reference_index <= len(exposed):
                return exposed[reference_index - 1][1], None
            return None, "I need the dish name before I can identify that item."
        if not query:
            return None, "Which dish did you mean?"
        normalized = _normalize(query)
        exact = [dish for dish in dishes if _normalize(dish.name) == normalized]
        matches = exact or [dish for dish in dishes if normalized in _normalize(dish.name)]
        if not matches and original_message:
            utterance = _normalize(original_message)
            matches = [dish for dish in dishes if _normalize(dish.name) in utterance]
        if not matches:
            return None, "I couldn't find that dish in the current menu."
        if len(matches) > 1:
            names = ", ".join(dish.name for dish in matches[:5])
            return None, f"I found multiple matching dishes: {names}. Which one did you mean?"
        return matches[0], None

    async def _compile_cart_add(
        self, dish: CustomerDishRead, plan: CustomerIntentPlan
    ) -> CompiledCustomerIntent:
        variant_id: str | None = None
        if plan.variant_query:
            variant_matches = [
                variant
                for variant in dish.variants
                if _normalize(variant.name) == _normalize(plan.variant_query)
            ]
            if len(variant_matches) != 1:
                return CompiledCustomerIntent(
                    clarification="Please choose an available variant for that dish."
                )
            variant_id = str(variant_matches[0].id)
        modifier_ids: list[str] = []
        for query in plan.modifier_queries:
            modifier_matches = [
                option
                for group in dish.modifiers
                for option in group.options
                if _normalize(option.name) == _normalize(query)
            ]
            if len(modifier_matches) != 1:
                return CompiledCustomerIntent(
                    clarification="Please clarify the modifier you would like."
                )
            modifier_ids.append(str(modifier_matches[0].id))
        return CompiledCustomerIntent(
            tool_name="cart_add_item",
            arguments={
                "dish_id": str(dish.id),
                "variant_id": variant_id,
                "quantity": plan.quantity or 1,
                "modifier_option_ids": modifier_ids,
            },
        )

    async def _compile_cart_item(
        self, session: AsyncSession, context: AIToolContext, plan: CustomerIntentPlan
    ) -> CompiledCustomerIntent:
        token = context.dining_session_token
        if token is None or not plan.cart_item_reference:
            return CompiledCustomerIntent(clarification="Which cart item did you mean?")
        cart = await CartService(session).get_cart(token)
        reference = _normalize(plan.cart_item_reference)
        matches = [item for item in cart.items if reference in _normalize(item.dish_name)]
        if len(matches) != 1:
            return CompiledCustomerIntent(clarification="Which cart item did you mean?")
        arguments: dict[str, Any] = {
            "cart_item_id": str(matches[0].id),
            "expected_cart_version": cart.version,
        }
        if plan.intent == CustomerIntentKind.CART_UPDATE:
            if plan.quantity is None:
                return CompiledCustomerIntent(clarification="What quantity would you like?")
            arguments["quantity"] = plan.quantity
            return CompiledCustomerIntent("cart_update_item", arguments)
        return CompiledCustomerIntent("cart_remove_item", arguments)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())
