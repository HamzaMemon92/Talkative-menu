import httpx
import asyncio
import uuid

SESSION_TOKEN = "wsTO6Bt80u9jZejjbiODpPG3ijLddamsUJt-bTiL9A4"
API = "http://localhost:8000"

async def main():
    async with httpx.AsyncClient(base_url=API, timeout=60.0) as c:
        # 1. Create conversation
        print("Creating conversation...")
        r = await c.post(f"/api/v1/dining-sessions/{SESSION_TOKEN}/ai/conversations")
        r.raise_for_status()
        conv_token = r.json()["conversation_token"]
        print(f"Conversation: {conv_token[:16]}...")

        # 2. Send a casual message (no tools needed, fast)
        print("\nStreaming 'hi'...")
        async with c.stream(
            "POST",
            f"/api/v1/ai/conversations/{conv_token}/messages/stream",
            json={"client_message_id": str(uuid.uuid4()), "message": "hi"}
        ) as r:
            print(f"Status: {r.status_code}")
            async for line in r.aiter_lines():
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data:
                        print(f"  EVENT: {data[:120]}")

asyncio.run(main())
