#!/usr/bin/env python3
"""Closed-loop cached-query performance protocol over the HTTPS reverse proxy."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import ssl
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def make_bvid(index: int) -> str:
    value = index
    chars = ["1"] * 10
    for position in range(9, -1, -1):
        chars[position] = ALPHABET[value % len(ALPHABET)]
        value //= len(ALPHABET)
    return "BV" + "".join(chars)


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return math.inf
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(ratio * len(ordered)) - 1))
    return ordered[index]


@dataclass(slots=True)
class RunStats:
    name: str
    latencies_ms: list[float]
    successes: int
    failures: int
    elapsed_seconds: float

    def as_json(self) -> dict[str, float | int | str]:
        total = self.successes + self.failures
        return {
            "name": self.name,
            "successes": self.successes,
            "failures": self.failures,
            "error_rate": (self.failures / total) if total else 1.0,
            "throughput_rps": (
                self.successes / self.elapsed_seconds if self.elapsed_seconds else 0.0
            ),
            "p50_ms": percentile(self.latencies_ms, 0.50),
            "p95_ms": percentile(self.latencies_ms, 0.95),
            "p99_ms": percentile(self.latencies_ms, 0.99),
            "mean_ms": statistics.fmean(self.latencies_ms) if self.latencies_ms else math.inf,
            "elapsed_seconds": self.elapsed_seconds,
        }


def check_environment(cpu_target: int, memory_gb_target: int) -> dict[str, float | int]:
    cpu_count = os.cpu_count() or 0
    memory_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    memory_gb = memory_bytes / (1024**3)
    if cpu_count < cpu_target:
        raise SystemExit(f"host has {cpu_count} CPUs; need at least {cpu_target}")
    if memory_gb + 0.1 < memory_gb_target:
        raise SystemExit(f"host has {memory_gb:.2f} GB RAM; need at least {memory_gb_target}")
    return {"cpu_count": cpu_count, "memory_gb": round(memory_gb, 2)}


async def verify_rows(database_url: str, expected_rows: int) -> None:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            result_count = int(
                await connection.scalar(text("SELECT COUNT(*) FROM analysis_result")) or 0
            )
            metadata_count = int(
                await connection.scalar(text("SELECT COUNT(*) FROM video_metadata")) or 0
            )
    finally:
        await engine.dispose()
    if result_count != expected_rows or metadata_count != expected_rows:
        raise SystemExit(
            f"expected exactly {expected_rows} seeded rows, "
            f"got results={result_count} metadata={metadata_count}"
        )


async def closed_loop(
    *,
    name: str,
    client: httpx.AsyncClient,
    token: str,
    connections: int,
    warm_seconds: float,
    measure_seconds: float,
    request_factory,
) -> RunStats:
    stop_at = 0.0
    measure = False
    latencies: list[float] = []
    successes = 0
    failures = 0
    counter = 0
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal counter, successes, failures
        while time.perf_counter() < stop_at:
            async with lock:
                index = counter
                counter += 1
            path, payload = request_factory(index)
            started = time.perf_counter()
            try:
                if payload is None:
                    response = await client.get(
                        path,
                        headers={"Authorization": f"Bearer {token}"},
                    )
                else:
                    response = await client.post(
                        path,
                        headers={"Authorization": f"Bearer {token}"},
                        json=payload,
                    )
                ok = response.status_code == 200
            except Exception:
                ok = False
            elapsed_ms = (time.perf_counter() - started) * 1000
            if not measure:
                continue
            if ok:
                successes += 1
                latencies.append(elapsed_ms)
            else:
                failures += 1

    async def run_phase(seconds: float, counting: bool) -> float:
        nonlocal stop_at, measure
        measure = counting
        stop_at = time.perf_counter() + seconds
        phase_started = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(connections)))
        return time.perf_counter() - phase_started

    await run_phase(warm_seconds, counting=False)
    elapsed = await run_phase(measure_seconds, counting=True)
    return RunStats(name, latencies, successes, failures, elapsed)


def single_factory(index: int) -> tuple[str, None]:
    seeded_index = index % 100_000
    bvid = make_bvid(seeded_index)
    cid = 1 + (seeded_index % 7)
    return f"/api/v1/analyses/{bvid}?cid={cid}", None


def batch_factory(index: int) -> tuple[str, dict[str, list[str]]]:
    start = (index * 30) % 100_000
    bvids = [make_bvid((start + offset) % 100_000) for offset in range(30)]
    return "/api/v1/analyses/batch", {"bvids": bvids}


async def main_async(args: argparse.Namespace) -> None:
    parsed = urlparse(args.base_url)
    if parsed.scheme != "https":
        raise SystemExit("performance protocol requires an https --base-url")
    host_info = check_environment(args.cpu_target, args.memory_gb_target)
    await verify_rows(args.database_url, args.expected_rows)

    output_dir = Path(args.output_dir)
    await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)
    verify: bool | ssl.SSLContext = (
        ssl.create_default_context(cafile=args.ca_cert) if args.ca_cert else True
    )
    async with httpx.AsyncClient(
        base_url=args.base_url,
        verify=verify,
        timeout=30.0,
        trust_env=False,
    ) as client:
        single = await closed_loop(
            name="cached_single",
            client=client,
            token=args.token,
            connections=args.connections,
            warm_seconds=args.warm_seconds,
            measure_seconds=args.measure_seconds,
            request_factory=single_factory,
        )
        batch = await closed_loop(
            name="cached_batch_30",
            client=client,
            token=args.token,
            connections=args.connections,
            warm_seconds=args.warm_seconds,
            measure_seconds=args.measure_seconds,
            request_factory=batch_factory,
        )

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "host": host_info,
        "target_environment": {
            "cpu_target": args.cpu_target,
            "memory_gb_target": args.memory_gb_target,
        },
        "protocol": {
            "connections": args.connections,
            "warm_seconds": args.warm_seconds,
            "measure_seconds": args.measure_seconds,
            "expected_rows": args.expected_rows,
        },
        "runs": [single.as_json(), batch.as_json()],
    }
    path = output_dir / f"perf-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(path)
    print(json.dumps(report, indent=2))

    for run in (single, batch):
        stats = run.as_json()
        if int(stats["successes"]) < args.min_successes:
            raise SystemExit(f"{run.name} successes below {args.min_successes}")
        if float(stats["p95_ms"]) >= args.p95_budget_ms:
            raise SystemExit(f"{run.name} p95 {stats['p95_ms']} ms exceeds budget")
        if float(stats["error_rate"]) >= args.error_budget:
            raise SystemExit(f"{run.name} error rate {stats['error_rate']} exceeds budget")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--ca-cert", default=None)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--expected-rows", type=int, default=100_000)
    parser.add_argument("--token", default=os.getenv("PERF_INSTALLATION_TOKEN"))
    parser.add_argument("--connections", type=int, default=20)
    parser.add_argument("--warm-seconds", type=float, default=30)
    parser.add_argument("--measure-seconds", type=float, default=300)
    parser.add_argument("--min-successes", type=int, default=1000)
    parser.add_argument("--p95-budget-ms", type=float, default=500)
    parser.add_argument("--error-budget", type=float, default=0.01)
    parser.add_argument("--cpu-target", type=int, default=4)
    parser.add_argument("--memory-gb-target", type=int, default=8)
    parser.add_argument("--output-dir", default="artifacts/performance")
    args = parser.parse_args()
    if not args.token:
        parser.error("--token or PERF_INSTALLATION_TOKEN is required")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
