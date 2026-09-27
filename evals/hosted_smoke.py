"""Unauthenticated hosted smoke; never uses or logs a user session."""
import argparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


def status(url: str, method: str = "GET") -> int:
    try:
        with urlopen(Request(url, method=method), timeout=20) as response:
            return response.status
    except HTTPError as error:
        return error.code


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="https://focusos-api.vercel.app")
    parser.add_argument("--web", default="https://focusos-web-five.vercel.app")
    args = parser.parse_args()
    run_id = uuid4()
    checks = [
        (args.api + "/health", "GET", 200),
        (args.web + "/agent", "GET", 200),
        (args.web + "/api/me", "GET", 401),
        (args.web + f"/api/agent/runs/{run_id}/audit", "GET", 401),
        (args.web + "/api/connections/google", "DELETE", 401),
        (args.web + f"/api/sources/{run_id}", "DELETE", 401),
        (args.api + f"/approvals/{run_id}/execute", "POST", 401),
    ]
    failed = False
    for url, method, expected in checks:
        observed = status(url, method)
        print(f"{method} {url}: {observed} (expected {expected})")
        failed |= observed != expected
    if failed:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
