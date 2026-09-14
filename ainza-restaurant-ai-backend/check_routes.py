import httpx
import asyncio

async def main():
    async with httpx.AsyncClient(base_url="http://localhost:8000") as c:
        r = await c.get("/openapi.json")
        paths = r.json().get("paths", {})
        print("Routes with 'message' or 'stream':")
        for path in paths:
            if "message" in path or "stream" in path:
                print(" ", path)
        print("\nAll AI routes:")
        for path in paths:
            if "/ai/" in path:
                print(" ", path)

asyncio.run(main())
