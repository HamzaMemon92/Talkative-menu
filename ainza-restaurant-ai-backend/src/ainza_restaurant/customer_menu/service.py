from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ainza_restaurant.availability.models import (
    DishAvailabilityOverride,
    IngredientAvailabilityOverride,
)
from ainza_restaurant.customer_menu.schemas import (
    CustomerAvailabilityRead,
    CustomerCategoryRead,
    CustomerComboItemRead,
    CustomerCuisineRead,
    CustomerDishRead,
    CustomerFoodPolicyRead,
    CustomerImageRead,
    CustomerIngredientRead,
    CustomerMenuFilters,
    CustomerMenuRead,
    CustomerMenuSummaryRead,
    CustomerModifierGroupRead,
    CustomerModifierOptionRead,
    CustomerOfferRead,
    CustomerOfferRefRead,
    CustomerOutletRead,
    CustomerPricingRead,
    CustomerRestaurantRead,
    CustomerVariantRead,
)
from ainza_restaurant.domain.enums import (
    AlcoholPolicy,
    HalalCertificationStatus,
    HalalPolicy,
    ImageApprovalStatus,
    MenuStatus,
    MerchandisingStatus,
    PorkPolicy,
    ReviewStatus,
)
from ainza_restaurant.menu.models import (
    Category,
    Cuisine,
    Dish,
    DishCuisine,
    DishIngredient,
    DishVariant,
    Menu,
    ModifierGroup,
)
from ainza_restaurant.merchandising.models import (
    FeaturedDish,
    Offer,
    OfferCategoryScope,
    OfferComboItem,
    OfferDishScope,
    TodaysSpecial,
)
from ainza_restaurant.restaurants.models import RestaurantOutlet


