import asyncio
import asyncpg

async def go():
    conn = await asyncpg.connect("postgresql://ainza:1989@127.0.0.1:5432/ainza_restaurant_e2e")
    
    # Get first active table with QR
    rows = await conn.fetch("SELECT id, outlet_id, label, public_qr_code FROM restaurant_tables WHERE is_active = true LIMIT 5")
    print("Tables:")
    for r in rows:
        print(dict(r))
    
    # Get any existing active dining sessions
    rows2 = await conn.fetch("SELECT id, table_id, public_session_token, status FROM dining_sessions WHERE status = 'ACTIVE' LIMIT 3")
    print("\nActive sessions:")
    for r in rows2:
        print(dict(r))
    
    await conn.close()

asyncio.run(go())
