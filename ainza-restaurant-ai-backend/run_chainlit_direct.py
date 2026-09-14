import asyncio
import asyncpg
import subprocess
import os

async def main():
    print("Connecting to DB to get a table ID...")
    conn = await asyncpg.connect("postgresql://ainza:1989@127.0.0.1:5432/ainza_restaurant_e2e")
    
    # Get a table ID
    table_id = await conn.fetchval("SELECT id FROM restaurant_tables LIMIT 1")
    if not table_id:
        print("No tables found!")
        return
        
    print(f"Found table: {table_id}")
    
    # Check for active session
    token = await conn.fetchval(
        "SELECT token FROM dining_sessions WHERE table_id = $1 AND status = 'ACTIVE' LIMIT 1",
        table_id
    )
    
    if not token:
        print("Creating new session via API is harder, let's just insert one.")
        outlet_id = await conn.fetchval("SELECT outlet_id FROM restaurant_tables WHERE id = $1", table_id)
        restaurant_id = await conn.fetchval("SELECT restaurant_id FROM restaurant_tables WHERE id = $1", table_id)
        
        await conn.execute("""
            INSERT INTO dining_sessions (id, token, table_id, outlet_id, restaurant_id, pax, status, created_at, updated_at)
            VALUES (gen_random_uuid(), gen_random_uuid(), $1, $2, $3, 2, 'ACTIVE', now(), now())
        """, table_id, outlet_id, restaurant_id)
        
        token = await conn.fetchval(
            "SELECT token FROM dining_sessions WHERE table_id = $1 AND status = 'ACTIVE' LIMIT 1",
            table_id
        )
        
    await conn.close()
    
    print(f"✅ Session Token ready: {token}")

    print("Starting Chainlit UI...")
    
    # Clear DATABASE_URL to avoid asyncpg configuration error in Chainlit
    env = os.environ.copy()
    if "DATABASE_URL" in env:
        del env["DATABASE_URL"]
        
    env["AINZA_API_URL"] = "http://localhost:8000"
    env["AINZA_SESSION_TOKEN"] = str(token)

    # Run chainlit
    process = subprocess.Popen(
        [".venv\\Scripts\\chainlit", "run", "ui\\chainlit_app.py", "--port", "8001"],
        env=env
    )
    process.wait()

if __name__ == "__main__":
    asyncio.run(main())
