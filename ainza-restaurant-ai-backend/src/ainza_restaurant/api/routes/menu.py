# ruff: noqa: B008
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.db.session import get_db_session
from ainza_restaurant.menu.schemas import (
    BadgeReplace,
    CategoryCreate,
    CategoryPatch,
    CategoryRead,
    CuisineCreate,
    CuisinePatch,
    CuisineRead,
    CuisineReplace,
    DietaryReplace,
    DishCreate,
    DishIngredientRead,
    DishPatch,
    DishRead,
    ImageCreate,
    ImagePatch,
    ImageRead,
    IngredientCreate,
    IngredientPatch,
    IngredientRead,
    IngredientReplace,
    MenuCreate,
    MenuPatch,
    MenuRead,
    ModifierGroupCreate,
    ModifierGroupPatch,
    ModifierGroupRead,
    ModifierOptionCreate,
    ModifierOptionPatch,
    ModifierOptionRead,
    PublicationStatusRead,
    PublishRequest,
    VariantCreate,
    VariantPatch,
    VariantRead,
)
from ainza_restaurant.menu.service import MenuCatalogService, MenuConflict, MenuNotFound

router = APIRouter(tags=["menu catalog"])


def catalog(session: AsyncSession = Depends(get_db_session)) -> MenuCatalogService:
    return MenuCatalogService(session)


def _not_found(exc: MenuNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})


def _conflict(exc: MenuConflict) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": exc.code, "message": str(exc), "details": exc.details},
    )


@router.post("/api/v1/outlets/{outlet_id}/menus", response_model=MenuRead, status_code=201)
async def create_outlet_menu(
    outlet_id: UUID, payload: MenuCreate, service: MenuCatalogService = Depends(catalog)
) -> MenuRead:
    try:
        payload.outlet_id = outlet_id
        outlet = await service._outlet(outlet_id)
        return MenuRead.model_validate(await service.create_menu(outlet.restaurant_id, payload))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.put("/api/v1/dishes/{dish_id}/cuisines", response_model=list[CuisineRead])
async def replace_dish_cuisines(
    dish_id: UUID, payload: CuisineReplace, service: MenuCatalogService = Depends(catalog)
) -> list[CuisineRead]:
    try:
        cuisines = await service.replace_dish_cuisines(dish_id, payload)
        return [CuisineRead.model_validate(item) for item in cuisines]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/restaurants/{restaurant_id}/menus", response_model=MenuRead, status_code=201)
async def create_menu(
    restaurant_id: UUID,
    payload: MenuCreate,
    service: MenuCatalogService = Depends(catalog),
) -> MenuRead:
    try:
        return MenuRead.model_validate(await service.create_menu(restaurant_id, payload))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/outlets/{outlet_id}/menus", response_model=list[MenuRead])
async def list_outlet_menus(
    outlet_id: UUID, service: MenuCatalogService = Depends(catalog)
) -> list[MenuRead]:
    try:
        outlet = await service._outlet(outlet_id)
        return [
            MenuRead.model_validate(item)
            for item in await service.list_menus(outlet.restaurant_id, outlet_id)
        ]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/restaurants/{restaurant_id}/menus", response_model=list[MenuRead])
async def list_menus(
    restaurant_id: UUID, service: MenuCatalogService = Depends(catalog)
) -> list[MenuRead]:
    try:
        return [MenuRead.model_validate(item) for item in await service.list_menus(restaurant_id)]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/menus/{menu_id}", response_model=MenuRead)
async def get_menu(menu_id: UUID, service: MenuCatalogService = Depends(catalog)) -> MenuRead:
    try:
        return MenuRead.model_validate(await service.get_menu(menu_id))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.patch("/api/v1/menus/{menu_id}", response_model=MenuRead)
async def patch_menu(
    menu_id: UUID, payload: MenuPatch, service: MenuCatalogService = Depends(catalog)
) -> MenuRead:
    try:
        return MenuRead.model_validate(await service.update_menu(menu_id, payload))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/menus/{menu_id}/categories", response_model=CategoryRead, status_code=201)
async def create_category(
    menu_id: UUID, payload: CategoryCreate, service: MenuCatalogService = Depends(catalog)
) -> CategoryRead:
    try:
        return CategoryRead.model_validate(await service.create_category(menu_id, payload))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/menus/{menu_id}/categories", response_model=list[CategoryRead])
