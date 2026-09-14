import asyncio
import httpx
import os
import subprocess
import json

QR_CODE = "yAhvJtN4Oycra-Pjbv6c6AmzwUjHJq3pNRXEWXh9FVM"  # Table T1
API_URL = "http://localhost:8000"

async def main():
    print("Creating or resolving dining session via API...")
    async with httpx.AsyncClient(base_url=API_URL, timeout=10.0) as client:
        r = await client.post(f"/api/v1/qr/{QR_CODE}/sessions", json={"party_size": 2})
        if r.status_code == 409:
            print("Session conflict: table already has active session. Fetching QR table info...")
            qr_resp = await client.get(f"/api/v1/qr/{QR_CODE}")
            qr_data = qr_resp.json()
            data = qr_data.get("active_session") or qr_data
        else:
            r.raise_for_status()
            data = r.json()
        
    print(f"Session data: {json.dumps(data, indent=2)}")
    session_token = (
        data.get("public_session_token")
        or data.get("session_token")
        or data.get("token")
        or data.get("public_token")
        or data.get("active_session_token")
    )
    
    if not session_token:
        # Try the first key that looks like a token
        for k, v in data.items():
            if isinstance(v, str) and len(v) > 10:
                print(f"Using key '{k}' as token: {v}")
                session_token = v
                break
                
    if not session_token:
        print("ERROR: Could not find session token in response")
        return

    print(f"\n[OK] Session Token: {session_token}")
    print("Starting Chainlit UI on http://localhost:8001 ...")
    
    # Don't pass DATABASE_URL — Chainlit's asyncpg layer crashes with postgresql+asyncpg scheme
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env["AINZA_API_URL"] = API_URL
    env["AINZA_SESSION_TOKEN"] = str(session_token)

    process = subprocess.Popen(
        [".venv\\Scripts\\chainlit", "run", "ui\\chainlit_app.py", "--port", "8001"],
        env=env,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    process.wait()

if __name__ == "__main__":
    asyncio.run(main())
