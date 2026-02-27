"""
Минимальный smoke/integration сценарий для сквозной проверки API.
Запуск:
    python smoke_test.py --base-url http://localhost:8000
"""

import argparse
import json
import sys
from urllib import request


def http_json(method: str, url: str, payload: dict | None = None):
    data = None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, method=method, headers=headers)
    with request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, json.loads(body) if body else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    try:
        print("1) health")
        _, health = http_json("GET", f"{base}/health")
        print(health)

        print("2) ingest emails")
        _, ingest = http_json("POST", f"{base}/emails/ingest?limit=3&mailbox=INBOX")
        print(ingest)

        print("3) get tickets")
        _, tickets = http_json("GET", f"{base}/tickets?limit=5")
        print(f"tickets: {len(tickets)}")
        if not tickets:
            print("Нет тикетов после ingest")
            return 1

        ticket_id = tickets[0]["id"]

        print("4) patch ticket")
        _, patched = http_json(
            "PATCH",
            f"{base}/tickets/{ticket_id}",
            {"status": "drafted", "needs_attention": False},
        )
        print({"id": patched.get("id"), "status": patched.get("status")})

        print("5) save ticket to kb")
        _, kb = http_json("POST", f"{base}/tickets/{ticket_id}/save-to-kb", {})
        print(kb)
    except Exception as exc:
        print("SMOKE FAILED:", exc)
        return 1

    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

