#!/usr/bin/env python3
"""
Load sketch: 100 check-in attempts in ~5 minutes (challenge-only storm).

This does NOT fabricate GPS/QR/signatures for real ACCEPTED events.
It measures API capacity for /attendance/challenge under concurrent clients.

Usage:
  export API_BASE=http://localhost:8000
  export EMPLOYEE_TOKEN=...
  export DEVICE_ID=...
  python scripts/load_test_checkins.py --count 100 --concurrency 10
"""

from __future__ import annotations

import argparse
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx


def one_challenge(client: httpx.Client, base: str, token: str, device_id: str) -> float:
    t0 = time.perf_counter()
    r = client.post(
        f"{base}/api/v1/attendance/challenge",
        headers={"Authorization": f"Bearer {token}"},
        json={"device_id": device_id, "purpose": "check_in"},
        timeout=30.0,
    )
    elapsed = time.perf_counter() - t0
    if r.status_code not in (200, 400, 429):
        raise RuntimeError(f"unexpected {r.status_code}: {r.text[:200]}")
    return elapsed


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=100)
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--base", default=os.environ.get("API_BASE", "http://localhost:8000"))
    args = p.parse_args()
    token = os.environ.get("EMPLOYEE_TOKEN")
    device_id = os.environ.get("DEVICE_ID")
    if not token or not device_id:
        print("Set EMPLOYEE_TOKEN and DEVICE_ID")
        return 2

    latencies: list[float] = []
    errors = 0
    t_start = time.perf_counter()
    with httpx.Client() as client:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futs = [
                pool.submit(one_challenge, client, args.base.rstrip("/"), token, device_id)
                for _ in range(args.count)
            ]
            for fut in as_completed(futs):
                try:
                    latencies.append(fut.result())
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    print("ERR", exc)
    total = time.perf_counter() - t_start
    ok = len(latencies)
    print(f"completed={ok} errors={errors} wall_s={total:.2f}")
    if latencies:
        print(
            f"latency_ms p50={statistics.median(latencies)*1000:.0f} "
            f"p95={statistics.quantiles(latencies, n=20)[18]*1000:.0f} "
            f"max={max(latencies)*1000:.0f}"
        )
    # Target from plan: 100 check-ins in 5 minutes → wall < 300s for this storm
    if total > 300:
        print("WARN: exceeded 5 minute wall clock for challenge storm")
        return 1
    print("OK: finished within 5 minutes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
