import asyncio
import asyncpg

async def go():
    conn = await asyncpg.connect("postgresql://ainza:1989@127.0.0.1:5432/ainza_restaurant_e2e")
    rows = await conn.fetch("SELECT id, table_id, public_session_token, status, opened_at FROM dining_sessions ORDER BY opened_at DESC LIMIT 10")
    print("All recent sessions:")
    for r in rows:
        print(dict(r))
    await conn.close()

asyncio.run(go())
