from fastapi import APIRouter

from ainza_restaurant.core.config import get_settings

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": get_settings().app_name}
