import asyncio

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.db.base import Base
from ainza_restaurant.db.session import get_db_session
from ainza_restaurant.main import app


def test_optional_policy_and_unknown_first_catalog_fields() -> None:
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
            restaurant = client.post("/api/v1/restaurants", json={"name": "Compliance Cafe"}).json()
            outlet = client.post(
                f"/api/v1/restaurants/{restaurant['id']}/outlets",
                json={
                    "name": "Main",
                    "address_line1": "1 Main Street",
                    "city": "Pune",
                    "state": "Maharashtra",
                    "postal_code": "411001",
                },
            ).json()
            policy_path = f"/api/v1/outlets/{outlet['id']}/food-policy"
            response = client.put(policy_path, json={"halal_policy": "unknown"})
            assert response.status_code == 200
            assert response.json()["information_confirmed"] is False
            assert response.json()["halal_policy"] == "unknown"

            menu = client.post(
                f"/api/v1/outlets/{outlet['id']}/menus", json={"name": "Main Menu"}
            ).json()
            category = client.post(
                f"/api/v1/menus/{menu['id']}/categories",
                json={"name": "Main Course", "display_order": 0},
            ).json()
            dish = client.post(
                f"/api/v1/menus/{menu['id']}/dishes",
                json={
                    "name": "Unnamed Facts",
                    "category_id": category["id"],
                    "base_price": "100.00",
                    "review_status": "confirmed",
                    "vegan_status": "unknown",
                    "jain_status": "unknown",
                    "dietary_classification": "unknown",
                },
            )
            assert dish.status_code == 201
            assert dish.json()["vegan_status"] == "unknown"
            assert dish.json()["jain_status"] == "unknown"
            assert dish.json()["dietary_classification"] == "unknown"

            other_outlet = client.post(
                f"/api/v1/restaurants/{restaurant['id']}/outlets",
                json={
                    "name": "Second",
                    "address_line1": "2 Main Street",
                    "city": "Pune",
                    "state": "Maharashtra",
                    "postal_code": "411002",
                },
            ).json()
            other_menu = client.post(
                f"/api/v1/outlets/{other_outlet['id']}/menus",
                json={"name": "Other Menu"},
            )
            assert other_menu.status_code == 201
            outlet_menus = client.get(f"/api/v1/outlets/{outlet['id']}/menus")
            assert outlet_menus.status_code == 200
            assert [item["id"] for item in outlet_menus.json()] == [menu["id"]]
    finally:
        app.dependency_overrides.clear()
        asyncio.run(teardown())