class CustomerMenuNotFound(LookupError):
    code = "customer_menu_not_available"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class CustomerMenuConflict(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_customer_menu_filter",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class _AvailabilityState:
    available: bool


@dataclass(frozen=True)
class _SpecialState:
    special: TodaysSpecial


MONEY = Decimal("0.01")


class CustomerMenuService:
    def __init__(self, session: AsyncSession, *, now: Callable[[], datetime] | None = None) -> None:
        self.session = session
        self._now = now or (lambda: datetime.now(UTC))

    def now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    async def get_menu(
        self, outlet_id: UUID, *, filters: CustomerMenuFilters | None = None
    ) -> CustomerMenuRead:
        now = self.now()
        outlet = await self._outlet(outlet_id)
        menu = await self._published_menu(outlet)
        categories = self._public_categories(menu)
        dishes = self._public_dishes(menu, {category.id for category in categories})
        dish_ids = [dish.id for dish in dishes]
        availability = await self._availability(dishes, now)
        specials = await self._specials(outlet.id, dish_ids, now)
        featured = await self._featured(outlet.id, dish_ids, now)
        dish_reads = [
            self._dish_read(
                dish,
                outlet.currency_code,
                availability.get(dish.id, _AvailabilityState(True)),
                specials,
                featured,
            )
            for dish in sorted(
                dishes, key=lambda item: (item.display_order, item.name, str(item.id))
            )
        ]
        filtered = self._apply_filters(dish_reads, filters or CustomerMenuFilters())
        dishes_by_category: dict[UUID, list[CustomerDishRead]] = {}
        for dish in filtered:
            dishes_by_category.setdefault(dish.category_id, []).append(dish)
        featured_reads = sorted(
            [dish for dish in filtered if dish.is_featured],
            key=lambda item: (item.featured_display_order or 0, item.name, str(item.id)),
        )
        return CustomerMenuRead(
            restaurant=CustomerRestaurantRead(
                id=outlet.restaurant.id,
                name=outlet.restaurant.name,
                slug=outlet.restaurant.slug,
            ),
            outlet=CustomerOutletRead(
                id=outlet.id,
                restaurant_id=outlet.restaurant_id,
                name=outlet.name,
                city=outlet.city,
                state=outlet.state,
                country=outlet.country,
                timezone=outlet.timezone,
                currency_code=outlet.currency_code,
            ),
            menu=CustomerMenuSummaryRead(
                id=menu.id,
                name=menu.name,
                description=menu.description,
                published_at=menu.published_at,
                prices_include_tax=(
                    outlet.tax_profile.prices_include_tax if outlet.tax_profile else None
                ),
            ),
            food_policy=self._food_policy(outlet),
            featured_dishes=featured_reads,
            categories=[
                CustomerCategoryRead(
                    id=category.id,
                    name=category.name,
                    description=category.description,
                    display_order=category.display_order,
                    dishes=dishes_by_category.get(category.id, []),
                )
                for category in categories
                if category.id in dishes_by_category
            ],
            offers=await self._offers(outlet.id, now),
            generated_at=now,
        )

    async def get_dish(self, outlet_id: UUID, dish_id: UUID) -> CustomerDishRead:
        menu = await self.get_menu(outlet_id)
        for category in menu.categories:
            for dish in category.dishes:
                if dish.id == dish_id:
                    return dish
        wrong_outlet = await self._dish_exists_elsewhere(dish_id)
        code = "customer_menu_dish_wrong_outlet" if wrong_outlet else "customer_menu_dish_not_found"
        raise CustomerMenuNotFound("customer menu dish not found", code=code)

    async def search(
        self,
        outlet_id: UUID,
        *,
        q: str | None = None,
        filters: CustomerMenuFilters | None = None,
    ) -> list[CustomerDishRead]:
        query = " ".join(q.casefold().split()) if q is not None else None
        if query == "":
            raise CustomerMenuConflict("q must not be blank")
        if query is None and filters is None:
            raise CustomerMenuConflict("q or filters is required")
        menu = await self.get_menu(outlet_id, filters=filters)
        dishes = [dish for category in menu.categories for dish in category.dishes]
        if query is None:
            return sorted(dishes, key=lambda dish: (dish.display_order, dish.name, str(dish.id)))
        matches = [dish for dish in dishes if self._matches(dish, query)]
        if not matches:
            matches = [dish for dish in dishes if self._fuzzy_matches(dish, query)]
        return sorted(matches, key=lambda dish: self._search_key(dish, query))

    async def _outlet(self, outlet_id: UUID) -> RestaurantOutlet:
        result = await self.session.execute(
            select(RestaurantOutlet)
            .options(
                selectinload(RestaurantOutlet.restaurant),
                selectinload(RestaurantOutlet.tax_profile),
                selectinload(RestaurantOutlet.food_policy),
            )
            .where(RestaurantOutlet.id == outlet_id)
        )
        outlet = result.scalar_one_or_none()
        if outlet is None:
            raise CustomerMenuNotFound("outlet not found", code="customer_menu_outlet_not_found")
        restaurant_status = getattr(outlet.restaurant.status, "value", outlet.restaurant.status)
        if not outlet.is_active or restaurant_status != "active":
            raise CustomerMenuNotFound("customer menu is not available")
        return outlet

    async def _published_menu(self, outlet: RestaurantOutlet) -> Menu:
        result = await self.session.execute(
            select(Menu)
            .options(
                selectinload(Menu.categories),
                selectinload(Menu.dishes).selectinload(Dish.category),
                selectinload(Menu.dishes).selectinload(Dish.variants),
                selectinload(Menu.dishes)
                .selectinload(Dish.ingredients)
                .selectinload(DishIngredient.ingredient),
                selectinload(Menu.dishes).selectinload(Dish.badges),
                selectinload(Menu.dishes).selectinload(Dish.images),
                selectinload(Menu.dishes)
                .selectinload(Dish.modifier_groups)
                .selectinload(ModifierGroup.options),
                selectinload(Menu.dishes)
                .selectinload(Dish.cuisines)
                .selectinload(DishCuisine.cuisine),
            )
            .where(Menu.outlet_id == outlet.id, Menu.status == MenuStatus.PUBLISHED)
        )
        menu = result.scalar_one_or_none()
        if menu is None:
            raise CustomerMenuNotFound("published customer menu not found")
        return menu

    def _public_categories(self, menu: Menu) -> list[Category]:
        return sorted(
            [category for category in menu.categories if category.is_active],
            key=lambda item: (item.display_order, item.name, str(item.id)),
        )

    def _public_dishes(self, menu: Menu, active_category_ids: set[UUID]) -> list[Dish]:
        return [
            dish
            for dish in menu.dishes
            if dish.is_active
            and dish.category_id in active_category_ids
            and dish.review_status in (ReviewStatus.CONFIRMED, ReviewStatus.APPROVED)
        ]

    async def _availability(
        self, dishes: list[Dish], now: datetime
    ) -> dict[UUID, _AvailabilityState]:
        dish_ids = [dish.id for dish in dishes]
        if not dish_ids:
            return {}
        unavailable = set(await self._direct_blocked_dish_ids(dish_ids, now))
        ingredient_result = await self.session.execute(
            select(DishIngredient.dish_id)
            .join(
                IngredientAvailabilityOverride,
                DishIngredient.ingredient_id == IngredientAvailabilityOverride.ingredient_id,
            )
            .where(
                DishIngredient.dish_id.in_(dish_ids),
                DishIngredient.is_required_for_availability.is_(True),
                IngredientAvailabilityOverride.revoked_at.is_(None),
                or_(
                    IngredientAvailabilityOverride.expires_at.is_(None),
                    IngredientAvailabilityOverride.expires_at > now,
                ),
            )
        )
        unavailable.update(ingredient_result.scalars())
        return {dish_id: _AvailabilityState(dish_id not in unavailable) for dish_id in dish_ids}

    async def _direct_blocked_dish_ids(self, dish_ids: list[UUID], now: datetime) -> list[UUID]:
        result = await self.session.execute(
            select(DishAvailabilityOverride.dish_id).where(
                DishAvailabilityOverride.dish_id.in_(dish_ids),
                DishAvailabilityOverride.revoked_at.is_(None),
                or_(
                    DishAvailabilityOverride.expires_at.is_(None),
                    DishAvailabilityOverride.expires_at > now,
                ),
            )
        )
        return list(result.scalars())

    async def _specials(
        self, outlet_id: UUID, dish_ids: list[UUID], now: datetime
    ) -> dict[tuple[UUID, UUID | None], _SpecialState]:
        if not dish_ids:
            return {}
        result = await self.session.execute(
            select(TodaysSpecial)
            .where(
                TodaysSpecial.outlet_id == outlet_id,
                TodaysSpecial.dish_id.in_(dish_ids),
                TodaysSpecial.status == MerchandisingStatus.ACTIVE,
                TodaysSpecial.starts_at <= now,
                TodaysSpecial.ends_at > now,
            )
            .order_by(TodaysSpecial.created_at.desc())
        )
        values: dict[tuple[UUID, UUID | None], _SpecialState] = {}
        for special in result.scalars():
            values.setdefault((special.dish_id, special.variant_id), _SpecialState(special))
        return values

    async def _featured(
        self, outlet_id: UUID, dish_ids: list[UUID], now: datetime
    ) -> dict[UUID, FeaturedDish]:
        if not dish_ids:
            return {}
        result = await self.session.execute(
            select(FeaturedDish)
            .where(
                FeaturedDish.outlet_id == outlet_id,
                FeaturedDish.dish_id.in_(dish_ids),
                FeaturedDish.status == MerchandisingStatus.ACTIVE,
                FeaturedDish.starts_at <= now,
                or_(FeaturedDish.ends_at.is_(None), FeaturedDish.ends_at > now),
            )
            .order_by(FeaturedDish.display_order, FeaturedDish.created_at)
        )
        values: dict[UUID, FeaturedDish] = {}
        for item in result.scalars():
            values.setdefault(item.dish_id, item)
        return values

    def _dish_read(
        self,
        dish: Dish,
        currency_code: str,
        availability: _AvailabilityState,
        specials: dict[tuple[UUID, UUID | None], _SpecialState],
        featured: dict[UUID, FeaturedDish],
    ) -> CustomerDishRead:
        active_variants = sorted(
            [variant for variant in dish.variants if variant.is_active],
            key=lambda item: (item.display_order, item.name, str(item.id)),
        )
        approved_images = sorted(
            [
                image
                for image in dish.images
                if image.approval_status == ImageApprovalStatus.APPROVED
                and image.review_status in (ReviewStatus.CONFIRMED, ReviewStatus.APPROVED)
            ],
            key=lambda item: (not item.is_primary, item.sort_order, str(item.id)),
        )
        image_reads = [self._image_read(image) for image in approved_images]
        dish_images = [image for image in image_reads if image.variant_id is None]
        dish_special = specials.get((dish.id, None))
        variant_reads = [
            self._variant_read(variant, image_reads, specials.get((dish.id, variant.id)))
            for variant in active_variants
        ]
        base_price = money(dish.base_price) if dish.base_price is not None else None
        special_price = (
            money(dish_special.special.special_price)
            if dish_special is not None and dish_special.special.special_price is not None
            else None
        )
        effective_price = special_price or base_price
        starting_price = (
            min((variant.effective_price for variant in variant_reads), default=None)
            if variant_reads
            else None
        )
        featured_item = featured.get(dish.id)
        return CustomerDishRead(
            id=dish.id,
            menu_id=dish.menu_id,
            category_id=dish.category_id,
            name=dish.name,
            description=dish.description,
            item_type=dish.item_type,
            dietary_classification=dish.dietary_classification,
            vegan_status=dish.vegan_status,
            jain_status=dish.jain_status,
            halal_status=dish.halal_status,
            spice_level=dish.spice_level,
            ingredient_description=dish.ingredient_description,
            allergen_information_status=dish.allergen_information_status,
            allergen_notes=dish.allergen_notes,
            badges=sorted([badge.badge for badge in dish.badges], key=lambda item: item.value),
            is_todays_special=dish_special is not None
            or any(variant.is_todays_special for variant in variant_reads),
            special_display_note=dish_special.special.display_note if dish_special else None,
            special_ends_at=dish_special.special.ends_at if dish_special else None,
            is_featured=featured_item is not None,
            featured_display_order=featured_item.display_order if featured_item else None,
            available=availability.available,
            availability=CustomerAvailabilityRead(
                available=availability.available,
                status="available" if availability.available else "sold_out",
                message=None if availability.available else "Currently unavailable",
            ),
            pricing=CustomerPricingRead(
                currency_code=currency_code,
                catalog_price=base_price,
                effective_price=effective_price,
                has_special_price=special_price is not None,
                special_price=special_price,
                starting_price=starting_price,
            ),
            variants=variant_reads,
            primary_image=next((image for image in dish_images if image.is_primary), None),
            images=dish_images,
            modifiers=self._modifiers(dish),
            ingredients=self._ingredients(dish),
            cuisines=self._cuisines(dish),
            display_order=dish.display_order,
        )

    def _variant_read(
        self,
        variant: DishVariant,
        images: list[CustomerImageRead],
        special: _SpecialState | None,
    ) -> CustomerVariantRead:
        variant_images = [image for image in images if image.variant_id == variant.id]
        special_price = (
            money(special.special.special_price)
            if special is not None and special.special.special_price is not None
            else None
        )
        catalog_price = money(variant.price)
        return CustomerVariantRead(
            id=variant.id,
            name=variant.name,
            catalog_price=catalog_price,
            effective_price=special_price or catalog_price,
            has_special_price=special_price is not None,
            special_price=special_price,
            is_todays_special=special is not None,
            special_ends_at=special.special.ends_at if special else None,
            display_order=variant.display_order,
            primary_image=next((image for image in variant_images if image.is_primary), None),
            images=variant_images,
        )

    def _image_read(self, image: Any) -> CustomerImageRead:
        return CustomerImageRead(
            id=image.id,
            variant_id=image.variant_id,
            storage_key=image.storage_key,
            source_url=image.source_url,
            alt_text=image.alt_text,
            mime_type=image.mime_type,
            width=image.width,
            height=image.height,
            sort_order=image.sort_order,
            is_primary=image.is_primary,
            approval_status=image.approval_status,
        )

    def _modifiers(self, dish: Dish) -> list[CustomerModifierGroupRead]:
        groups = sorted(
            [group for group in dish.modifier_groups if group.is_active],
            key=lambda item: (item.display_order, item.name, str(item.id)),
        )
        return [
            CustomerModifierGroupRead(
                id=group.id,
                name=group.name,
                is_required=group.is_required,
                min_selections=group.min_selections,
                max_selections=group.max_selections,
                display_order=group.display_order,
                options=[
                    CustomerModifierOptionRead(
                        id=option.id,
                        name=option.name,
                        price_delta=money(option.price_delta),
                        display_order=option.display_order,
                    )
                    for option in sorted(
                        [option for option in group.options if option.is_active],
                        key=lambda item: (item.display_order, item.name, str(item.id)),
                    )
                ],
            )
            for group in groups
        ]

    def _ingredients(self, dish: Dish) -> list[CustomerIngredientRead]:
        return [
            CustomerIngredientRead(id=link.ingredient.id, name=link.ingredient.name)
            for link in sorted(
                dish.ingredients,
                key=lambda item: (item.ingredient.name, str(item.ingredient_id)),
            )
            if link.ingredient.is_active
        ]

    def _cuisines(self, dish: Dish) -> list[CustomerCuisineRead]:
        values: list[Cuisine] = [link.cuisine for link in dish.cuisines if link.cuisine.is_active]
        return [
            CustomerCuisineRead(id=cuisine.id, name=cuisine.name)
            for cuisine in sorted(values, key=lambda item: (item.name, str(item.id)))
        ]

    def _food_policy(self, outlet: RestaurantOutlet) -> CustomerFoodPolicyRead:
        policy = outlet.food_policy
        if policy is None or not policy.information_confirmed:
            return CustomerFoodPolicyRead(
                information_confirmed=False,
                halal_policy=HalalPolicy.UNKNOWN,
                halal_certification_status=HalalCertificationStatus.UNKNOWN,
                pork_policy=PorkPolicy.UNKNOWN,
                alcohol_policy=AlcoholPolicy.UNKNOWN,
            )
        return CustomerFoodPolicyRead(
            information_confirmed=True,
            halal_policy=policy.halal_policy,
            halal_certification_status=policy.halal_certification_status,
            pork_policy=policy.pork_policy,
            alcohol_policy=policy.alcohol_policy,
        )

    async def _offers(self, outlet_id: UUID, now: datetime) -> list[CustomerOfferRead]:
        offers = list(
            (
                await self.session.execute(
                    select(Offer)
                    .where(
                        Offer.outlet_id == outlet_id,
                        Offer.status == MerchandisingStatus.ACTIVE,
                        Offer.starts_at <= now,
                        Offer.ends_at > now,
                    )
                    .order_by(Offer.created_at, Offer.name)
                )
            ).scalars()
        )
        if not offers:
            return []
        offer_ids = [offer.id for offer in offers]
        dish_scope = await self._offer_dish_scope(offer_ids)
        category_scope = await self._offer_category_scope(offer_ids)
        combos = await self._offer_combo_items(offer_ids)
        return [
            CustomerOfferRead(
                id=offer.id,
                name=offer.name,
                description=offer.description,
                offer_type=offer.offer_type,
                scope_type=offer.scope_type,
                minimum_subtotal=money(offer.minimum_subtotal)
                if offer.minimum_subtotal is not None
                else None,
                discount_value=money(offer.discount_value)
                if offer.discount_value is not None
                else None,
                maximum_discount=money(offer.maximum_discount)
                if offer.maximum_discount is not None
                else None,
                combo_price=money(offer.combo_price) if offer.combo_price is not None else None,
                starts_at=offer.starts_at,
                ends_at=offer.ends_at,
                dish_scope=dish_scope.get(offer.id, []),
                category_scope=category_scope.get(offer.id, []),
                combo_items=combos.get(offer.id, []),
            )
            for offer in offers
        ]

    async def _offer_dish_scope(
        self, offer_ids: list[UUID]
    ) -> dict[UUID, list[CustomerOfferRefRead]]:
        result = await self.session.execute(
            select(OfferDishScope.offer_id, Dish.id, Dish.name)
            .join(Dish, Dish.id == OfferDishScope.dish_id)
            .where(OfferDishScope.offer_id.in_(offer_ids))
            .order_by(Dish.name)
        )
        values: dict[UUID, list[CustomerOfferRefRead]] = {}
        for offer_id, dish_id, name in result.all():
            values.setdefault(offer_id, []).append(CustomerOfferRefRead(id=dish_id, name=name))
        return values

    async def _offer_category_scope(
        self, offer_ids: list[UUID]
    ) -> dict[UUID, list[CustomerOfferRefRead]]:
        result = await self.session.execute(
            select(OfferCategoryScope.offer_id, Category.id, Category.name)
            .join(Category, Category.id == OfferCategoryScope.category_id)
            .where(OfferCategoryScope.offer_id.in_(offer_ids))
            .order_by(Category.display_order, Category.name)
        )
        values: dict[UUID, list[CustomerOfferRefRead]] = {}
        for offer_id, category_id, name in result.all():
            values.setdefault(offer_id, []).append(CustomerOfferRefRead(id=category_id, name=name))
        return values

    async def _offer_combo_items(
        self, offer_ids: list[UUID]
    ) -> dict[UUID, list[CustomerComboItemRead]]:
        result = await self.session.execute(
            select(OfferComboItem, Dish, DishVariant)
            .join(Dish, Dish.id == OfferComboItem.dish_id)
            .outerjoin(DishVariant, DishVariant.id == OfferComboItem.variant_id)
            .where(OfferComboItem.offer_id.in_(offer_ids))
            .order_by(Dish.name, DishVariant.display_order)
        )
        values: dict[UUID, list[CustomerComboItemRead]] = {}
        for item, dish, variant in result.all():
            values.setdefault(item.offer_id, []).append(
                CustomerComboItemRead(
                    dish_id=dish.id,
                    dish_name=dish.name,
                    variant_id=variant.id if variant else None,
                    variant_name=variant.name if variant else None,
                    required_quantity=item.required_quantity,
                )
            )
        return values

    def _apply_filters(
        self, dishes: list[CustomerDishRead], filters: CustomerMenuFilters
    ) -> list[CustomerDishRead]:
        values = dishes
        if filters.category_id is not None:
            values = [dish for dish in values if dish.category_id == filters.category_id]
        if filters.cuisine_id is not None:
            values = [
                dish
                for dish in values
                if any(cuisine.id == filters.cuisine_id for cuisine in dish.cuisines)
            ]
        if filters.item_type is not None:
            values = [dish for dish in values if dish.item_type == filters.item_type]
        if filters.dietary_classification is not None:
            values = [
                dish
                for dish in values
                if dish.dietary_classification == filters.dietary_classification
            ]
        if filters.vegan_status is not None:
            values = [dish for dish in values if dish.vegan_status == filters.vegan_status]
        if filters.jain_status is not None:
            values = [dish for dish in values if dish.jain_status == filters.jain_status]
        if filters.halal_status is not None:
            values = [dish for dish in values if dish.halal_status == filters.halal_status]
        if filters.spice_level is not None:
            values = [dish for dish in values if dish.spice_level == filters.spice_level]
        if filters.available is not None:
            values = [dish for dish in values if dish.available is filters.available]
        if filters.is_featured is not None:
            values = [dish for dish in values if dish.is_featured is filters.is_featured]
        if filters.is_todays_special is not None:
            values = [
                dish for dish in values if dish.is_todays_special is filters.is_todays_special
            ]
        if filters.price_min is not None:
            values = [
                dish
                for dish in values
                if (price := self._search_price(dish)) is not None and price >= filters.price_min
            ]
        if filters.price_max is not None:
            values = [
                dish
                for dish in values
                if (price := self._search_price(dish)) is not None and price <= filters.price_max
            ]
        return values

    @staticmethod
    def _search_price(dish: CustomerDishRead) -> Decimal | None:
        return dish.pricing.effective_price or dish.pricing.starting_price

    def _matches(self, dish: CustomerDishRead, query: str) -> bool:
        fields = [
            dish.name,
            dish.description,
            dish.ingredient_description,
            *[cuisine.name for cuisine in dish.cuisines],
        ]
        return any(query in (field or "").casefold() for field in fields)

    def _fuzzy_matches(self, dish: CustomerDishRead, query: str) -> bool:
        candidates = [dish.name, *[cuisine.name for cuisine in dish.cuisines]]
        tokens = query.split()
        for candidate in candidates:
            normalized = " ".join(candidate.casefold().split())
            if SequenceMatcher(None, query, normalized).ratio() >= 0.82:
                return True
            if any(
                SequenceMatcher(None, token, value).ratio() >= 0.82
                for token in tokens
                for value in normalized.split()
            ):
                return True
        return False

    def _search_key(self, dish: CustomerDishRead, query: str) -> tuple[int, int, str, str]:
        name = dish.name.casefold()
        if name == query:
            rank = 0
        elif name.startswith(query):
            rank = 1
        elif query in name:
            rank = 2
        else:
            rank = 3
        return (rank, dish.display_order, dish.name, str(dish.id))

    async def _dish_exists_elsewhere(self, dish_id: UUID) -> bool:
        return (
            await self.session.execute(select(Dish.id).where(Dish.id == dish_id))
        ).scalar_one_or_none() is not None


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)
