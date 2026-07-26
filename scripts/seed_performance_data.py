#!/usr/bin/env python3
"""Deterministically seed current analysis results for the performance protocol."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

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


async def seed(database_url: str, rows: int) -> None:
    if rows <= 0:
        raise SystemExit("rows must be positive")
    database_name = urlparse(database_url).path.removeprefix("/")
    if not database_name.endswith("_perf"):
        raise SystemExit("performance database name must end with _perf")
    engine = create_async_engine(database_url, pool_pre_ping=True)
    analyzed_at = datetime.now(UTC)
    expires_at = analyzed_at + timedelta(days=365)
    batch_size = 1000
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE analysis_outbox, analysis_result, video_declaration, "
                    "video_metadata, analysis_attempt, analysis_target, "
                    "installation_token CASCADE"
                )
            )
            for offset in range(0, rows, batch_size):
                chunk = min(batch_size, rows - offset)
                targets = []
                results = []
                metadata_rows = []
                for index in range(offset, offset + chunk):
                    bvid = make_bvid(index)
                    cid = 1 + (index % 7)
                    targets.append(
                        {
                            "bvid": bvid,
                            "cid": cid,
                            "desired_analysis_version": "v1",
                            "write_generation": 1,
                        }
                    )
                    results.append(
                        {
                            "bvid": bvid,
                            "cid": cid,
                            "score": 10 + (index % 90),
                            "label": ("none", "light", "medium", "high")[index % 4],
                            "confidence": 0.4 + ((index % 60) / 100),
                            "evidence": "[]",
                            "analysis_version": "v1",
                            "analyzed_at": analyzed_at,
                            "analysis_expires_at": expires_at,
                        }
                    )
                    metadata_rows.append(
                        {
                            "bvid": bvid,
                            "default_cid": cid,
                            "checked_at": analyzed_at,
                        }
                    )
                await connection.execute(
                    text(
                        "INSERT INTO analysis_target "
                        "(bvid, cid, desired_analysis_version, write_generation) "
                        "VALUES (:bvid, :cid, :desired_analysis_version, :write_generation) "
                        "ON CONFLICT (bvid, cid) DO UPDATE SET "
                        "desired_analysis_version = EXCLUDED.desired_analysis_version, "
                        "write_generation = EXCLUDED.write_generation, updated_at = now()"
                    ),
                    targets,
                )
                await connection.execute(
                    text(
                        "INSERT INTO analysis_result "
                        "(bvid, cid, score, label, confidence, evidence_json, analysis_version, "
                        "analyzed_at, analysis_expires_at) VALUES "
                        "(:bvid, :cid, :score, :label, :confidence, CAST(:evidence AS jsonb), "
                        ":analysis_version, :analyzed_at, :analysis_expires_at) "
                        "ON CONFLICT (bvid, cid) DO UPDATE SET "
                        "score = EXCLUDED.score, label = EXCLUDED.label, "
                        "confidence = EXCLUDED.confidence, evidence_json = EXCLUDED.evidence_json, "
                        "analysis_version = EXCLUDED.analysis_version, "
                        "analyzed_at = EXCLUDED.analyzed_at, "
                        "analysis_expires_at = EXCLUDED.analysis_expires_at, updated_at = now()"
                    ),
                    results,
                )
                await connection.execute(
                    text(
                        "INSERT INTO video_metadata (bvid, default_cid, checked_at) "
                        "VALUES (:bvid, :default_cid, :checked_at) "
                        "ON CONFLICT (bvid) DO UPDATE SET "
                        "default_cid = EXCLUDED.default_cid, checked_at = EXCLUDED.checked_at"
                    ),
                    metadata_rows,
                )
            result_count = await connection.scalar(text("SELECT COUNT(*) FROM analysis_result"))
            metadata_count = await connection.scalar(text("SELECT COUNT(*) FROM video_metadata"))
    finally:
        await engine.dispose()

    print(f"analysis_result_rows={result_count}")
    print(f"video_metadata_rows={metadata_count}")
    if int(result_count or 0) != rows or int(metadata_count or 0) != rows:
        raise SystemExit("seed did not produce the exact requested row counts")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--rows", type=int, default=100_000)
    args = parser.parse_args()
    asyncio.run(seed(args.database_url, args.rows))


if __name__ == "__main__":
    main()
