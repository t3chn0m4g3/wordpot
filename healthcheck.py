#!/usr/bin/env python3

import sys
import urllib.request


def main():
    with urllib.request.urlopen("http://127.0.0.1/healthz", timeout=2) as response:
        return 0 if response.status == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
