from fastapi import APIRouter

from ainza_restaurant.api.routes.ai import router as ai_router
from ainza_restaurant.api.routes.availability import router as availability_router
from ainza_restaurant.api.routes.billing import router as billing_router
from ainza_restaurant.api.routes.customer_menu import router as customer_menu_router
from ainza_restaurant.api.routes.dining import router as dining_router
from ainza_restaurant.api.routes.health import router as health_router
from ainza_restaurant.api.routes.kitchen import router as kitchen_router
from ainza_restaurant.api.routes.menu import router as menu_router
from ainza_restaurant.api.routes.merchandising import router as merchandising_router
from ainza_restaurant.api.routes.ordering import router as ordering_router
from ainza_restaurant.api.routes.restaurants import router as restaurants_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(restaurants_router)
api_router.include_router(menu_router)
api_router.include_router(availability_router)
api_router.include_router(merchandising_router)
api_router.include_router(customer_menu_router)
api_router.include_router(dining_router)
api_router.include_router(ordering_router)
api_router.include_router(kitchen_router)
api_router.include_router(billing_router)
api_router.include_router(ai_router)
