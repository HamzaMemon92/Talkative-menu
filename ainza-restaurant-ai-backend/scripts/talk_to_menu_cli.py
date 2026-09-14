from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid

API_BASE = "http://127.0.0.1:8000"


def configure_utf8_console() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def post(path: str, payload: dict[str, object]) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    configure_utf8_console()
    session_token = input("Dining session token: ").strip()
    conversation = post(f"/api/v1/dining-sessions/{session_token}/ai/conversations", {})
    token = str(conversation["conversation_token"])
    print("Starting customer AI conversation...")
    while True:
        text = input("\nYOU: ").strip()
        if text.lower() in {"exit", "quit"}:
            return 0
        response = post(
            f"/api/v1/ai/conversations/{token}/messages",
            {
                "client_message_id": str(uuid.uuid4()),
                "message": text,
            },
        )
        print(f"\nAINZA: {response['assistant_message']}")
        pending = response.get("confirmation_required")
        if pending:
            answer = input("Confirm? [y/N]: ").strip().lower()
            confirmed = post(
                f"/api/v1/ai/conversations/{token}/confirmations/{pending['confirmation_token']}",
                {"confirm": answer in {"y", "yes"}},
            )
            print(f"\nAINZA: {confirmed['assistant_message']}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"))
        raise