async def list_categories(
    menu_id: UUID, service: MenuCatalogService = Depends(catalog)
) -> list[CategoryRead]:
    try:
        return [
            CategoryRead.model_validate(item) for item in await service.list_categories(menu_id)
        ]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/categories/{category_id}", response_model=CategoryRead)
async def get_category(
    category_id: UUID, service: MenuCatalogService = Depends(catalog)
) -> CategoryRead:
    try:
        return CategoryRead.model_validate(await service.get_category(category_id))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.patch("/api/v1/categories/{category_id}", response_model=CategoryRead)
async def patch_category(
    category_id: UUID, payload: CategoryPatch, service: MenuCatalogService = Depends(catalog)
) -> CategoryRead:
    try:
        return CategoryRead.model_validate(await service.update_category(category_id, payload))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/outlets/{outlet_id}/cuisines", response_model=CuisineRead, status_code=201)
async def create_outlet_cuisine(
    outlet_id: UUID, payload: CuisineCreate, service: MenuCatalogService = Depends(catalog)
) -> CuisineRead:
    try:
        outlet = await service._outlet(outlet_id)
        return CuisineRead.model_validate(
            await service.create_cuisine(outlet.restaurant_id, payload, outlet_id)
        )
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/outlets/{outlet_id}/cuisines", response_model=list[CuisineRead])
async def list_outlet_cuisines(
    outlet_id: UUID, service: MenuCatalogService = Depends(catalog)
) -> list[CuisineRead]:
    try:
        outlet = await service._outlet(outlet_id)
        return [
            CuisineRead.model_validate(item)
            for item in await service.list_cuisines(outlet.restaurant_id, outlet_id)
        ]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.post(
    "/api/v1/restaurants/{restaurant_id}/cuisines", response_model=CuisineRead, status_code=201
)
async def create_cuisine(
    restaurant_id: UUID, payload: CuisineCreate, service: MenuCatalogService = Depends(catalog)
) -> CuisineRead:
    try:
        return CuisineRead.model_validate(await service.create_cuisine(restaurant_id, payload))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/restaurants/{restaurant_id}/cuisines", response_model=list[CuisineRead])
async def list_cuisines(
    restaurant_id: UUID, service: MenuCatalogService = Depends(catalog)
) -> list[CuisineRead]:
    try:
        return [
            CuisineRead.model_validate(item) for item in await service.list_cuisines(restaurant_id)
        ]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.patch("/api/v1/cuisines/{cuisine_id}", response_model=CuisineRead)
async def patch_cuisine(
    cuisine_id: UUID, payload: CuisinePatch, service: MenuCatalogService = Depends(catalog)
) -> CuisineRead:
    try:
        return CuisineRead.model_validate(await service.update_cuisine(cuisine_id, payload))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.put("/api/v1/menus/{menu_id}/cuisines", response_model=list[CuisineRead])
async def replace_cuisines(
    menu_id: UUID, payload: CuisineReplace, service: MenuCatalogService = Depends(catalog)
) -> list[CuisineRead]:
    try:
        return [
            CuisineRead.model_validate(item)
            for item in await service.replace_cuisines(menu_id, payload)
        ]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/menus/{menu_id}/cuisines", response_model=list[CuisineRead])
async def list_menu_cuisines(
    menu_id: UUID, service: MenuCatalogService = Depends(catalog)
) -> list[CuisineRead]:
    try:
        return [
            CuisineRead.model_validate(item) for item in await service.list_menu_cuisines(menu_id)
        ]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.post(
    "/api/v1/outlets/{outlet_id}/ingredients",
    response_model=IngredientRead,
    status_code=201,
)
async def create_outlet_ingredient(
    outlet_id: UUID, payload: IngredientCreate, service: MenuCatalogService = Depends(catalog)
) -> IngredientRead:
    try:
        outlet = await service._outlet(outlet_id)
        return IngredientRead.model_validate(
            await service.create_ingredient(outlet.restaurant_id, payload, outlet_id)
        )
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/outlets/{outlet_id}/ingredients", response_model=list[IngredientRead])
async def list_outlet_ingredients(
    outlet_id: UUID, service: MenuCatalogService = Depends(catalog)
) -> list[IngredientRead]:
    try:
        outlet = await service._outlet(outlet_id)
        return [
            IngredientRead.model_validate(item)
            for item in await service.list_ingredients(outlet.restaurant_id, outlet_id)
        ]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.post(
    "/api/v1/restaurants/{restaurant_id}/ingredients",
    response_model=IngredientRead,
    status_code=201,
)
async def create_ingredient(
    restaurant_id: UUID, payload: IngredientCreate, service: MenuCatalogService = Depends(catalog)
) -> IngredientRead:
    try:
        return IngredientRead.model_validate(
            await service.create_ingredient(restaurant_id, payload)
        )
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/restaurants/{restaurant_id}/ingredients", response_model=list[IngredientRead])
async def list_ingredients(
    restaurant_id: UUID, service: MenuCatalogService = Depends(catalog)
) -> list[IngredientRead]:
    try:
        return [
            IngredientRead.model_validate(item)
            for item in await service.list_ingredients(restaurant_id)
        ]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/ingredients/{ingredient_id}", response_model=IngredientRead)
