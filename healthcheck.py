#!/usr/bin/env python3

import sys
import urllib.request


def main():
    request = urllib.request.Request(
        "http://127.0.0.1/healthz",
        headers={"X-Wordpot-Healthcheck": "1"},
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        return 0 if response.status == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
