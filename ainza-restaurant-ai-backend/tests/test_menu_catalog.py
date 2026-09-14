import asyncio
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.db.base import Base
from ainza_restaurant.db.session import get_db_session
from ainza_restaurant.main import app


def test_menu_catalog_is_draft_first_and_replacements_validate_ownership() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def setup() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def teardown() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    async def override_db():
        async with sessions() as session:
            yield session

    asyncio.run(setup())
    app.dependency_overrides[get_db_session] = override_db
    try:
        with TestClient(app) as client:
            restaurant = client.post("/api/v1/restaurants", json={"name": "Catalog Cafe"}).json()
            other = client.post("/api/v1/restaurants", json={"name": "Other Cafe"}).json()
            menu = client.post(
                f"/api/v1/restaurants/{restaurant['id']}/menus", json={"name": "Dinner"}
            ).json()
            category = client.post(
                f"/api/v1/menus/{menu['id']}/categories", json={"name": "Mains"}
            ).json()
            cuisine = client.post(
                f"/api/v1/restaurants/{restaurant['id']}/cuisines",
                json={"name": "Indian"},
            ).json()
            foreign_cuisine = client.post(
                f"/api/v1/restaurants/{other['id']}/cuisines",
                json={"name": "Italian"},
            ).json()
            assert (
                client.put(
                    f"/api/v1/menus/{menu['id']}/cuisines",
                    json={"cuisine_ids": [foreign_cuisine["id"]]},
                ).status_code
                == 409
            )
            assert (
                client.put(
                    f"/api/v1/menus/{menu['id']}/cuisines",
                    json={"cuisine_ids": [cuisine["id"]]},
                ).status_code
                == 200
            )
            ingredient = client.post(
                f"/api/v1/restaurants/{restaurant['id']}/ingredients",
                json={"name": "Paneer"},
            ).json()
            dish = client.post(
                f"/api/v1/menus/{menu['id']}/dishes",
                json={
                    "name": "Paneer Tikka",
                    "category_id": category["id"],
                    "base_price": "250.00",
                    "ingredient_ids": [ingredient["id"]],
                    "dietary_statuses": ["vegetarian"],
                    "badges": ["chef_recommended"],
                },
            )
            assert dish.status_code == 201
            assert Decimal(dish.json()["base_price"]) == Decimal("250.00")
            variant = client.post(
                f"/api/v1/dishes/{dish.json()['id']}/variants",
                json={"name": "Regular", "price": "250.00"},
            )
            assert variant.status_code == 201
            assert client.get(f"/api/v1/menus/{menu['id']}/dishes").status_code == 200
            group = client.post(
                f"/api/v1/dishes/{dish.json()['id']}/modifier-groups",
                json={"name": "Sauce", "min_selections": 0, "max_selections": 1},
            )
            assert group.status_code == 201
            option = client.post(
                f"/api/v1/modifier-groups/{group.json()['id']}/options",
                json={"name": "Mint", "price_delta": "0.00"},
            )
            assert option.status_code == 201
            assert (
                client.get(f"/api/v1/dishes/{dish.json()['id']}/modifier-groups").status_code == 200
            )
            assert client.post(f"/api/v1/menus/{menu['id']}/publish").status_code == 409
            assert (
                client.patch(
                    f"/api/v1/dishes/{dish.json()['id']}",
                    json={"review_status": "approved"},
                ).status_code
                == 200
            )
            published = client.post(f"/api/v1/menus/{menu['id']}/publish")
            assert published.status_code == 200
            assert published.json()["status"] == "published"
            assert (
                client.patch(
                    f"/api/v1/dishes/{dish.json()['id']}",
                    json={"name": "Changed"},
                ).status_code
                == 409
            )
    finally:
        app.dependency_overrides.clear()
        asyncio.run(teardown())