async def get_ingredient(
    ingredient_id: UUID, service: MenuCatalogService = Depends(catalog)
) -> IngredientRead:
    try:
        return IngredientRead.model_validate(await service.get_ingredient(ingredient_id))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.patch("/api/v1/ingredients/{ingredient_id}", response_model=IngredientRead)
async def patch_ingredient(
    ingredient_id: UUID, payload: IngredientPatch, service: MenuCatalogService = Depends(catalog)
) -> IngredientRead:
    try:
        return IngredientRead.model_validate(
            await service.update_ingredient(ingredient_id, payload)
        )
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/menus/{menu_id}/dishes", response_model=DishRead, status_code=201)
async def create_dish(
    menu_id: UUID, payload: DishCreate, service: MenuCatalogService = Depends(catalog)
) -> DishRead:
    try:
        return DishRead.model_validate(await service.create_dish(menu_id, payload))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/menus/{menu_id}/dishes", response_model=list[DishRead])
async def list_dishes(
    menu_id: UUID,
    category_id: UUID | None = None,
    item_type: str | None = None,
    dietary_classification: str | None = None,
    is_active: bool | None = None,
    cuisine_id: UUID | None = None,
    service: MenuCatalogService = Depends(catalog),
) -> list[DishRead]:
    try:
        return [
            DishRead.model_validate(item)
            for item in await service.list_dishes(
                menu_id,
                category_id=category_id,
                item_type=item_type,
                dietary_classification=dietary_classification,
                is_active=is_active,
                cuisine_id=cuisine_id,
            )
        ]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/dishes/{dish_id}", response_model=DishRead)
async def get_dish(dish_id: UUID, service: MenuCatalogService = Depends(catalog)) -> DishRead:
    try:
        return DishRead.model_validate(await service.get_dish(dish_id))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.patch("/api/v1/dishes/{dish_id}", response_model=DishRead)
async def patch_dish(
    dish_id: UUID, payload: DishPatch, service: MenuCatalogService = Depends(catalog)
) -> DishRead:
    try:
        return DishRead.model_validate(await service.update_dish(dish_id, payload))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/dishes/{dish_id}/variants", response_model=VariantRead, status_code=201)
async def create_variant(
    dish_id: UUID, payload: VariantCreate, service: MenuCatalogService = Depends(catalog)
) -> VariantRead:
    try:
        return VariantRead.model_validate(await service.create_variant(dish_id, payload))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/dishes/{dish_id}/variants", response_model=list[VariantRead])
async def list_variants(
    dish_id: UUID, service: MenuCatalogService = Depends(catalog)
) -> list[VariantRead]:
    try:
        return [VariantRead.model_validate(item) for item in await service.list_variants(dish_id)]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.patch("/api/v1/variants/{variant_id}", response_model=VariantRead)
async def patch_variant(
    variant_id: UUID, payload: VariantPatch, service: MenuCatalogService = Depends(catalog)
) -> VariantRead:
    try:
        return VariantRead.model_validate(await service.update_variant(variant_id, payload))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.put("/api/v1/dishes/{dish_id}/ingredients", response_model=list[DishIngredientRead])
async def replace_ingredients(
    dish_id: UUID, payload: IngredientReplace, service: MenuCatalogService = Depends(catalog)
) -> list[DishIngredientRead]:
    try:
        await service.replace_ingredients(dish_id, payload)
        dish = await service.get_dish(dish_id)
        return [DishIngredientRead.model_validate(item) for item in dish.ingredients]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/dishes/{dish_id}/ingredients", response_model=list[DishIngredientRead])
async def list_dish_ingredients(
    dish_id: UUID, service: MenuCatalogService = Depends(catalog)
) -> list[DishIngredientRead]:
    try:
        return [
            DishIngredientRead.model_validate(item)
            for item in await service.list_ingredients_for_dish(dish_id)
        ]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.put("/api/v1/dishes/{dish_id}/dietary-statuses", response_model=list[str])
