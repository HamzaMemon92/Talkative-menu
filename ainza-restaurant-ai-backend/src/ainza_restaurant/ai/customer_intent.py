from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ainza_restaurant.ai.category_roles import MenuCategoryRole
from ainza_restaurant.ai.models import AIMessage, AIModelResponse
from ainza_restaurant.ai.providers.base import ToolCallingModelProvider
from ainza_restaurant.ai.providers.llama_cpp import (
    AIModelProviderError,
    LlamaCppToolCallingProvider,
)
from ainza_restaurant.domain.enums import (
    AvailabilityStatus,
    DietaryClassification,
    HalalOverride,
    SpiceLevel,
)


class CustomerIntentKind(StrEnum):
    CASUAL_CONVERSATION = "casual_conversation"
    MENU_OVERVIEW = "menu_overview"
    MENU_SEARCH = "menu_search"
    MEAL_RECOMMENDATION = "meal_recommendation"
    DISH_DETAIL = "dish_detail"
    DISH_AVAILABILITY = "dish_availability"
    OFFERS_GET = "offers_get"
    CART_GET = "cart_get"
    CART_ADD = "cart_add"
    CART_UPDATE = "cart_update"
    CART_REMOVE = "cart_remove"
    CART_SELECT_OFFER = "cart_select_offer"
    CART_SUBMIT = "cart_submit"
    ORDERS_GET = "orders_get"
    BILL_PREVIEW = "bill_preview"
    CURRENT_TOTAL = "current_total"
    QUOTE_SELECTION = "quote_selection"
    UNSUPPORTED = "unsupported"


class CartItemRequirement(StrEnum):
    REQUIRED = "required"
    CONDITIONAL = "conditional"


class MealRecommendationGoal(StrEnum):
    GENERAL_RECOMMENDATION = "general_recommendation"
    BALANCED_MEAL = "balanced_meal"
    LIGHT_MEAL = "light_meal"
    FULL_MEAL = "full_meal"
    SNACK = "snack"
    DESSERT = "dessert"
    DRINKS = "drinks"


class CustomerIntentPlan(BaseModel):
    """Small model-facing expression of customer meaning, never internal identifiers."""

    model_config = ConfigDict(extra="forbid")

    intent: CustomerIntentKind
    text_query: str | None = Field(default=None, min_length=1, max_length=200)
    category_query: str | None = Field(default=None, min_length=1, max_length=200)
    category_role: MenuCategoryRole | None = None
    dish_query: str | None = Field(default=None, max_length=200)
    dietary_classification: DietaryClassification | None = None
    spice_level: SpiceLevel | None = None
    jain_status: AvailabilityStatus | None = None
    vegan_status: AvailabilityStatus | None = None
    halal_status: HalalOverride | None = None
    available_only: bool | None = None
    price_min: Decimal | None = Field(default=None, ge=Decimal("0"))
    price_max: Decimal | None = Field(default=None, ge=Decimal("0"))
    party_size: int | None = Field(default=None, ge=1, le=20)
    budget_min: Decimal | None = Field(default=None, ge=Decimal("0"))
    budget_max: Decimal | None = Field(default=None, ge=Decimal("0"))
    # Soft planner context only; the deterministic recommendation service does not apply it yet.
    preference_query: str | None = Field(default=None, min_length=1, max_length=200)
    recommendation_goal: MealRecommendationGoal = MealRecommendationGoal.GENERAL_RECOMMENDATION
    quantity: int | None = Field(default=None, ge=1, le=99)
    cart_item_reference: str | None = Field(default=None, max_length=200)
    variant_query: str | None = Field(default=None, max_length=200)
    modifier_queries: list[str] = Field(default_factory=list, max_length=10)
    offer_query: str | None = Field(default=None, max_length=200)
    reference_to_previous_result: int | None = Field(default=None, ge=1, le=20)
    needs_clarification: bool = False
    # Ordered semantic items for natural-language multi-item cart requests.
    items: list[CustomerIntentCartItem] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_intent_semantics(self) -> CustomerIntentPlan:
        _normalize_customer_semantic_filters(self)
        if self.needs_clarification:
            return self
        if self.intent == CustomerIntentKind.MENU_SEARCH:
            constraints = (
                self.text_query,
                self.category_query,
                self.category_role,
                self.dietary_classification,
                self.spice_level,
                self.jain_status,
                self.vegan_status,
                self.halal_status,
                self.available_only,
                self.price_min,
                self.price_max,
            )
            if not any(value is not None for value in constraints):
                raise ValueError("menu_search requires a query or filter constraint")
            if self.price_min is not None and self.price_max is not None:
                if self.price_min > self.price_max:
                    raise ValueError("menu_search price_min must not exceed price_max")
        if self.intent == CustomerIntentKind.MEAL_RECOMMENDATION:
            if self.budget_min is not None and self.budget_max is not None:
                if self.budget_min > self.budget_max:
                    raise ValueError("meal_recommendation budget_min must not exceed budget_max")
        if self.intent == CustomerIntentKind.CART_ADD and self.items:
            return self
        if self.intent in {
            CustomerIntentKind.DISH_DETAIL,
            CustomerIntentKind.DISH_AVAILABILITY,
            CustomerIntentKind.CART_ADD,
        } and not (self.dish_query or self.reference_to_previous_result):
            raise ValueError(
                f"{self.intent.value} requires dish_query or previous-result reference"
            )
        if (
            self.intent in {CustomerIntentKind.CART_UPDATE, CustomerIntentKind.CART_REMOVE}
            and not self.cart_item_reference
        ):
            raise ValueError(f"{self.intent.value} requires cart_item_reference")
        if self.intent == CustomerIntentKind.CASUAL_CONVERSATION and any(
            value is not None
            for value in (
                self.text_query,
                self.dish_query,
                self.quantity,
                self.cart_item_reference,
                self.variant_query,
                self.offer_query,
                self.reference_to_previous_result,
            )
        ):
            raise ValueError("casual_conversation cannot include restaurant action fields")
        return self


class CustomerIntentCartItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dish_query: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=1, ge=1, le=99)
    variant_query: str | None = Field(default=None, max_length=200)
    modifier_queries: list[str] = Field(default_factory=list, max_length=10)
    customer_note: str | None = Field(default=None, max_length=500)
    requirement: CartItemRequirement = CartItemRequirement.REQUIRED


CustomerIntentPlan.model_rebuild()


PLAN_FIELD_NAMES = frozenset(CustomerIntentPlan.model_fields)


class CustomerIntentPlanner:
    """Produces a validated semantic plan without exposing production tool schemas."""

    def __init__(self, provider: ToolCallingModelProvider) -> None:
        self.provider = provider
        self.last_discarded_field_names: tuple[str, ...] = ()

    async def plan(self, messages: list[AIMessage]) -> CustomerIntentPlan | None:
        for repair in range(2):
            prompt = self._prompt(repair=repair)
            planner_messages = [AIMessage(role="system", content=prompt), *messages]
            response = await self._generate(planner_messages)
            content = response.message.content if response.message else ""
            parsed = self._parse(content)
            if parsed is not None:
                return parsed
        return None

    async def _generate(self, messages: list[AIMessage]):  # type: ignore[no-untyped-def]
        if isinstance(self.provider, LlamaCppToolCallingProvider):
            try:
                return await self.provider.generate_json(
                    messages=messages,
                    json_schema=CustomerIntentPlan.model_json_schema(),
                )
            except AIModelProviderError as exc:
                if exc.code != "ai_model_invalid_request":
                    raise
        return await self.provider.generate(messages=messages, tool_schemas=[], tool_results=[])

    def _prompt(self, *, repair: int) -> str:
        repair_instruction = (
            "Your previous output was invalid. Return only one valid JSON object now.\n"
            if repair
            else ""
        )
        kinds = ", ".join(intent.value for intent in CustomerIntentKind)
        return f"""/no_think
You interpret restaurant customer intent. Return ONLY a JSON CustomerIntentPlan.
Supported intent values: {kinds}.
Use only customer meaning: text_query, category_query, dish_query, dietary_classification,
spice_level, jain_status, vegan_status, halal_status, available_only, price_min, price_max,
party_size, budget_min, budget_max, preference_query, quantity, cart_item_reference,
variant_query, modifier_queries, offer_query,
reference_to_previous_result, needs_clarification.
If the immediately preceding assistant message asks one recommendation preference question,
interpret the user's reply as a constraint for that current recommendation only. Do not turn
temporary search or recommendation choices into permanent customer preferences.
Never output UUIDs, factual menu prices, availability facts, confirmation, tool names,
or customer prose.
Use casual_conversation for ordinary social chat and unsupported for unavailable requests.
{repair_instruction}"""

    def _parse(self, content: str) -> CustomerIntentPlan | None:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
            if not isinstance(payload, dict):
                return None
            projected = {key: value for key, value in payload.items() if key in PLAN_FIELD_NAMES}
            self.last_discarded_field_names = tuple(
                sorted(str(key) for key in payload if key not in PLAN_FIELD_NAMES)
            )
            return CustomerIntentPlan.model_validate(projected)
        except (json.JSONDecodeError, ValidationError):
            return None


class IntentClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: CustomerIntentKind
    needs_clarification: bool = False


class MenuSearchSlots(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text_query: str | None = Field(default=None, min_length=1, max_length=200)
    category_query: str | None = Field(default=None, min_length=1, max_length=200)
    category_role: MenuCategoryRole | None = None
    dietary_classification: DietaryClassification | None = None
    spice_level: SpiceLevel | None = None
    jain_status: AvailabilityStatus | None = None
    vegan_status: AvailabilityStatus | None = None
    halal_status: HalalOverride | None = None
    available_only: bool | None = None
    price_min: Decimal | None = Field(default=None, ge=Decimal("0"))
    price_max: Decimal | None = Field(default=None, ge=Decimal("0"))

    @model_validator(mode="after")
    def require_search_constraint(self) -> MenuSearchSlots:
        _normalize_customer_semantic_filters(self)
        constraints = (
            self.text_query,
            self.category_query,
            self.category_role,
            self.dietary_classification,
            self.spice_level,
            self.jain_status,
            self.vegan_status,
            self.halal_status,
            self.available_only,
            self.price_min,
            self.price_max,
        )
        if not any(value is not None for value in constraints):
            raise ValueError("menu_search requires a query or filter constraint")
        if self.price_min is not None and self.price_max is not None:
            if self.price_min > self.price_max:
                raise ValueError("menu_search price_min must not exceed price_max")
        return self


class CartAddSlots(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dish_query: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: int | None = Field(default=None, ge=1, le=99)
    variant_query: str | None = Field(default=None, min_length=1, max_length=200)
    modifier_queries: list[str] = Field(default_factory=list, max_length=10)
    reference_to_previous_result: int | None = Field(default=None, ge=1, le=20)
    items: list[CustomerIntentCartItem] = Field(default_factory=list, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_shape(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if "items" in data:
            return data
        if "dish_query" not in data and "reference_to_previous_result" not in data:
            return data
        legacy_items: list[dict[str, object]] = []
        legacy_item = {
            "dish_query": data.get("dish_query"),
            "quantity": data.get("quantity") or 1,
            "variant_query": data.get("variant_query"),
            "modifier_queries": data.get("modifier_queries") or [],
            "customer_note": data.get("customer_note"),
            "requirement": data.get("requirement") or "required",
        }
        legacy_items.append(legacy_item)
        return {**data, "items": legacy_items}

    @model_validator(mode="after")
    def require_dish_reference(self) -> CartAddSlots:
        if self.items:
            return self
        if self.reference_to_previous_result is not None:
            return self
        if self.dish_query:
            self.items = [
                CustomerIntentCartItem(
                    dish_query=self.dish_query,
                    quantity=self.quantity or 1,
                    variant_query=self.variant_query,
                    modifier_queries=self.modifier_queries,
                    requirement=CartItemRequirement.REQUIRED,
                )
            ]
            return self
        raise ValueError("cart_add requires a requested item or previous-result reference")


class MealRecommendationSlots(BaseModel):
    model_config = ConfigDict(extra="forbid")

    party_size: int | None = Field(default=None, ge=1, le=20)
    budget_min: Decimal | None = Field(default=None, ge=Decimal("0"))
    budget_max: Decimal | None = Field(default=None, ge=Decimal("0"))
    dietary_classification: DietaryClassification | None = None
    spice_level: SpiceLevel | None = None
    jain_status: AvailabilityStatus | None = None
    vegan_status: AvailabilityStatus | None = None
    halal_status: HalalOverride | None = None
    preference_query: str | None = Field(default=None, min_length=1, max_length=200)
    recommendation_goal: MealRecommendationGoal = MealRecommendationGoal.GENERAL_RECOMMENDATION

    @model_validator(mode="after")
    def validate_budget_range(self) -> MealRecommendationSlots:
        _normalize_customer_semantic_filters(self)
        if self.budget_min is not None and self.budget_max is not None:
            if self.budget_min > self.budget_max:
                raise ValueError("budget_min must not exceed budget_max")
        return self


class PendingRecommendationInteractionOption(BaseModel):
    semantic_value: str
    label: str
    reference_id: str | None = None


class PendingRecommendationInteraction(BaseModel):
    base_plan: MealRecommendationSlots
    choice_dimension: str
    options: list[PendingRecommendationInteractionOption] = Field(min_length=1, max_length=4)
    created_at: datetime
    expires_at: datetime

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


def _normalize_customer_semantic_filters(model: BaseModel) -> None:
    """Treat model-emitted UNKNOWN sentinels as absent customer constraints."""
    sentinels = (
        ("dietary_classification", DietaryClassification.UNKNOWN),
        ("spice_level", SpiceLevel.UNKNOWN),
        ("jain_status", AvailabilityStatus.UNKNOWN),
        ("vegan_status", AvailabilityStatus.UNKNOWN),
        ("halal_status", HalalOverride.UNKNOWN),
    )
    for field_name, sentinel in sentinels:
        if getattr(model, field_name, None) == sentinel:
            setattr(model, field_name, None)


class DishReferenceSlots(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dish_query: str | None = Field(default=None, min_length=1, max_length=200)
    reference_to_previous_result: int | None = Field(default=None, ge=1, le=20)

    @model_validator(mode="after")
    def require_dish_reference(self) -> DishReferenceSlots:
        if not (self.dish_query or self.reference_to_previous_result):
            raise ValueError("dish reference is required")
        return self


class CartItemSlots(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cart_item_reference: str = Field(min_length=1, max_length=200)
    quantity: int | None = Field(default=None, ge=1, le=99)


SLOT_MODELS: dict[CustomerIntentKind, type[BaseModel]] = {
    CustomerIntentKind.MENU_SEARCH: MenuSearchSlots,
    CustomerIntentKind.MEAL_RECOMMENDATION: MealRecommendationSlots,
    CustomerIntentKind.CART_ADD: CartAddSlots,
    CustomerIntentKind.DISH_DETAIL: DishReferenceSlots,
    CustomerIntentKind.DISH_AVAILABILITY: DishReferenceSlots,
    CustomerIntentKind.CART_UPDATE: CartItemSlots,
    CustomerIntentKind.CART_REMOVE: CartItemSlots,
}


class HierarchicalCustomerIntentPlanner:
    """Classifies intent first, then extracts only intent-relevant semantic slots."""

    def __init__(self, provider: ToolCallingModelProvider) -> None:
        self.provider = provider
        self.last_discarded_field_names: tuple[str, ...] = ()

    async def plan(self, messages: list[AIMessage]) -> CustomerIntentPlan | None:
        classification = await self._model(
            IntentClassification,
            messages,
            "Classify the customer restaurant intent only. Return JSON only; do not extract slots.",
        )
        if not isinstance(classification, IntentClassification):
            return None
        if classification.needs_clarification or classification.intent not in SLOT_MODELS:
            return CustomerIntentPlan(
                intent=classification.intent,
                needs_clarification=classification.needs_clarification,
            )
        slot_model = SLOT_MODELS[classification.intent]
        slots = await self._model(
            slot_model,
            messages,
            self._slot_instruction(classification.intent),
        )
        if slots is None:
            return None
        payload = slots.model_dump(exclude_none=True)
        return CustomerIntentPlan(intent=classification.intent, **payload)

    async def _model(
        self, model: type[BaseModel], messages: list[AIMessage], instruction: str
    ) -> BaseModel | None:
        for repair in range(2):
            prompt = (
                f"/no_think\n{instruction}\n"
                "The current user message is authoritative. "
                "Prior messages are supporting context only.\n"
                "Never copy prior assistant results or temporary search filters into a new plan "
                "unless the current message explicitly refers to them.\n"
                "Only explicit user personal restrictions may persist.\n"
                "Return only one JSON object. "
                "Never include IDs, prices, confirmation, tools, or prose."
            )
            if repair:
                prompt += " Previous output was invalid; use only the declared fields."
            response = await self._generate(
                [AIMessage(role="system", content=prompt), *messages], model
            )
            parsed = self._parse_model(response.message.content if response.message else "", model)
            if parsed is not None:
                return parsed
        return None

    async def _generate(self, messages: list[AIMessage], model: type[BaseModel]) -> AIModelResponse:
        if isinstance(self.provider, LlamaCppToolCallingProvider):
            try:
                return await self.provider.generate_json(
                    messages=messages,
                    json_schema=model.model_json_schema(),
                )
            except AIModelProviderError as exc:
                if exc.code != "ai_model_invalid_request":
                    raise
        return await self.provider.generate(messages=messages, tool_schemas=[], tool_results=[])

    def _parse_model(self, content: str, model: type[BaseModel]) -> BaseModel | None:
        text = content.strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
            if not isinstance(payload, dict):
                return None
            allowed = set(model.model_fields)
            self.last_discarded_field_names = tuple(
                sorted(str(key) for key in payload if key not in allowed)
            )
            return model.model_validate(
                {key: value for key, value in payload.items() if key in allowed}
            )
        except (json.JSONDecodeError, ValidationError):
            return None

    def _slot_instruction(self, intent: CustomerIntentKind) -> str:
        if intent == CustomerIntentKind.MENU_SEARCH:
            return (
                "Extract menu search subject and canonical filters. text_query contains only the "
                "remaining dish, name, ingredient, or cuisine concept; never copy filter words. "
                "Use category_query only for a named menu category. "
                "Use category_role for dessert, drink, starter, or main. Price bounds are numeric "
                "customer constraints, not menu facts. A filter-only search has text_query null. "
                "Leave every optional filter null unless the customer explicitly requested it; "
                "never infer availability and set false only for an explicit negative constraint."
            )
        if intent == CustomerIntentKind.CART_ADD:
            return (
                "Extract every independently requested food or drink item from the current "
                "message as a canonical items list. Preserve each item's own quantity, variant, "
                "modifiers, and whether it is conditional via conditional_if_available or "
                "requirement=conditional. If the customer says 'if available', only that item is "
                "conditional; do not collapse multiple requested dishes into the first one. "
                "When a single item is requested, return a one-item list. Do not include IDs, "
                "prices, or any hidden tool names."
            )
        if intent == CustomerIntentKind.MEAL_RECOMMENDATION:
            return (
                "Extract only the current request's party size, budget bounds, explicit dietary or "
                "preference constraints. Budget and group requests are meal_recommendation, "
                "not menu_search. Use a meal goal to distinguish a normal meal from snacks, "
                "drinks, or dessert. "
                "budget_min and budget_max must remain null unless the current user request "
                "explicitly states a monetary budget, price limit, or range; never use 0 as an "
                "unknown-budget placeholder. Do not inherit a prior turn's budget unless the "
                "current request clearly refers back to it. Leave unmentioned restrictions null; "
                "do not inherit a prior search filter."
            )
        if intent in {CustomerIntentKind.DISH_DETAIL, CustomerIntentKind.DISH_AVAILABILITY}:
            return "Extract only a dish reference or prior result index."
        return (
            "Extract only the required cart-item reference and requested quantity when applicable."
        )
