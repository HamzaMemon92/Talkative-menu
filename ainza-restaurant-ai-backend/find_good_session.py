import asyncio
import asyncpg

async def go():
    conn = await asyncpg.connect("postgresql://ainza:1989@127.0.0.1:5432/ainza_restaurant_e2e")
    
    # Check the session we are using
    token = "wsTO6Bt80u9jZejjbiODpPG3ijLddamsUJt-bTiL9A4"
    session = await conn.fetchrow("""
        SELECT ds.id, ds.public_session_token, ds.status, t.label, t.outlet_id,
               o.id as outlet_id2, r.name as restaurant_name
        FROM dining_sessions ds
        JOIN restaurant_tables t ON t.id = ds.table_id
        JOIN restaurant_outlets o ON o.id = t.outlet_id
        JOIN restaurants r ON r.id = o.restaurant_id
        WHERE ds.public_session_token = $1
    """, token)
    print("Session info:", dict(session) if session else "NOT FOUND")
    
    if session:
        outlet_id = session["outlet_id"]
        # Check published menus for this outlet
        menus = await conn.fetch("""
            SELECT m.id, m.name, m.status FROM menus m
            WHERE m.outlet_id = $1 OR m.restaurant_id IN (
                SELECT restaurant_id FROM restaurant_outlets WHERE id = $1
            )
        """, outlet_id)
        print(f"\nMenus for outlet {outlet_id}:")
        for m in menus:
            print(dict(m))
    
    # Also find a session that has a published menu
    print("\n--- Looking for sessions with published menus ---")
    good = await conn.fetch("""
        SELECT ds.public_session_token, t.label, o.id as outlet_id, m.name as menu_name, m.status
        FROM dining_sessions ds
        JOIN restaurant_tables t ON t.id = ds.table_id
        JOIN restaurant_outlets o ON o.id = t.outlet_id
        LEFT JOIN menus m ON (m.outlet_id = o.id OR m.restaurant_id = o.restaurant_id)
        WHERE ds.status = 'open' AND m.status = 'published'
        LIMIT 5
    """)
    for row in good:
        print(dict(row))
    
    await conn.close()

asyncio.run(go())