async def replace_dietary_statuses(
    dish_id: UUID, payload: DietaryReplace, service: MenuCatalogService = Depends(catalog)
) -> list[str]:
    try:
        rows = await service.replace_dietary_statuses(dish_id, payload)
        return [row.status.value for row in rows]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.put("/api/v1/dishes/{dish_id}/badges", response_model=list[str])
async def replace_badges(
    dish_id: UUID, payload: BadgeReplace, service: MenuCatalogService = Depends(catalog)
) -> list[str]:
    try:
        rows = await service.replace_badges(dish_id, payload)
        return [row.badge.value for row in rows]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/api/v1/dishes/{dish_id}/images", response_model=ImageRead, status_code=201)
async def add_image(
    dish_id: UUID, payload: ImageCreate, service: MenuCatalogService = Depends(catalog)
) -> ImageRead:
    try:
        return ImageRead.model_validate(await service.add_image(dish_id, payload))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/dishes/{dish_id}/images", response_model=list[ImageRead])
async def list_images(
    dish_id: UUID, service: MenuCatalogService = Depends(catalog)
) -> list[ImageRead]:
    try:
        return [ImageRead.model_validate(item) for item in await service.list_images(dish_id)]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.patch("/api/v1/dish-images/{image_id}", response_model=ImageRead)
@router.patch("/api/v1/images/{image_id}", response_model=ImageRead)
async def patch_image(
    image_id: UUID, payload: ImagePatch, service: MenuCatalogService = Depends(catalog)
) -> ImageRead:
    try:
        return ImageRead.model_validate(await service.update_image(image_id, payload))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.post(
    "/api/v1/dishes/{dish_id}/modifier-groups", response_model=ModifierGroupRead, status_code=201
)
async def create_modifier_group(
    dish_id: UUID, payload: ModifierGroupCreate, service: MenuCatalogService = Depends(catalog)
) -> ModifierGroupRead:
    try:
        return ModifierGroupRead.model_validate(await service.add_modifier_group(dish_id, payload))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/dishes/{dish_id}/modifier-groups", response_model=list[ModifierGroupRead])
async def list_modifier_groups(
    dish_id: UUID, service: MenuCatalogService = Depends(catalog)
) -> list[ModifierGroupRead]:
    try:
        return [
            ModifierGroupRead.model_validate(item)
            for item in await service.list_modifier_groups(dish_id)
        ]
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.post(
    "/api/v1/modifier-groups/{group_id}/options", response_model=ModifierOptionRead, status_code=201
)
async def create_modifier_option(
    group_id: UUID, payload: ModifierOptionCreate, service: MenuCatalogService = Depends(catalog)
) -> ModifierOptionRead:
    try:
        return ModifierOptionRead.model_validate(
            await service.add_modifier_option(group_id, payload)
        )
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.patch("/api/v1/modifier-groups/{group_id}", response_model=ModifierGroupRead)
async def patch_modifier_group(
    group_id: UUID, payload: ModifierGroupPatch, service: MenuCatalogService = Depends(catalog)
) -> ModifierGroupRead:
    try:
        return ModifierGroupRead.model_validate(
            await service.update_modifier_group(group_id, payload)
        )
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.patch("/api/v1/modifier-options/{option_id}", response_model=ModifierOptionRead)
async def patch_modifier_option(
    option_id: UUID, payload: ModifierOptionPatch, service: MenuCatalogService = Depends(catalog)
) -> ModifierOptionRead:
    try:
        return ModifierOptionRead.model_validate(
            await service.update_modifier_option(option_id, payload)
        )
    except MenuNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/api/v1/menus/{menu_id}/publish", response_model=MenuRead)
async def publish_menu(
    menu_id: UUID,
    payload: PublishRequest | None = None,
    service: MenuCatalogService = Depends(catalog),
) -> MenuRead:
    try:
        return MenuRead.model_validate(
            await service.publish(
                menu_id, payload if payload is not None else PublishRequest(confirm=True)
            )
        )
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
    except MenuConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/menus/{menu_id}/publication-status", response_model=PublicationStatusRead)
async def publication_status(
    menu_id: UUID, service: MenuCatalogService = Depends(catalog)
) -> PublicationStatusRead:
    try:
        return PublicationStatusRead.model_validate(await service.publication_status(menu_id))
    except MenuNotFound as exc:
        raise _not_found(exc) from exc
