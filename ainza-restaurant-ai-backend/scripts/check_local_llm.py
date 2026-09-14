from __future__ import annotations

import json
import urllib.error
import urllib.request


def main() -> int:
    url = "http://127.0.0.1:8081/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        print(f"local llama-server not ready: {exc}")
        return 1
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
