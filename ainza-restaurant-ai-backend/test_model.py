import httpx
import asyncio
import json

import os

API_KEY = os.environ.get("GEMINI_API_KEY", "your-api-key-here")
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
MODEL = "gemini-3.6-flash"

async def test():
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Say hello in 5 words"}],
        "max_tokens": 50
    }
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload)
        print(f"Status: {r.status_code}")
        print(f"Body: {r.text[:500]}")

asyncio.run(test())
