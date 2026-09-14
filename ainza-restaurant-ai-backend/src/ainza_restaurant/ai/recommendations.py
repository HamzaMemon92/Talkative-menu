from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.ai.category_roles import MenuCategoryRole, category_role
from ainza_restaurant.ai.customer_intent import MealRecommendationGoal
from ainza_restaurant.customer_menu.schemas import CustomerDishRead, CustomerMenuFilters
from ainza_restaurant.customer_menu.service import CustomerMenuService


class MealRecommendationService:
    """Builds a bounded, read-only meal suggestion from customer-visible menu data."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def recommend(
        self,
        outlet_id: UUID,
        *,
        party_size: int | None,
        budget_min: Decimal | None,
        budget_max: Decimal | None,
        filters: CustomerMenuFilters | None,
        goal: MealRecommendationGoal,
        excluded_dish_names: list[str] | None = None,
    ) -> dict[str, Any]:
        explicit = (filters or CustomerMenuFilters()).model_copy(update={"available": True})
        menu = await CustomerMenuService(self.session).get_menu(outlet_id, filters=explicit)
        candidates = [dish for category in menu.categories for dish in category.dishes]
        if excluded_dish_names:
            excluded_lower = {name.casefold() for name in excluded_dish_names}
            candidates = [d for d in candidates if d.name.casefold() not in excluded_lower]
        priced = [dish for dish in candidates if self._price(dish) is not None]
        target_count = min(party_size or 1, len(priced))
        category_names = {category.id: category.name for category in menu.categories}
        chosen = self._choose(priced, category_names, target_count, budget_min, budget_max, goal)
        currency = menu.outlet.currency_code
        total = sum((self._price(dish) or Decimal("0")) for dish in chosen)
        return {
            "party_size": party_size,
            "budget_min": budget_min,
            "currency_code": currency,
            "budget_max": budget_max,
            "recommendation_goal": goal,
            "total": total,
            "items": [
                {"dish_id": dish.id, "name": dish.name, "price": self._price(dish)}
                for dish in chosen
            ],
            "no_plan": not chosen,
        }

    def _choose(
        self,
        dishes: list[CustomerDishRead],
        category_names: dict[UUID, str],
        target_count: int,
        budget_min: Decimal | None,
        budget_max: Decimal | None,
        goal: MealRecommendationGoal,
    ) -> list[CustomerDishRead]:
        by_role: dict[MenuCategoryRole, list[CustomerDishRead]] = {}
        for dish in dishes:
            role = category_role(category_names.get(dish.category_id, ""))
            by_role.setdefault(role, []).append(dish)
        for values in by_role.values():
            values.sort(key=self._catalog_key if budget_max is None else self._budget_key)
        roles = self._role_order(goal, by_role)
        selected: list[CustomerDishRead] = []
        total = Decimal("0")
        # TODO: Keep this role-first pass bounded by target_count without inventing
        # serving-size claims; party size should guide breadth in a later change.
        for role in roles:
            candidate = self._first_that_fits(by_role.get(role, []), total, budget_max)
            if candidate is not None:
                selected.append(candidate)
                total += self._price(candidate) or Decimal("0")
        remaining = [
            dish for role in roles for dish in by_role.get(role, []) if dish not in selected
        ]
        for dish in remaining:
            if len(selected) >= target_count and (budget_min is None or total >= budget_min):
                break
            price = self._price(dish) or Decimal("0")
            if budget_max is None or total + price <= budget_max:
                selected.append(dish)
                total += price
        if goal in {
            MealRecommendationGoal.GENERAL_RECOMMENDATION,
            MealRecommendationGoal.BALANCED_MEAL,
            MealRecommendationGoal.FULL_MEAL,
        } and by_role.get(MenuCategoryRole.MAIN) and not any(
            category_role(category_names.get(dish.category_id, "")) == MenuCategoryRole.MAIN
            for dish in selected
        ):
            # Broad meals must not degrade into accompaniment-only suggestions.
            return []
        return selected

    @staticmethod
    def _role_order(
        goal: MealRecommendationGoal, by_role: dict[MenuCategoryRole, list[CustomerDishRead]]
    ) -> list[MenuCategoryRole]:
        if goal == MealRecommendationGoal.DRINKS:
            return [MenuCategoryRole.DRINK]
        if goal == MealRecommendationGoal.DESSERT:
            return [MenuCategoryRole.DESSERT]
        if goal == MealRecommendationGoal.SNACK:
            return [
                MenuCategoryRole.SNACK,
                MenuCategoryRole.STARTER,
                MenuCategoryRole.OTHER,
            ]
        if goal == MealRecommendationGoal.LIGHT_MEAL:
            return [
                MenuCategoryRole.MAIN,
                MenuCategoryRole.STARTER,
                MenuCategoryRole.ACCOMPANIMENT,
                MenuCategoryRole.OTHER,
                MenuCategoryRole.DRINK,
            ]
        normal = [
            MenuCategoryRole.STARTER,
            MenuCategoryRole.MAIN,
            MenuCategoryRole.ACCOMPANIMENT,
            MenuCategoryRole.DESSERT,
            MenuCategoryRole.DRINK,
            MenuCategoryRole.OTHER,
        ]
        return [role for role in normal if role in by_role]

    def _first_that_fits(
        self, dishes: list[CustomerDishRead], total: Decimal, budget_max: Decimal | None
    ) -> CustomerDishRead | None:
        return next(
            (
                dish
                for dish in dishes
                if budget_max is None or total + (self._price(dish) or Decimal("0")) <= budget_max
            ),
            None,
        )

    def _catalog_key(self, dish: CustomerDishRead) -> tuple[bool, int, str, str]:
        return (not dish.is_featured, dish.display_order, dish.name, str(dish.id))

    def _budget_key(self, dish: CustomerDishRead) -> tuple[Decimal, bool, int, str, str]:
        return (
            self._price(dish) or Decimal("0"),
            not dish.is_featured,
            dish.display_order,
            dish.name,
            str(dish.id),
        )

    @staticmethod
    def _price(dish: CustomerDishRead) -> Decimal | None:
        return dish.pricing.effective_price or dish.pricing.starting_price
