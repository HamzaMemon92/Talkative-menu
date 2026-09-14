from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ainza_restaurant.domain.enums import (
    MenuStatus,
    ReviewStatus,
)
from ainza_restaurant.menu.models import (
    Category,
    Cuisine,
    Dish,
    DishBadge,
    DishCuisine,
    DishDietaryStatus,
    DishImage,
    DishIngredient,
    DishVariant,
    Ingredient,
    Menu,
    MenuCuisine,
    ModifierGroup,
    ModifierOption,
)
from ainza_restaurant.menu.schemas import (
    BadgeReplace,
    CategoryCreate,
    CategoryPatch,
    CuisineCreate,
    CuisinePatch,
    CuisineReplace,
    DietaryReplace,
    DishCreate,
    DishPatch,
    ImageCreate,
    ImagePatch,
    IngredientCreate,
    IngredientPatch,
    IngredientReplace,
    MenuCreate,
    MenuPatch,
    ModifierGroupCreate,
    ModifierGroupPatch,
    ModifierOptionCreate,
    ModifierOptionPatch,
    PublishRequest,
    VariantCreate,
    VariantPatch,
)
from ainza_restaurant.restaurants.domain import normalize_slug
from ainza_restaurant.restaurants.models import Restaurant, RestaurantOutlet


class MenuNotFound(LookupError):
    code = "not_found"


