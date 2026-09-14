from __future__ import annotations

from datetime import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.db.base import Base
from ainza_restaurant.db.session import get_db_session
from ainza_restaurant.main import app
from ainza_restaurant.restaurants.domain import (
    IntervalForValidation,
    OperatingHoursError,
    validate_gstin,
    validate_weekly_intervals,
)


@pytest.fixture
def client():
    import asyncio

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def teardown():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    async def override_db():
        async with sessions() as session:
            yield session

    asyncio.run(setup())
    app.dependency_overrides[get_db_session] = override_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        asyncio.run(teardown())


def outlet_payload() -> dict[str, str]:
    return {
        "name": "Main outlet",
        "address_line1": "1 Market Street",
        "city": "Pune",
        "state": "Maharashtra",
        "postal_code": "411001",
    }


def test_split_intervals_are_valid_and_overlapping_intervals_are_rejected() -> None:
    validate_weekly_intervals(
        [
            IntervalForValidation(0, time(9), time(13)),
            IntervalForValidation(0, time(14), time(22)),
        ]
    )
    with pytest.raises(OperatingHoursError):
        validate_weekly_intervals(
            [
                IntervalForValidation(0, time(9), time(13)),
                IntervalForValidation(0, time(12), time(14)),
            ]
        )


def test_overnight_full_day_and_circular_week_overlap_are_rejected() -> None:
    with pytest.raises(OperatingHoursError):
        validate_weekly_intervals(
            [
                IntervalForValidation(0, time(22), time(2)),
                IntervalForValidation(1, time(1), time(4)),
            ]
        )
    with pytest.raises(OperatingHoursError):
        validate_weekly_intervals(
            [
                IntervalForValidation(2, None, None, is_full_day=True),
                IntervalForValidation(2, time(12), time(14)),
            ]
        )
    with pytest.raises(OperatingHoursError):
        validate_weekly_intervals(
            [
                IntervalForValidation(6, time(23), time(1)),
                IntervalForValidation(0, time(0, 30), time(2)),
            ]
        )


def test_gstin_validation_is_conservative() -> None:
    assert validate_gstin("22AAAAA0000A1Z5") == "22AAAAA0000A1Z5"
    with pytest.raises(ValueError):
        validate_gstin("22AAAAA0000A1Z")
    with pytest.raises(ValueError):
        validate_gstin("22AAAAA0000A1Z!")


