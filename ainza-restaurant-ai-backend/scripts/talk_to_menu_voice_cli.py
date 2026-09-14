from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API_BASE = "http://127.0.0.1:8000"


def post_wav(conversation_token: str, wav_path: Path) -> dict[str, object]:
    request = urllib.request.Request(
        f"{API_BASE}/api/v1/ai/conversations/{conversation_token}/voice/transcriptions",
        data=wav_path.read_bytes(),
        headers={"Content-Type": "audio/wav"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=360) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(path: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=360) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send a WAV voice message through the FastAPI backend."
    )
    parser.add_argument("--conversation-token", required=True)
    parser.add_argument("--wav", type=Path, required=True)
    args = parser.parse_args()
    if not args.wav.is_file():
        parser.error("--wav must reference an existing WAV file")
    result = post_wav(args.conversation_token, args.wav)
    transcript = result["transcript"]
    message = str(transcript["text"])
    print("\n================================")
    print("YOU SAID")
    print("================================")
    print(message)
    answer = input("\nSend this message? [Y/e/N]: ").strip().casefold()
    if answer == "e":
        message = input("Corrected message: ").strip()
        if not message:
            print("Discarded.")
            return 0
    elif answer not in {"", "y", "yes"}:
        print("Discarded.")
        return 0
    result = post_json(
        f"/api/v1/ai/conversations/{args.conversation_token}/messages",
        {"client_message_id": str(uuid.uuid4()), "message": message},
    )
    print("\n================================")
    print("AINZA")
    print("================================")
    print(result["assistant_message"])
    pending = result.get("confirmation_required")
    if pending:
        answer = input("Confirm? [y/N]: ").strip().casefold()
        confirmed = post_json(
            "/api/v1/ai/conversations/"
            f"{args.conversation_token}/confirmations/{pending['confirmation_token']}",
            {"confirm": answer in {"y", "yes"}},
        )
        print(f"AINZA: {confirmed['assistant_message']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        raise
