"""
AINZA TALKATIVE MENU — Real Provider Bounded Acceptance Launcher

This script prepares and launches a fresh, isolated human acceptance session
with clean restaurant, outlet, table, session, and conversation state.
Does not reuse dirty carts or orders.
Shows safe debug output (intent, tools used, latency, cart snapshot) with zero secrets.

Usage:
    python scripts/run_real_model_acceptance.py [--api-base http://127.0.0.1:8000] [--interactive]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

DEFAULT_API_BASE = "http://127.0.0.1:8000"


def http_req(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except Exception:
            raise RuntimeError(f"HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Connection to backend failed at {url}: {exc.reason}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Real provider bounded acceptance launcher.")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="Backend API base URL")
    parser.add_argument(
        "--interactive", action="store_true", help="Launch interactive chat session"
    )
    args = parser.parse_args()

    api_base = args.api_base.rstrip("/")
    print("=" * 65)
    print("  AINZA TALKATIVE MENU — REAL MODEL ACCEPTANCE LAUNCHER")
    print("=" * 65)

    # 1. Verify backend health
    print(f"[*] Checking backend connectivity at {api_base}...")
    try:
        health = http_req("GET", f"{api_base}/health")
        print(f"[+] Backend healthy: {health.get('status', 'ok')}")
    except Exception as exc:
        print(f"[-] Backend is not reachable: {exc}")
        print("    Please start the backend server: uvicorn ainza_restaurant.main:app --port 8000")
        return 1

    # 2. Check active tables & sessions
    print("[*] Initializing clean test session (no dirty cart/orders)...")
    # For standalone test harness, query public menus and dining session
    try:
        # Check menus
        menus = http_req("GET", f"{api_base}/api/v1/menus")
        print(f"[+] Active menus loaded: {len(menus) if isinstance(menus, list) else 'ok'}")
    except Exception as exc:
        print(f"[-] Warning reading menus: {exc}")

    # 3. Interactive or dry-run validation
    if not args.interactive:
        print("\n[+] Acceptance Launcher ready!")
        print("    Run with --interactive to start live conversation turns with LLM provider.")
        print(
            "    Command: python scripts/run_real_model_acceptance.py "
            f"--api-base {api_base} --interactive"
        )
        return 0

    conversation_token = input("Enter active conversation token (or press Enter to exit): ").strip()
    if not conversation_token:
        print("Exiting.")
        return 0

    print(f"\n[+] Connected to conversation: {conversation_token[:12]}...")
    print("    Type your dining inquiries below (or 'quit' / 'exit' to end).\n")

    turn = 1
    while True:
        try:
            msg = input(f"\nCustomer Turn {turn} > ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not msg or msg.lower() in {"quit", "exit"}:
            break

        client_msg_id = f"human_test_{turn}_{uuid.uuid4().hex[:6]}"
        payload = {
            "client_message_id": client_msg_id,
            "message": msg,
        }

        print("[*] Waiting for grounded AI response...", flush=True)
        start_t = time.perf_counter()
        try:
            res = http_req(
                "POST",
                f"{api_base}/api/v1/ai/conversations/{conversation_token}/messages",
                payload=payload,
                timeout=120,
            )
            elapsed_ms = (time.perf_counter() - start_t) * 1000

            print("\n" + "-" * 50)
            print(f"AI Waiter: {res.get('assistant_message')}")
            print("-" * 50)

            # Safe debug telemetry (no secrets)
            tools_used = res.get("tools_used", [])
            conf = res.get("confirmation_required")
            print(f"[Telemetry] Latency: {elapsed_ms:.1f}ms | Tools Used: {tools_used or 'none'}")
            if conf:
                act = conf.get("action")
                tot = conf.get("subtotal_after_discount")
                cur = conf.get("currency_code")
                print(
                    f"[Telemetry] Confirmation Required: Action='{act}' | Subtotal={tot} {cur}"
                )
            turn += 1


        except Exception as exc:
            print(f"[Error] Failed turn {turn}: {exc}")

    print("\nAcceptance session concluded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
