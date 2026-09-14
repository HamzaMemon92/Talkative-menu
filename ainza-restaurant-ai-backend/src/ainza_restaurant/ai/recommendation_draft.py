from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ainza_restaurant.ai.category_roles import MenuCategoryRole, category_role
from ainza_restaurant.customer_menu.schemas import CustomerDishRead, CustomerMenuRead
from ainza_restaurant.domain.enums import DietaryClassification, SpiceLevel


class RecommendationDraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dish_id: UUID
    name: str
    price: Decimal
    category_name: str = ""
    category_role: MenuCategoryRole = MenuCategoryRole.MAIN
    dietary_classification: DietaryClassification = DietaryClassification.UNKNOWN
    spice_level: SpiceLevel = SpiceLevel.UNKNOWN


class RecommendationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: UUID = Field(default_factory=uuid.uuid4)
    outlet_id: UUID
    dining_session_id: UUID
    items: list[RecommendationDraftItem] = Field(default_factory=list)
    total: Decimal = Field(default=Decimal("0.00"))
    currency_code: str = "INR"
    party_size: int | None = None
    budget_max: Decimal | None = None
    dietary_preference: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=15))

    def is_expired(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        return current >= self.expires_at

    def recalculate_total(self) -> None:
        self.total = sum((item.price for item in self.items), Decimal("0.00"))


def _extract_dish_price(dish: Any) -> Decimal:
    if hasattr(dish, "pricing") and dish.pricing:
        return dish.pricing.effective_price or dish.pricing.catalog_price or Decimal("0.00")
    if hasattr(dish, "base_price") and dish.base_price is not None:
        return Decimal(str(dish.base_price))
    if hasattr(dish, "price") and dish.price is not None:
        return Decimal(str(dish.price))
    return Decimal("0.00")


class RecommendationDraftService:
    """Ephemeral in-memory draft manager for conversational recommendation revisions."""

    @classmethod
    def create_draft(
        cls,
        *,
        outlet_id: UUID,
        dining_session_id: UUID,
        recommended_dishes: list[Any],
        currency_code: str = "INR",
        party_size: int | None = None,
        budget_max: Decimal | None = None,
        ttl_minutes: int = 15,
        now: datetime | None = None,
    ) -> RecommendationDraft:
        current_time = now or datetime.now(UTC)
        items: list[RecommendationDraftItem] = []
        for dish in recommended_dishes:
            price = _extract_dish_price(dish)
            items.append(
                RecommendationDraftItem(
                    dish_id=dish.id,
                    name=dish.name,
                    price=price,
                    category_name="",
                    category_role=MenuCategoryRole.MAIN,
                    dietary_classification=dish.dietary_classification,
                    spice_level=dish.spice_level,
                )
            )
        draft = RecommendationDraft(
            outlet_id=outlet_id,
            dining_session_id=dining_session_id,
            items=items,
            currency_code=currency_code,
            party_size=party_size,
            budget_max=budget_max,
            created_at=current_time,
            expires_at=current_time + timedelta(minutes=ttl_minutes),
        )
        draft.recalculate_total()
        return draft

    @classmethod
    def revise(
        cls,
        draft: RecommendationDraft,
        menu: CustomerMenuRead,
        *,
        replace_target: str | None = None,
        replacement_query: str | None = None,
        remove_target: str | None = None,
        add_query: str | None = None,
        make_cheaper: bool = False,
        dietary_filter: DietaryClassification | None = None,
        is_jain: bool = False,
        is_less_spicy: bool = False,
        now: datetime | None = None,
    ) -> tuple[RecommendationDraft, str]:
        """Revise the draft against authoritative menu data.

        Returns: (revised_draft, message_summary)
        """
        if draft.is_expired(now):
            return draft, "Recommendation draft has expired. Please ask for a new recommendation."

        all_dishes = [
            dish
            for cat in menu.categories
            for dish in cat.dishes
            if getattr(dish, "available", True)
        ]
        category_map = {cat.id: cat.name for cat in menu.categories}

        # 1. Handle REMOVE target
        if remove_target:
            idx = cls._resolve_item_index(draft.items, remove_target)
            if idx is not None:
                removed = draft.items.pop(idx)
                draft.recalculate_total()
                return (
                    draft,
                    f"Removed {removed.name}. Revised total: {draft.currency_code} {draft.total}.",
                )

        # 2. Handle ADD query
        if add_query:
            match = cls._find_menu_match(all_dishes, add_query)
            if match is not None:
                price = _extract_dish_price(match)
                cat_name = category_map.get(match.category_id, "")
                role = category_role(cat_name)
                draft.items.append(
                    RecommendationDraftItem(
                        dish_id=match.id,
                        name=match.name,
                        price=price,
                        category_name=cat_name,
                        category_role=role,
                        dietary_classification=match.dietary_classification,
                        spice_level=match.spice_level,
                    )
                )
                draft.recalculate_total()
                return (
                    draft,
                    f"Added {match.name}. Revised total: {draft.currency_code} {draft.total}.",
                )
            return draft, f"Could not find available dish matching '{add_query}'."

        # 3. Handle MAKE CHEAPER
        if make_cheaper:
            if not draft.items:
                return draft, "No items in recommendation to make cheaper."
            # Find the most expensive item
            sorted_items = sorted(enumerate(draft.items), key=lambda x: x[1].price, reverse=True)
            target_idx, target_item = sorted_items[0]
            # Look for an available alternative in menu that is cheaper than target_item
            cheaper_candidates = [
                d
                for d in all_dishes
                if d.id != target_item.dish_id and _extract_dish_price(d) < target_item.price
            ]
            if cheaper_candidates:
                cheaper_candidates.sort(key=lambda d: _extract_dish_price(d))
                replacement = cheaper_candidates[0]
                price = _extract_dish_price(replacement)
                cat_name = category_map.get(replacement.category_id, "")
                draft.items[target_idx] = RecommendationDraftItem(
                    dish_id=replacement.id,
                    name=replacement.name,
                    price=price,
                    category_name=cat_name,
                    category_role=category_role(cat_name),
                    dietary_classification=replacement.dietary_classification,
                    spice_level=replacement.spice_level,
                )
                draft.recalculate_total()
                return (
                    draft,
                    f"Replaced {target_item.name} with cheaper option {replacement.name} "
                    f"({draft.currency_code} {price}). "
                    f"Revised total: {draft.currency_code} {draft.total}.",
                )
            return draft, "No cheaper available alternative found."

        # 4. Handle DIETARY / JAIN switch
        if is_jain:
            changed = []
            for i, item in enumerate(draft.items):
                jain_candidate = next(
                    (
                        d
                        for d in all_dishes
                        if d.jain_status.value == "available" and d.id != item.dish_id
                    ),
                    None,
                )
                if jain_candidate is not None:
                    price = _extract_dish_price(jain_candidate)
                    draft.items[i] = RecommendationDraftItem(
                        dish_id=jain_candidate.id,
                        name=jain_candidate.name,
                        price=price,
                        category_name=category_map.get(jain_candidate.category_id, ""),
                        category_role=category_role(
                            category_map.get(jain_candidate.category_id, "")
                        ),
                        dietary_classification=jain_candidate.dietary_classification,
                        spice_level=jain_candidate.spice_level,
                    )
                    changed.append(f"{item.name} -> {jain_candidate.name}")
            if changed:
                draft.recalculate_total()
                return (
                    draft,
                    f"Updated items for Jain preferences: {', '.join(changed)}. "
                    f"Revised total: {draft.currency_code} {draft.total}.",
                )

        if dietary_filter == DietaryClassification.VEGETARIAN:
            changed = []
            for i, item in enumerate(draft.items):
                if item.dietary_classification != DietaryClassification.VEGETARIAN:
                    veg_candidate = next(
                        (
                            d
                            for d in all_dishes
                            if d.dietary_classification == DietaryClassification.VEGETARIAN
                            and d.id != item.dish_id
                        ),
                        None,
                    )
                    if veg_candidate is not None:
                        price = _extract_dish_price(veg_candidate)
                        draft.items[i] = RecommendationDraftItem(
                            dish_id=veg_candidate.id,
                            name=veg_candidate.name,
                            price=price,
                            category_name=category_map.get(veg_candidate.category_id, ""),
                            category_role=category_role(
                                category_map.get(veg_candidate.category_id, "")
                            ),
                            dietary_classification=veg_candidate.dietary_classification,
                            spice_level=veg_candidate.spice_level,
                        )
                        changed.append(f"{item.name} -> {veg_candidate.name}")
            if changed:
                draft.recalculate_total()
                return (
                    draft,
                    f"Updated to vegetarian: {', '.join(changed)}. "
                    f"Revised total: {draft.currency_code} {draft.total}.",
                )

        # 5. Handle REPLACE target
        if replace_target:
            idx = cls._resolve_item_index(draft.items, replace_target)
            if idx is None:
                idx = 0  # default to first if unspecified
            old_item = draft.items[idx]

            replace_dish: CustomerDishRead | None = None
            if replacement_query:
                replace_dish = cls._find_menu_match(all_dishes, replacement_query)
            else:
                # Find a different dish in same role or category
                existing_ids = {it.dish_id for it in draft.items}
                candidates = [d for d in all_dishes if d.id not in existing_ids]
                if candidates:
                    replace_dish = candidates[0]

            if replace_dish is not None:
                price = _extract_dish_price(replace_dish)
                cat_name = category_map.get(replace_dish.category_id, "")
                draft.items[idx] = RecommendationDraftItem(
                    dish_id=replace_dish.id,
                    name=replace_dish.name,
                    price=price,
                    category_name=cat_name,
                    category_role=category_role(cat_name),
                    dietary_classification=replace_dish.dietary_classification,
                    spice_level=replace_dish.spice_level,
                )
                draft.recalculate_total()
                return (
                    draft,
                    f"Replaced {old_item.name} with {replace_dish.name}. "
                    f"Revised total: {draft.currency_code} {draft.total}.",
                )
            return draft, f"Could not find an available replacement for {old_item.name}."

        return draft, f"Current recommendation total is {draft.currency_code} {draft.total}."

    @classmethod
    def _resolve_item_index(cls, items: list[RecommendationDraftItem], target: str) -> int | None:
        t = target.strip().lower()
        # Ordinal checks
        ordinal_map = {
            "1": 0,
            "first": 0,
            "1st": 0,
            "2": 1,
            "second": 1,
            "2nd": 1,
            "3": 2,
            "third": 2,
            "3rd": 2,
            "4": 3,
            "fourth": 3,
            "4th": 3,
            "5": 4,
            "fifth": 4,
            "5th": 4,
            "last": len(items) - 1,
        }
        for word, idx in ordinal_map.items():
            if word in t and 0 <= idx < len(items):
                return idx

        # Role checks (e.g. "drink", "dessert")
        for i, item in enumerate(items):
            if item.category_role.value.lower() in t or item.category_name.lower() in t:
                return i

        # Name match
        for i, item in enumerate(items):
            if item.name.lower() in t or t in item.name.lower():
                return i
        return None

    @classmethod
    def _find_menu_match(
        cls, dishes: list[CustomerDishRead], query: str
    ) -> CustomerDishRead | None:
        q = query.strip().lower()
        # Exact match
        for d in dishes:
            if d.name.lower() == q:
                return d
        # Substring match
        for d in dishes:
            if q in d.name.lower():
                return d
        return None
