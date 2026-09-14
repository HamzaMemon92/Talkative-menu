import asyncio
import os
import sys
import subprocess

# Ensure src/ is in the python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from sqlalchemy import select
from ainza_restaurant.database import async_session_maker
from ainza_restaurant.restaurants.models import RestaurantTable
from ainza_restaurant.dining.models import DiningSession
from ainza_restaurant.domain.enums import DiningSessionStatus

async def main():
    print("Setting up a dining session...")
    async with async_session_maker() as session:
        # Find any table
        result = await session.execute(select(RestaurantTable).limit(1))
        table = result.scalar_one_or_none()
        
        if not table:
            print("No tables found in database. Cannot create dining session.")
            return

        # Check for active session, or create one
        result = await session.execute(
            select(DiningSession)
            .where(DiningSession.table_id == table.id)
            .where(DiningSession.status == DiningSessionStatus.ACTIVE)
        )
        ds = result.scalar_one_or_none()

        if not ds:
            ds = DiningSession(
                table_id=table.id,
                outlet_id=table.outlet_id,
                restaurant_id=table.restaurant_id,
                pax=2,
                status=DiningSessionStatus.ACTIVE
            )
            session.add(ds)
            await session.commit()
            
        token = ds.token
        print(f"✅ Session Token ready: {token}")

        print("Starting Chainlit UI...")
        
        # Clear DATABASE_URL to avoid asyncpg configuration error in Chainlit
        env = os.environ.copy()
        if "DATABASE_URL" in env:
            del env["DATABASE_URL"]
            
        env["AINZA_API_URL"] = "http://localhost:8000"
        env["AINZA_SESSION_TOKEN"] = token

        # Run chainlit
        process = subprocess.Popen(
            [".venv\\Scripts\\chainlit", "run", "ui\\chainlit_app.py", "--port", "8001"],
            env=env
        )
        process.wait()

if __name__ == "__main__":
    asyncio.run(main())
