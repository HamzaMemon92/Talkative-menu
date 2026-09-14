from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from ainza_restaurant.core.config import get_settings

DEFAULT_API_BASE = "http://127.0.0.1:8000"


def configure_utf8_console() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def request_json(
    method: str,
    api_base: str,
    path: str,
    payload: dict[str, object] | None = None,
    *,
    timeout_seconds: int,
) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{api_base}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"backend returned {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"AI request failed: {exc.reason}") from exc


class WaitingIndicator:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        print("AI is thinking...", flush=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        elapsed = 0
        while not self._stop.wait(10):
            elapsed += 10
            print(f"AI is thinking... {elapsed}s", flush=True)


def display_response(response: dict[str, object], elapsed: float) -> None:
    print(f"\nAI > {response['assistant_message']}")
    tools = response.get("tools_used")
    if tools:
        print(f"[debug] tools: {', '.join(str(tool) for tool in tools)}")
    else:
        print("[debug] tools: none")
    print(f"[debug] response time: {elapsed:.1f}s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Human free-form Talkative Menu client.")
    parser.add_argument("--state-file", default="tmp/human_typed_test.json")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    args = parser.parse_args()
    configure_utf8_console()
    try:
        state = json.loads(Path(args.state_file).read_text(encoding="utf-8"))
        conversation_token = str(state["conversation_token"])
    except (KeyError, OSError, ValueError) as exc:
        print(f"[ERROR] Human test state is unavailable: {exc}", file=sys.stderr)
        return 1

    api_base = args.api_base.rstrip("/")
    model_timeout = get_settings().local_llm_timeout_seconds
    # A tool-backed turn can require a tool-selection call and a final-answer call.
    request_timeout = (model_timeout * 2) + 30
    print("=" * 40)
    print("       AINZA TALKATIVE MENU")
    print("       Urban Tadka - Vesu")
    print("=" * 40)
    print("Table: T3")
    print("Mode: REAL LOCAL QWEN + REAL POSTGRESQL")
    print("Type /exit to leave.")

    while True:
        try:
            message = input("\nYOU > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if message.casefold() == "/exit":
            return 0
        if not message:
            continue

        client_message_id = str(uuid.uuid4())
        started = time.monotonic()
        indicator = WaitingIndicator()
        indicator.start()
        try:
            response = request_json(
                "POST",
                api_base,
                f"/api/v1/ai/conversations/{conversation_token}/messages",
                {"client_message_id": client_message_id, "message": message},
                timeout_seconds=request_timeout,
            )
        except RuntimeError as exc:
            indicator.stop()
            message_text = str(exc)
            if "ai_model_unavailable" in message_text:
                print("[ERROR] Local Qwen server became unreachable.")
            elif "timed out" in message_text.casefold():
                print(f"[ERROR] Local AI did not finish within {model_timeout}s.")
            else:
                print(f"[ERROR] {message_text}")
            continue
        indicator.stop()
        display_response(response, time.monotonic() - started)

        pending = response.get("confirmation_required")
        if isinstance(pending, dict):
            answer = input("Confirm? [y/N]: ").strip().casefold()
            if answer not in {"y", "yes"}:
                print("AI > No action was confirmed.")
                continue
            started = time.monotonic()
            try:
                confirmed = request_json(
                    "POST",
                    api_base,
                    "/api/v1/ai/conversations/"
                    f"{conversation_token}/confirmations/{pending['confirmation_token']}",
                    {"confirm": True},
                    timeout_seconds=request_timeout,
                )
            except RuntimeError as exc:
                print(f"[ERROR] {exc}")
                continue
            print(f"\nAI > {confirmed['assistant_message']}")
            print(f"[debug] confirmation response time: {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    raise SystemExit(main())