def test_onboarding_readiness_and_finalization(client: TestClient) -> None:
    restaurant = client.post("/restaurants", json={"name": "Ainza Cafe"}).json()
    restaurant_id = restaurant["id"]
    outlet = client.post(f"/restaurants/{restaurant_id}/outlets", json=outlet_payload()).json()
    outlet_id = outlet["id"]

    readiness = client.get(f"/restaurants/{restaurant_id}/onboarding/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["ready"] is False
    assert len(readiness.json()["blocking_reasons"]) == 2

    hours = {
        "intervals": [
            {"weekday": 0, "opens_at": "09:00:00", "closes_at": "13:00:00"},
            {"weekday": 0, "opens_at": "14:00:00", "closes_at": "22:00:00"},
        ]
    }
    assert (
        client.put(
            f"/restaurants/{restaurant_id}/outlets/{outlet_id}/operating-hours", json=hours
        ).status_code
        == 200
    )
    tax = {
        "gstin": "22AAAAA0000A1Z5",
        "gstin_confirmed": True,
        "confirm_no_auto_tax_rates": True,
    }
    tax_response = client.put(
        f"/restaurants/{restaurant_id}/outlets/{outlet_id}/tax-profile", json=tax
    )
    assert tax_response.status_code == 200

    # Only the configured outlet is required; readiness is deterministic and
    # does not invent missing hours for other weekdays or any tax rates.
    readiness = client.get(f"/restaurants/{restaurant_id}/onboarding/status").json()
    assert readiness["ready"] is True
    finalized = client.post(
        f"/api/v1/restaurants/{restaurant_id}/onboarding/finalize",
        json={"confirm": True},
    )
    assert finalized.status_code == 200
    assert finalized.json()["restaurant"]["onboarding_status"] == "ready_for_menu"
    assert (
        client.post(
            f"/api/v1/restaurants/{restaurant_id}/onboarding/finalize",
            json={"confirm": True},
        ).status_code
        == 200
    )


def test_overlapping_hours_and_unconfirmed_gstin_are_rejected(client: TestClient) -> None:
    restaurant_id = client.post("/restaurants", json={"name": "Ainza"}).json()["id"]
    outlet_id = client.post(f"/restaurants/{restaurant_id}/outlets", json=outlet_payload()).json()[
        "id"
    ]
    bad_hours = {
        "intervals": [
            {"weekday": 0, "opens_at": "09:00:00", "closes_at": "13:00:00"},
            {"weekday": 0, "opens_at": "12:00:00", "closes_at": "14:00:00"},
        ]
    }
    assert (
        client.put(
            f"/restaurants/{restaurant_id}/outlets/{outlet_id}/operating-hours",
            json=bad_hours,
        ).status_code
        == 409
    )
    assert (
        client.put(
            f"/restaurants/{restaurant_id}/outlets/{outlet_id}/tax-profile",
            json={"gstin": "22AAAAA0000A1Z5", "confirm_no_auto_tax_rates": True},
        ).status_code
        == 422
    )


def test_v1_slug_collision_and_primary_outlet_switch(client: TestClient) -> None:
    first = client.post("/api/v1/restaurants", json={"name": "Ainza Kitchen"}).json()
    assert first["slug"] == "ainza-kitchen"
    collision = client.post("/api/v1/restaurants", json={"name": "Ainza   Kitchen"})
    assert collision.status_code == 409
    first_id = first["id"]
    outlet = client.post(
        f"/api/v1/restaurants/{first_id}/outlets",
        json={**outlet_payload(), "country": "in", "timezone": "UTC"},
    )
    assert outlet.status_code == 201
    assert outlet.json()["is_primary"] is True
    second = client.post(
        f"/api/v1/restaurants/{first_id}/outlets",
        json={**outlet_payload(), "name": "Second", "is_primary": True},
    )
    assert second.status_code == 201
    outlets = client.get(f"/api/v1/restaurants/{first_id}/outlets").json()
    assert sum(item["is_primary"] for item in outlets) == 1
    assert (
        client.patch(
            f"/api/v1/restaurants/{first_id}/outlets/{outlet.json()['id']}",
            json={"timezone": "Not/AZone"},
        ).status_code
        == 422
    )


def test_v1_tax_profile_and_finalize_require_explicit_confirmation(client: TestClient) -> None:
    restaurant = client.post("/api/v1/restaurants", json={"name": "Ready Cafe"}).json()
    restaurant_id = restaurant["id"]
    outlet = client.post(
        f"/api/v1/restaurants/{restaurant_id}/outlets", json=outlet_payload()
    ).json()
    outlet_id = outlet["id"]
    assert (
        client.put(
            f"/api/v1/restaurants/{restaurant_id}/outlets/{outlet_id}/operating-hours",
            json={"intervals": [{"weekday": 6, "opens_at": "22:00", "closes_at": "02:00"}]},
        ).status_code
        == 200
    )
    profile = {
        "legal_business_name": "Ready Cafe Private Limited",
        "restaurant_type": "other",
        "gst_registered": True,
        "gst_state_code": "22",
        "gstin": "22AAAAA0000A1Z5",
        "gstin_confirmed": True,
        "configured_tax_rate_percent": "5.00",
        "prices_include_tax": False,
        "tax_configuration_confirmed": True,
    }
    assert (
        client.put(
            f"/api/v1/restaurants/{restaurant_id}/outlets/{outlet_id}/tax-profile",
            json=profile,
        ).status_code
        == 200
    )
    assert (
        client.post(f"/api/v1/restaurants/{restaurant_id}/onboarding/finalize").status_code == 422
    )
    finalized = client.post(
        f"/api/v1/restaurants/{restaurant_id}/onboarding/finalize",
        json={"confirm": True},
    )
    assert finalized.status_code == 200
    assert finalized.json()["restaurant"]["onboarding_status"] == "ready_for_menu"


def test_hours_require_explicit_full_day_and_replacement_is_atomic(client: TestClient) -> None:
    restaurant_id = client.post("/api/v1/restaurants", json={"name": "Hours Cafe"}).json()["id"]
    outlet_id = client.post(
        f"/api/v1/restaurants/{restaurant_id}/outlets", json=outlet_payload()
    ).json()["id"]
    same_times = {"intervals": [{"weekday": 0, "opens_at": "00:00", "closes_at": "00:00"}]}
    assert (
        client.put(
            f"/api/v1/restaurants/{restaurant_id}/outlets/{outlet_id}/operating-hours",
            json=same_times,
        ).status_code
        == 422
    )
    assert (
        client.put(
            f"/api/v1/restaurants/{restaurant_id}/outlets/{outlet_id}/operating-hours",
            json={"intervals": [{"weekday": 0, "is_full_day": True}]},
        ).status_code
        == 200
    )
    bad_replacement = {
        "intervals": [
            {"weekday": 0, "opens_at": "09:00", "closes_at": "12:00"},
            {"weekday": 0, "opens_at": "11:00", "closes_at": "13:00"},
        ]
    }
    assert (
        client.put(
            f"/api/v1/restaurants/{restaurant_id}/outlets/{outlet_id}/operating-hours",
            json=bad_replacement,
        ).status_code
        == 409
    )
    hours = client.get(
        f"/api/v1/restaurants/{restaurant_id}/outlets/{outlet_id}/operating-hours"
    ).json()
    assert hours[0]["is_full_day"] is True


def test_unregistered_tax_profile_accepts_missing_rate_without_auto_assignment(
    client: TestClient,
) -> None:
    restaurant_id = client.post("/api/v1/restaurants", json={"name": "No GST Cafe"}).json()["id"]
    outlet_id = client.post(
        f"/api/v1/restaurants/{restaurant_id}/outlets", json=outlet_payload()
    ).json()["id"]

    response = client.put(
        f"/api/v1/restaurants/{restaurant_id}/outlets/{outlet_id}/tax-profile",
        json={
            "legal_business_name": "No GST Cafe",
            "restaurant_type": "other",
            "gst_registered": False,
            "prices_include_tax": False,
            "tax_configuration_confirmed": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["gstin"] is None
    assert response.json()["configured_tax_rate_percent"] is None
