import asyncio
import json
import httpx

async def test_system():
    print("🚀 Starting E2E test...")
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        # 1. Create a dining session
        print("\n📝 Creating dining session...")
        res = await client.post("/api/v1/dining-sessions", json={
            "table_number": "10",
            "pax": 2
        })
        res.raise_for_status()
        session_token = res.json()["token"]
        print(f"✅ Session created: {session_token}")

        # 2. Create an AI conversation
        print("\n💬 Creating AI conversation...")
        res = await client.post(f"/api/v1/dining-sessions/{session_token}/ai/conversations")
        res.raise_for_status()
        conv_token = res.json()["token"]
        print(f"✅ Conversation created: {conv_token}")

        # 3. Test streaming and parallel tools
        # We'll ask a complex question that requires multiple tool calls in parallel!
        # For example, "What is on the menu and what offers are active?"
        # That should trigger menu_search and offers_get_effective.
        prompt = "Show me the full menu and all current offers. Use your tools to look them up."
        print(f"\n🤖 Sending prompt: '{prompt}'")
        
        async with client.stream(
            "POST",
            f"/api/v1/ai/conversations/{conv_token}/messages/stream",
            json={
                "client_message_id": "test-id-1",
                "message": prompt
            },
            timeout=httpx.Timeout(60.0)
        ) as response:
            response.raise_for_status()
            print("\n📡 Streaming response:")
            
            tool_starts = []
            tool_dones = []
            
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                
                try:
                    event = json.loads(data)
                except Exception as e:
                    print(f"Error parsing JSON: {data}")
                    continue
                    
                if event["type"] == "tool_start":
                    print(f"  [Tool Start] {event['tool']}")
                    tool_starts.append(event['tool'])
                elif event["type"] == "tool_done":
                    print(f"  [Tool Done] {event['tool']} (ok={event.get('ok')})")
                    tool_dones.append(event['tool'])
                elif event["type"] == "token":
                    print(event["content"], end="", flush=True)
                elif event["type"] == "done":
                    print("\n\n✅ Stream completed.")
                    print(f"Tools used: {event.get('tools_used')}")
                elif event["type"] == "error":
                    print(f"\n❌ Stream Error: {event}")

        assert len(tool_starts) > 0, "No tools were called!"

if __name__ == "__main__":
    asyncio.run(test_system())