class MenuConflict(ValueError):
    def __init__(
        self, message: str, *, code: str = "conflict", details: dict[str, object] | None = None
    ):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class MenuCatalogService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _restaurant(self, restaurant_id: UUID) -> Restaurant:
        item = await self.session.get(Restaurant, restaurant_id)
        if item is None:
            raise MenuNotFound("restaurant not found")
        return item

    async def _outlet(self, outlet_id: UUID, restaurant_id: UUID | None = None) -> RestaurantOutlet:
        query = select(RestaurantOutlet).where(RestaurantOutlet.id == outlet_id)
        if restaurant_id is not None:
            query = query.where(RestaurantOutlet.restaurant_id == restaurant_id)
        item = (await self.session.execute(query)).scalar_one_or_none()
        if item is None:
            raise MenuNotFound("outlet not found")
        return item

    async def _menu(self, menu_id: UUID, *, eager: bool = False) -> Menu:
        query = select(Menu).where(Menu.id == menu_id)
        if eager:
            query = query.options(
                selectinload(Menu.categories),
                selectinload(Menu.dishes).selectinload(Dish.category),
                selectinload(Menu.dishes).selectinload(Dish.variants),
                selectinload(Menu.dishes)
                .selectinload(Dish.ingredients)
                .selectinload(DishIngredient.ingredient),
                selectinload(Menu.dishes)
                .selectinload(Dish.modifier_groups)
                .selectinload(ModifierGroup.options),
            )
        item = (await self.session.execute(query)).scalar_one_or_none()
        if item is None:
            raise MenuNotFound("menu not found")
        return item

    async def _dish(self, dish_id: UUID, *, eager: bool = True) -> Dish:
        query = select(Dish).where(Dish.id == dish_id)
        if eager:
            query = query.options(
                selectinload(Dish.variants),
                selectinload(Dish.ingredients).selectinload(DishIngredient.ingredient),
                selectinload(Dish.dietary_statuses),
                selectinload(Dish.badges),
                selectinload(Dish.images),
                selectinload(Dish.modifier_groups).selectinload(ModifierGroup.options),
            )
        item = (await self.session.execute(query)).scalar_one_or_none()
        if item is None:
            raise MenuNotFound("dish not found")
        return item

    @staticmethod
    def _editable(menu: Menu) -> None:
        if menu.status == MenuStatus.PUBLISHED:
            raise MenuConflict("published menus cannot be changed", code="menu_published")

    async def create_menu(self, restaurant_id: UUID, data: MenuCreate) -> Menu:
        restaurant = await self._restaurant(restaurant_id)
        outlet = None
        if data.outlet_id is not None:
            outlet = await self._outlet(data.outlet_id, restaurant_id)
        menu = Menu(
            restaurant_id=restaurant.id,
            outlet_id=outlet.id if outlet else None,
            name=data.name,
            description=data.description,
        )
        self.session.add(menu)
        await self.session.commit()
        await self.session.refresh(menu)
        return menu

    async def list_menus(self, restaurant_id: UUID, outlet_id: UUID | None = None) -> list[Menu]:
        await self._restaurant(restaurant_id)
        query = select(Menu).where(Menu.restaurant_id == restaurant_id)
        if outlet_id is not None:
            query = query.where(Menu.outlet_id == outlet_id)
        result = await self.session.execute(query.order_by(Menu.name, Menu.id))
        return list(result.scalars())

    async def get_menu(self, menu_id: UUID) -> Menu:
        return await self._menu(menu_id)

    async def update_menu(self, menu_id: UUID, data: MenuPatch) -> Menu:
        menu = await self._menu(menu_id)
        self._editable(menu)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(menu, key, value)
        await self.session.commit()
        await self.session.refresh(menu)
        return menu

    async def create_category(self, menu_id: UUID, data: CategoryCreate) -> Category:
        menu = await self._menu(menu_id)
        self._editable(menu)
        slug = normalize_slug(data.slug or data.name)
        category = Category(
            menu_id=menu_id,
            name=data.name,
            slug=slug,
            description=data.description,
            display_order=data.display_order,
            sort_order=data.display_order,
            is_active=data.is_active,
        )
        self.session.add(category)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise MenuConflict(
                "category slug is already in use", code="duplicate_category"
            ) from exc
        await self.session.refresh(category)
        return category

    async def list_categories(self, menu_id: UUID) -> list[Category]:
        await self._menu(menu_id)
        result = await self.session.execute(
            select(Category)
            .where(Category.menu_id == menu_id)
            .order_by(Category.display_order, Category.name)
        )
        return list(result.scalars())

    async def get_category(self, category_id: UUID) -> Category:
        item = await self.session.get(Category, category_id)
        if item is None:
            raise MenuNotFound("category not found")
        return item

    async def update_category(self, category_id: UUID, data: CategoryPatch) -> Category:
        category = await self.get_category(category_id)
        menu = await self._menu(category.menu_id)
        self._editable(menu)
        values = data.model_dump(exclude_unset=True)
        if "slug" in values and values["slug"] is not None:
            values["slug"] = normalize_slug(values["slug"])
        if "display_order" in values:
            values["sort_order"] = values["display_order"]
        for key, value in values.items():
            if hasattr(category, key):
                setattr(category, key, value)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise MenuConflict(
                "category slug is already in use", code="duplicate_category"
            ) from exc
        await self.session.refresh(category)
        return category

    async def create_cuisine(
        self, restaurant_id: UUID, data: CuisineCreate, outlet_id: UUID | None = None
    ) -> Cuisine:
        await self._restaurant(restaurant_id)
        if outlet_id is not None:
            await self._outlet(outlet_id, restaurant_id)
        slug = normalize_slug(data.slug or data.name)
        cuisine = Cuisine(
            restaurant_id=restaurant_id,
            outlet_id=outlet_id,
            name=data.name,
            slug=slug,
            normalized_slug=slug,
            is_active=data.is_active,
        )
        self.session.add(cuisine)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise MenuConflict("cuisine slug is already in use", code="duplicate_cuisine") from exc
        await self.session.refresh(cuisine)
        return cuisine

    async def list_cuisines(
        self, restaurant_id: UUID, outlet_id: UUID | None = None
    ) -> list[Cuisine]:
        await self._restaurant(restaurant_id)
        query = select(Cuisine).where(Cuisine.restaurant_id == restaurant_id)
        if outlet_id is not None:
            query = query.where(Cuisine.outlet_id == outlet_id)
        result = await self.session.execute(query.order_by(Cuisine.name))
        return list(result.scalars())

    async def get_cuisine(self, cuisine_id: UUID) -> Cuisine:
        item = await self.session.get(Cuisine, cuisine_id)
        if item is None:
            raise MenuNotFound("cuisine not found")
        return item

    async def update_cuisine(self, cuisine_id: UUID, data: CuisinePatch) -> Cuisine:
        item = await self.get_cuisine(cuisine_id)
        values = data.model_dump(exclude_unset=True)
        if values.get("slug") is not None:
            values["slug"] = normalize_slug(values["slug"])
            values["normalized_slug"] = values["slug"]
        elif values.get("name") is not None:
            values["slug"] = normalize_slug(values["name"])
            values["normalized_slug"] = values["slug"]
        for key, value in values.items():
            setattr(item, key, value)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise MenuConflict("cuisine slug is already in use", code="duplicate_cuisine") from exc
        await self.session.refresh(item)
        return item

    async def create_ingredient(
        self, restaurant_id: UUID, data: IngredientCreate, outlet_id: UUID | None = None
    ) -> Ingredient:
        await self._restaurant(restaurant_id)
        if outlet_id is not None:
            await self._outlet(outlet_id, restaurant_id)
        ingredient = Ingredient(
            restaurant_id=restaurant_id,
            outlet_id=outlet_id,
            name=data.name,
            normalized_name=" ".join(data.name.casefold().split()),
            description=data.description,
            is_active=data.is_active,
        )
        self.session.add(ingredient)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise MenuConflict(
                "ingredient name is already in use", code="duplicate_ingredient"
            ) from exc
        await self.session.refresh(ingredient)
        return ingredient

    async def list_ingredients(
        self, restaurant_id: UUID, outlet_id: UUID | None = None
    ) -> list[Ingredient]:
        await self._restaurant(restaurant_id)
        query = select(Ingredient).where(Ingredient.restaurant_id == restaurant_id)
        if outlet_id is not None:
            query = query.where(Ingredient.outlet_id == outlet_id)
        result = await self.session.execute(query.order_by(Ingredient.name))
        return list(result.scalars())

    async def get_ingredient(self, ingredient_id: UUID) -> Ingredient:
        item = await self.session.get(Ingredient, ingredient_id)
        if item is None:
            raise MenuNotFound("ingredient not found")
        return item

    async def update_ingredient(self, ingredient_id: UUID, data: IngredientPatch) -> Ingredient:
        item = await self.get_ingredient(ingredient_id)
        values = data.model_dump(exclude_unset=True)
        if values.get("name") is not None:
            values["normalized_name"] = " ".join(values["name"].casefold().split())
        for key, value in values.items():
            setattr(item, key, value)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise MenuConflict(
                "ingredient name is already in use", code="duplicate_ingredient"
            ) from exc
        await self.session.refresh(item)
        return item

    async def replace_cuisines(self, menu_id: UUID, data: CuisineReplace) -> list[Cuisine]:
        menu = await self._menu(menu_id)
        self._editable(menu)
        ids = list(dict.fromkeys(data.cuisine_ids))
        result = await self.session.execute(select(Cuisine).where(Cuisine.id.in_(ids)))
        cuisines = list(result.scalars()) if ids else []
        if len(cuisines) != len(ids) or any(
            c.restaurant_id != menu.restaurant_id for c in cuisines
        ):
            raise MenuConflict("cuisine does not belong to menu outlet", code="ownership_error")
        if menu.outlet_id is not None and any(c.outlet_id != menu.outlet_id for c in cuisines):
            raise MenuConflict("cuisine does not belong to menu outlet", code="ownership_error")
        await self.session.execute(delete(MenuCuisine).where(MenuCuisine.menu_id == menu_id))
        self.session.add_all([MenuCuisine(menu_id=menu_id, cuisine_id=c.id) for c in cuisines])
        await self.session.commit()
        return cuisines

    async def replace_dish_cuisines(self, dish_id: UUID, data: CuisineReplace) -> list[Cuisine]:
        dish = await self._dish(dish_id)
        menu = await self._menu(dish.menu_id)
        self._editable(menu)
        ids = list(dict.fromkeys(data.cuisine_ids))
        result = (
            await self.session.execute(select(Cuisine).where(Cuisine.id.in_(ids))) if ids else None
        )
        cuisines = list(result.scalars()) if result is not None else []
        if len(cuisines) != len(ids) or any(
            c.restaurant_id != menu.restaurant_id for c in cuisines
        ):
            raise MenuConflict("cuisine does not belong to dish outlet", code="ownership_error")
        if menu.outlet_id is not None and any(c.outlet_id != menu.outlet_id for c in cuisines):
            raise MenuConflict("cuisine does not belong to dish outlet", code="ownership_error")
        await self.session.execute(delete(DishCuisine).where(DishCuisine.dish_id == dish_id))
        self.session.add_all([DishCuisine(dish_id=dish_id, cuisine_id=c.id) for c in cuisines])
        await self.session.commit()
        return cuisines

    async def list_menu_cuisines(self, menu_id: UUID) -> list[Cuisine]:
        await self._menu(menu_id)
        result = await self.session.execute(
            select(Cuisine)
            .join(MenuCuisine)
            .where(MenuCuisine.menu_id == menu_id)
            .order_by(Cuisine.name)
        )
        return list(result.scalars())

    async def _ingredients_for_menu(self, menu: Menu, ids: list[UUID]) -> list[Ingredient]:
        if not ids:
            return []
        result = await self.session.execute(select(Ingredient).where(Ingredient.id.in_(ids)))
        ingredients = list(result.scalars())
        if len(ingredients) != len(set(ids)) or any(
            i.restaurant_id != menu.restaurant_id for i in ingredients
        ):
            raise MenuConflict("ingredient does not belong to menu outlet", code="ownership_error")
        if menu.outlet_id is not None and any(i.outlet_id != menu.outlet_id for i in ingredients):
            raise MenuConflict("ingredient does not belong to menu outlet", code="ownership_error")
        return ingredients

    async def create_dish(self, menu_id: UUID, data: DishCreate) -> Dish:
        menu = await self._menu(menu_id)
        self._editable(menu)
        if data.category_id is not None:
            await self._category_for_menu(menu_id, data.category_id)
        ingredients = await self._ingredients_for_menu(menu, data.ingredient_ids)
        values = data.model_dump(
            exclude={
                "variants",
                "ingredient_ids",
                "dietary_statuses",
                "badges",
                "allergen_status",
                "halal_override",
                "provenance_source",
            }
        )
        values["allergen_status"] = data.allergen_information_status
        values["halal_override"] = data.halal_status
        values["provenance_source"] = data.catalog_source
        # Owner-created records in the outlet-scoped API are explicit manual
        # facts. Legacy restaurant-scoped menus retain pending-by-default
        # behavior for backwards compatibility with the first catalog API.
        if (
            menu.outlet_id is not None
            and data.catalog_source.value == "manual"
            and "review_status" not in data.model_fields_set
        ):
            values["review_status"] = ReviewStatus.CONFIRMED
        dish = Dish(menu_id=menu_id, **values)
        dish.ingredients = [DishIngredient(ingredient_id=i.id) for i in ingredients]
        dish.variants = [
            DishVariant(
                name=v.name,
                normalized_name=" ".join(v.name.casefold().split()),
                price=v.price,
                is_active=v.is_active,
                display_order=v.display_order,
                sort_order=v.display_order,
            )
            for v in data.variants
        ]
        dish.dietary_statuses = [DishDietaryStatus(status=s) for s in data.dietary_statuses]
        dish.badges = [DishBadge(badge=b) for b in data.badges]
        self.session.add(dish)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise MenuConflict("duplicate or invalid dish data", code="duplicate_record") from exc
        return await self._dish(dish.id)

    async def get_dish(self, dish_id: UUID) -> Dish:
        return await self._dish(dish_id)

    async def list_dishes(
        self,
        menu_id: UUID,
        *,
        category_id: UUID | None = None,
        item_type: str | None = None,
        dietary_classification: str | None = None,
        is_active: bool | None = None,
        cuisine_id: UUID | None = None,
    ) -> list[Dish]:
        await self._menu(menu_id)
        query = select(Dish).where(Dish.menu_id == menu_id)
        if category_id is not None:
            query = query.where(Dish.category_id == category_id)
        if item_type is not None:
            query = query.where(Dish.item_type == item_type)
        if dietary_classification is not None:
            query = query.where(Dish.dietary_classification == dietary_classification)
        if is_active is not None:
            query = query.where(Dish.is_active == is_active)
        if cuisine_id is not None:
            query = query.join(MenuCuisine, MenuCuisine.menu_id == menu_id).where(
                MenuCuisine.cuisine_id == cuisine_id
            )
        result = await self.session.execute(query.order_by(Dish.display_order, Dish.name))
        return [await self._dish(item.id) for item in result.scalars()]

    async def update_dish(self, dish_id: UUID, data: DishPatch) -> Dish:
        dish = await self._dish(dish_id)
        menu = await self._menu(dish.menu_id)
        self._editable(menu)
        values = data.model_dump(exclude_unset=True)
        if data.allergen_status is not None:
            values["allergen_information_status"] = data.allergen_status
        if data.halal_override is not None:
            values["halal_status"] = data.halal_override
        if data.provenance_source is not None:
            values["catalog_source"] = data.provenance_source
        if "category_id" in values and values["category_id"] is not None:
            await self._category_for_menu(dish.menu_id, values["category_id"])
        if "allergen_information_status" in values:
            values["allergen_status"] = values["allergen_information_status"]
        if "halal_status" in values:
            values["halal_override"] = values["halal_status"]
        if "catalog_source" in values:
            values["provenance_source"] = values["catalog_source"]
        for key, value in values.items():
            if hasattr(dish, key):
                setattr(dish, key, value)
        if values.get("review_status") in (ReviewStatus.CONFIRMED, ReviewStatus.APPROVED):
            dish.reviewed_at = datetime.now(UTC)
        await self.session.commit()
        return await self._dish(dish_id)

    async def create_variant(self, dish_id: UUID, data: VariantCreate) -> DishVariant:
        dish = await self._dish(dish_id)
        menu = await self._menu(dish.menu_id)
        self._editable(menu)
        variant = DishVariant(
            dish_id=dish_id,
            name=data.name,
            normalized_name=" ".join(data.name.casefold().split()),
            price=data.price,
            is_active=data.is_active,
            display_order=data.display_order,
            sort_order=data.display_order,
        )
        self.session.add(variant)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise MenuConflict("variant name is already in use", code="duplicate_variant") from exc
        await self.session.refresh(variant)
        return variant

    async def list_variants(self, dish_id: UUID) -> list[DishVariant]:
        await self._dish(dish_id)
        result = await self.session.execute(
            select(DishVariant)
            .where(DishVariant.dish_id == dish_id)
            .order_by(DishVariant.display_order, DishVariant.name)
        )
        return list(result.scalars())

    async def update_variant(self, variant_id: UUID, data: VariantPatch) -> DishVariant:
        variant = await self.session.get(DishVariant, variant_id)
        if variant is None:
            raise MenuNotFound("variant not found")
        dish = await self._dish(variant.dish_id)
        self._editable(await self._menu(dish.menu_id))
        values = data.model_dump(exclude_unset=True)
        if values.get("name") is not None:
            values["normalized_name"] = " ".join(values["name"].casefold().split())
        if "display_order" in values:
            values["sort_order"] = values["display_order"]
        for key, value in values.items():
            setattr(variant, key, value)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise MenuConflict("variant name is already in use", code="duplicate_variant") from exc
        await self.session.refresh(variant)
        return variant

    async def replace_ingredients(
        self, dish_id: UUID, data: IngredientReplace
    ) -> list[DishIngredient]:
        dish = await self._dish(dish_id)
        menu = await self._menu(dish.menu_id)
        self._editable(menu)
        ingredients = await self._ingredients_for_menu(
            menu, [x.ingredient_id for x in data.ingredients]
        )
        if len(ingredients) != len(data.ingredients):
            raise MenuConflict("ingredient does not belong to menu outlet", code="ownership_error")
        await self.session.execute(delete(DishIngredient).where(DishIngredient.dish_id == dish_id))
        rows = [
            DishIngredient(
                dish_id=dish_id,
                ingredient_id=item.ingredient_id,
                is_required_for_availability=item.is_required_for_availability,
                quantity=item.quantity,
                unit=item.unit,
                notes=item.notes,
            )
            for item in data.ingredients
        ]
        self.session.add_all(rows)
        await self.session.commit()
        return rows

    async def list_ingredients_for_dish(self, dish_id: UUID) -> list[DishIngredient]:
        return (await self._dish(dish_id)).ingredients

    async def replace_dietary_statuses(
        self, dish_id: UUID, data: DietaryReplace
    ) -> list[DishDietaryStatus]:
        dish = await self._dish(dish_id)
        self._editable(await self._menu(dish.menu_id))
        await self.session.execute(
            delete(DishDietaryStatus).where(DishDietaryStatus.dish_id == dish_id)
        )
        rows = [DishDietaryStatus(dish_id=dish_id, status=s) for s in data.statuses]
        self.session.add_all(rows)
        await self.session.commit()
        return rows

    async def replace_badges(self, dish_id: UUID, data: BadgeReplace) -> list[DishBadge]:
        dish = await self._dish(dish_id)
        self._editable(await self._menu(dish.menu_id))
        await self.session.execute(delete(DishBadge).where(DishBadge.dish_id == dish_id))
        rows = [DishBadge(dish_id=dish_id, badge=b) for b in data.badges]
        self.session.add_all(rows)
        await self.session.commit()
        return rows

    async def add_image(self, dish_id: UUID, data: ImageCreate) -> DishImage:
        dish = await self._dish(dish_id)
        self._editable(await self._menu(dish.menu_id))
        if data.variant_id is not None:
            variant = await self.session.get(DishVariant, data.variant_id)
            if variant is None or variant.dish_id != dish_id:
                raise MenuConflict("variant does not belong to dish", code="ownership_error")
        if data.is_primary:
            await self.session.execute(
                update(DishImage)
                .where(DishImage.dish_id == dish_id, DishImage.variant_id == data.variant_id)
                .values(is_primary=False)
            )
        image = DishImage(dish_id=dish_id, **data.model_dump())
        self.session.add(image)
        await self.session.commit()
        await self.session.refresh(image)
        return image

    async def list_images(self, dish_id: UUID) -> list[DishImage]:
        await self._dish(dish_id)
        result = await self.session.execute(select(DishImage).where(DishImage.dish_id == dish_id))
        return list(result.scalars())

    async def update_image(self, image_id: UUID, data: ImagePatch) -> DishImage:
        image = await self.session.get(DishImage, image_id)
        if image is None:
            raise MenuNotFound("image not found")
        dish = await self._dish(image.dish_id)
        self._editable(await self._menu(dish.menu_id))
        values = data.model_dump(exclude_unset=True)
        variant_id = values.get("variant_id", image.variant_id)
        if variant_id is not None:
            variant = await self.session.get(DishVariant, variant_id)
            if variant is None or variant.dish_id != dish.id:
                raise MenuConflict("variant does not belong to dish", code="ownership_error")
        if values.get("is_primary"):
            await self.session.execute(
                update(DishImage)
                .where(DishImage.dish_id == dish.id, DishImage.variant_id == variant_id)
                .values(is_primary=False)
            )
        for key, value in values.items():
            setattr(image, key, value)
        await self.session.commit()
        await self.session.refresh(image)
        return image

    async def add_modifier_group(self, dish_id: UUID, data: ModifierGroupCreate) -> ModifierGroup:
        dish = await self._dish(dish_id)
        self._editable(await self._menu(dish.menu_id))
        group = ModifierGroup(
            dish_id=dish_id,
            name=data.name,
            is_required=data.is_required,
            min_selections=data.min_selections,
            max_selections=data.max_selections,
            display_order=data.display_order,
            sort_order=data.display_order,
            is_active=data.is_active,
        )
        self.session.add(group)
        await self.session.commit()
        result = await self.session.execute(
            select(ModifierGroup)
            .options(selectinload(ModifierGroup.options))
            .where(ModifierGroup.id == group.id)
        )
        return result.scalar_one()

    async def update_modifier_group(
        self, group_id: UUID, data: ModifierGroupPatch
    ) -> ModifierGroup:
        group = await self.session.get(ModifierGroup, group_id)
        if group is None:
            raise MenuNotFound("modifier group not found")
        dish = await self._dish(group.dish_id)
        self._editable(await self._menu(dish.menu_id))
        values = data.model_dump(exclude_unset=True)
        min_value = values.get("min_selections", group.min_selections)
        max_value = values.get("max_selections", group.max_selections)
        if max_value < min_value:
            raise MenuConflict(
                "max_selections must be at least min_selections", code="invalid_modifier_bounds"
            )
        for key, value in values.items():
            setattr(group, key, value)
        await self.session.commit()
        await self.session.refresh(group)
        return group

    async def add_modifier_option(
        self, group_id: UUID, data: ModifierOptionCreate
    ) -> ModifierOption:
        group = await self.session.get(ModifierGroup, group_id)
        if group is None:
            raise MenuNotFound("modifier group not found")
        dish = await self._dish(group.dish_id)
        self._editable(await self._menu(dish.menu_id))
        option = ModifierOption(group_id=group_id, **data.model_dump())
        self.session.add(option)
        await self.session.commit()
        await self.session.refresh(option)
        return option

    async def update_modifier_option(
        self, option_id: UUID, data: ModifierOptionPatch
    ) -> ModifierOption:
        option = await self.session.get(ModifierOption, option_id)
        if option is None:
            raise MenuNotFound("modifier option not found")
        group = await self.session.get(ModifierGroup, option.group_id)
        if group is None:
            raise MenuNotFound("modifier group not found")
        dish = await self._dish(group.dish_id)
        self._editable(await self._menu(dish.menu_id))
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(option, key, value)
        await self.session.commit()
        await self.session.refresh(option)
        return option

    async def list_modifier_groups(self, dish_id: UUID) -> list[ModifierGroup]:
        await self._dish(dish_id)
        result = await self.session.execute(
            select(ModifierGroup)
            .options(selectinload(ModifierGroup.options))
            .where(ModifierGroup.dish_id == dish_id)
            .order_by(ModifierGroup.display_order, ModifierGroup.name)
        )
        return list(result.scalars())

    async def publication_status(self, menu_id: UUID) -> dict[str, object]:
        menu = await self._menu(menu_id, eager=True)
        blockers = self._publication_blockers(menu)
        if menu.outlet_id is not None:
            restaurant = await self._restaurant(menu.restaurant_id)
            if restaurant.onboarding_status.value != "ready_for_menu":
                blockers.insert(0, "parent onboarding is not ready")
            outlet = await self._outlet(menu.outlet_id, menu.restaurant_id)
            if not outlet.is_active:
                blockers.insert(0, "outlet is inactive")
        return {
            "menu_id": menu.id,
            "status": menu.status,
            "ready": not blockers,
            "blockers": blockers,
        }

    def _publication_blockers(self, menu: Menu) -> list[str]:
        blockers: list[str] = []
        if not menu.categories or not any(c.is_active for c in menu.categories):
            blockers.append("at least one active category is required")
        active_dishes = [d for d in menu.dishes if d.is_active]
        if not active_dishes:
            blockers.append("at least one active dish is required")
        active_categories = {c.id for c in menu.categories if c.is_active}
        for dish in active_dishes:
            if dish.category_id not in active_categories:
                blockers.append(f"dish {dish.name} must reference an active category in this menu")
            if dish.base_price is None and not any(
                v.is_active and v.price is not None for v in dish.variants
            ):
                blockers.append(f"dish {dish.name} needs base_price or an active variant price")
            if dish.review_status not in (ReviewStatus.CONFIRMED, ReviewStatus.APPROVED):
                blockers.append(f"dish {dish.name} is pending review")
            for group in dish.modifier_groups:
                if group.is_active and (
                    group.max_selections < group.min_selections
                    or not any(o.is_active for o in group.options)
                ):
                    blockers.append(f"modifier group {group.name} is invalid")
        return blockers

    async def publish(self, menu_id: UUID, data: PublishRequest) -> Menu:
        if not data.confirm:
            raise MenuConflict("publishing requires confirm=true", code="confirmation_required")
        menu = await self._menu(menu_id, eager=True)
        if menu.outlet_id is not None:
            restaurant = await self._restaurant(menu.restaurant_id)
            if restaurant.onboarding_status.value != "ready_for_menu":
                raise MenuConflict("parent onboarding is not ready", code="onboarding_not_ready")
            outlet = await self._outlet(menu.outlet_id, menu.restaurant_id)
            if not outlet.is_active:
                raise MenuConflict("outlet is inactive", code="outlet_inactive")
            published = (
                await self.session.execute(
                    select(Menu).where(
                        Menu.outlet_id == menu.outlet_id,
                        Menu.status == MenuStatus.PUBLISHED,
                        Menu.id != menu.id,
                    )
                )
            ).scalar_one_or_none()
        else:
            published = (
                await self.session.execute(
                    select(Menu).where(
                        Menu.restaurant_id == menu.restaurant_id,
                        Menu.status == MenuStatus.PUBLISHED,
                        Menu.id != menu.id,
                    )
                )
            ).scalar_one_or_none()
        if published is not None:
            raise MenuConflict(
                "another published menu already exists", code="published_menu_exists"
            )
        blockers = self._publication_blockers(menu)
        if blockers:
            raise MenuConflict(
                "menu failed publish validation",
                code="publish_validation_failed",
                details={"errors": blockers},
            )
        menu.status = MenuStatus.PUBLISHED
        menu.published_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(menu)
        return menu

    async def _category_for_menu(self, menu_id: UUID, category_id: UUID) -> Category:
        item = (
            await self.session.execute(
                select(Category).where(Category.id == category_id, Category.menu_id == menu_id)
            )
        ).scalar_one_or_none()
        if item is None:
            raise MenuConflict("category does not belong to menu", code="ownership_error")
        return item

    async def create_draft_revision(self, outlet_id: UUID) -> Menu:
        draft = (
            await self.session.execute(
                select(Menu).where(Menu.outlet_id == outlet_id, Menu.status == MenuStatus.DRAFT)
            )
        ).scalar_one_or_none()
        if draft is not None:
            return draft

        published = (
            await self.session.execute(
                select(Menu)
                .options(
                    selectinload(Menu.categories),
                    selectinload(Menu.dishes).selectinload(Dish.variants),
                )
                .where(Menu.outlet_id == outlet_id, Menu.status == MenuStatus.PUBLISHED)
            )
        ).scalar_one_or_none()

        outlet = await self.session.get(RestaurantOutlet, outlet_id)
        if outlet is None:
            raise MenuNotFound("outlet not found")

        if published is None:
            new_menu = Menu(
                restaurant_id=outlet.restaurant_id,
                outlet_id=outlet.id,
                name="Main Menu (Draft)",
                status=MenuStatus.DRAFT,
            )
            self.session.add(new_menu)
            await self.session.commit()
            await self.session.refresh(new_menu)
            return new_menu

        new_menu = Menu(
            restaurant_id=published.restaurant_id,
            outlet_id=published.outlet_id,
            name=f"{published.name} (Draft)",
            status=MenuStatus.DRAFT,
        )
        self.session.add(new_menu)
        await self.session.flush()

        cat_map: dict[UUID, Category] = {}
        for old_cat in published.categories:
            new_cat = Category(
                menu_id=new_menu.id,
                name=old_cat.name,
                slug=f"{old_cat.slug}-draft",
                display_order=old_cat.display_order,
                is_active=old_cat.is_active,
            )
            self.session.add(new_cat)
            await self.session.flush()
            cat_map[old_cat.id] = new_cat

        for old_dish in published.dishes:
            new_dish = Dish(
                menu_id=new_menu.id,
                category_id=cat_map[old_dish.category_id].id
                if old_dish.category_id in cat_map
                else None,
                name=old_dish.name,
                description=old_dish.description,
                item_type=old_dish.item_type,
                dietary_classification=old_dish.dietary_classification,
                spice_level=old_dish.spice_level,
                base_price=old_dish.base_price,
                display_order=old_dish.display_order,
                is_active=old_dish.is_active,
                review_status=ReviewStatus.CONFIRMED,
            )
            self.session.add(new_dish)
            await self.session.flush()

            for old_var in old_dish.variants:
                new_var = DishVariant(
                    dish_id=new_dish.id,
                    name=old_var.name,
                    normalized_name=old_var.normalized_name,
                    price=old_var.price,
                    is_active=old_var.is_active,
                )
                self.session.add(new_var)

        await self.session.commit()
        await self.session.refresh(new_menu)
        return new_menu

    async def preview_draft_diff(self, outlet_id: UUID) -> dict[str, Any]:
        published = (
            await self.session.execute(
                select(Menu)
                .options(selectinload(Menu.dishes))
                .where(Menu.outlet_id == outlet_id, Menu.status == MenuStatus.PUBLISHED)
            )
        ).scalar_one_or_none()

        draft = (
            await self.session.execute(
                select(Menu)
                .options(selectinload(Menu.dishes))
                .where(Menu.outlet_id == outlet_id, Menu.status == MenuStatus.DRAFT)
            )
        ).scalar_one_or_none()

        if draft is None:
            return {"has_draft": False, "changes": []}

        published_dishes = {d.name.lower(): d for d in (published.dishes if published else [])}
        draft_dishes = {d.name.lower(): d for d in draft.dishes}

        changes: list[dict[str, str]] = []
        for name_lower, draft_d in draft_dishes.items():
            if name_lower not in published_dishes:
                changes.append(
                    {
                        "action": "added_dish",
                        "dish_name": draft_d.name,
                        "price": str(draft_d.base_price),
                    }
                )
            else:
                pub_d = published_dishes[name_lower]
                if pub_d.base_price != draft_d.base_price:
                    changes.append(
                        {
                            "action": "price_changed",
                            "dish_name": draft_d.name,
                            "old_price": str(pub_d.base_price),
                            "new_price": str(draft_d.base_price),
                        }
                    )

        for name_lower, pub_d in published_dishes.items():
            if name_lower not in draft_dishes:
                changes.append(
                    {
                        "action": "removed_dish",
                        "dish_name": pub_d.name,
                    }
                )

        return {
            "has_draft": True,
            "draft_id": str(draft.id),
            "changes_count": len(changes),
            "changes": changes,
        }

    async def publish_draft_revision(self, outlet_id: UUID) -> Menu:
        draft = (
            await self.session.execute(
                select(Menu).where(Menu.outlet_id == outlet_id, Menu.status == MenuStatus.DRAFT)
            )
        ).scalar_one_or_none()
        if draft is None:
            raise MenuConflict("no draft menu to publish", code="no_draft_menu")

        published = (
            await self.session.execute(
                select(Menu).where(Menu.outlet_id == outlet_id, Menu.status == MenuStatus.PUBLISHED)
            )
        ).scalar_one_or_none()
        if published is not None:
            published.status = MenuStatus.ARCHIVED
            await self.session.flush()

        return await self.publish(draft.id, PublishRequest(confirm=True))

    async def update_dish_price(self, dish_id: UUID, new_price: Decimal) -> tuple[Decimal, Decimal]:
        dish = await self._dish(dish_id)
        menu = await self._menu(dish.menu_id)
        if menu.status != MenuStatus.DRAFT:
            raise MenuConflict(
                "Cannot mutate published menu directly. Create a draft revision first.",
                code="published_menu_immutable",
            )
        old_price = dish.base_price or Decimal("0.00")
        dish.base_price = new_price
        await self.session.commit()
        return old_price, new_price


MenuService = MenuCatalogService
