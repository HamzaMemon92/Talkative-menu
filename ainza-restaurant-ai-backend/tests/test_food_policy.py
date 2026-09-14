import asyncio

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.db.base import Base
from ainza_restaurant.db.session import get_db_session
from ainza_restaurant.main import app


def test_outlet_food_policy_requires_confirmation_and_is_one_to_one() -> None:
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
            restaurant = client.post("/api/v1/restaurants", json={"name": "Policy Cafe"}).json()
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
            path = f"/api/v1/outlets/{outlet['id']}/food-policy"
            assert client.put(path, json={"halal_status": "halal"}).status_code == 422
            response = client.put(
                path,
                json={
                    "halal_status": "halal",
                    "halal_certification_status": "unknown",
                    "pork_policy": "not_served",
                    "alcohol_policy": "unknown",
                    "confirmation": True,
                },
            )
            assert response.status_code == 200
            assert response.json()["halal_status"] == "halal"
            assert response.json()["confirmed"] is True
            assert client.get(path).json()["pork_policy"] == "not_served"
            updated = client.put(path, json={"confirmation": True}).json()
            assert updated["halal_status"] == "unknown"
    finally:
        app.dependency_overrides.clear()
        asyncio.run(teardown())
