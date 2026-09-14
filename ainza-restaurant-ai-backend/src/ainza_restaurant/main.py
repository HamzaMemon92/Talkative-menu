from fastapi import FastAPI

from ainza_restaurant.api.router import api_router
from ainza_restaurant.core.config import get_settings
from ainza_restaurant.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.include_router(api_router)
    return app


app = create_app()
