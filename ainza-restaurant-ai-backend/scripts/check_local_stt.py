from __future__ import annotations

import urllib.error
import urllib.request


def main() -> int:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8082/", timeout=5) as response:
            print(f"READY: local whisper-server responded with HTTP {response.status}")
            return 0
    except urllib.error.URLError:
        print("NOT READY: local whisper-server is unavailable at http://127.0.0.1:8082")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
