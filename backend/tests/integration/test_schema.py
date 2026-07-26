import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

EXPECTED_TABLES = {
    "analysis_attempt",
    "analysis_outbox",
    "analysis_result",
    "analysis_target",
    "installation_token",
    "video_declaration",
    "video_metadata",
}
BACKEND_ROOT = Path(__file__).parents[2]


def _test_database_url() -> str:
    database_url = os.getenv("BILI_AI_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("BILI_AI_TEST_DATABASE_URL is required for PostgreSQL integration tests")

    database_name = urlparse(database_url).path.removeprefix("/")
    if not database_name.endswith("_test"):
        pytest.fail("BILI_AI_TEST_DATABASE_URL database name must end with '_test'")
    return database_url


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[str]:
    database_url = _test_database_url()
    config = _alembic_config(database_url)

    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield database_url
    command.downgrade(config, "base")
    command.upgrade(config, "head")


async def _query(
    database_url: str,
    statement: str,
    parameters: dict[str, object] | None = None,
) -> list[dict[str, Any]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(statement), parameters or {})
            return [dict(row) for row in result.mappings()]
    finally:
        await engine.dispose()


async def _expect_integrity_error(
    connection: AsyncConnection,
    statement: str,
    parameters: dict[str, object],
) -> None:
    try:
        async with connection.begin_nested():
            await connection.execute(text(statement), parameters)
    except IntegrityError:
        return
    pytest.fail("PostgreSQL accepted data that should violate a schema constraint")


def test_postgresql_16_and_required_schema_exist(migrated_database: str) -> None:
    async def inspect_schema() -> tuple[int, set[str], dict[str, str], set[str], set[str]]:
        engine = create_async_engine(migrated_database)
        try:
            async with engine.connect() as connection:
                version = int(await connection.scalar(text("SHOW server_version_num")) or 0)
                tables = {
                    row["tablename"]
                    for row in (
                        await connection.execute(
                            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                        )
                    ).mappings()
                }
                column_rows = (
                    await connection.execute(
                        text(
                            "SELECT table_name, column_name, data_type, udt_name "
                            "FROM information_schema.columns "
                            "WHERE table_schema = 'public'"
                        )
                    )
                ).mappings()
                columns = {
                    f"{row['table_name']}.{row['column_name']}": str(
                        row["udt_name"] if row["data_type"] == "USER-DEFINED" else row["data_type"]
                    )
                    for row in column_rows
                }
                constraints = {
                    row["conname"]
                    for row in (
                        await connection.execute(
                            text(
                                "SELECT conname FROM pg_constraint "
                                "WHERE connamespace = 'public'::regnamespace"
                            )
                        )
                    ).mappings()
                }
                indexes = {
                    row["indexname"]
                    for row in (
                        await connection.execute(
                            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
                        )
                    ).mappings()
                }
                return version, tables, columns, constraints, indexes
        finally:
            await engine.dispose()

    version, tables, columns, constraints, indexes = asyncio.run(inspect_schema())

    assert version // 10000 == 16
    assert tables >= EXPECTED_TABLES
    assert columns["analysis_result.evidence_json"] == "jsonb"
    assert columns["video_declaration.evidence"] == "jsonb"
    assert columns["analysis_result.analyzed_at"] == "timestamp with time zone"
    assert {
        "fk_analysis_attempt_target",
        "fk_analysis_outbox_attempt",
        "fk_analysis_result_target",
        "fk_analysis_target_owner_attempt",
        "fk_video_declaration_target",
        "uq_analysis_outbox_delivery_key",
        "uq_installation_token_hash",
    } <= constraints
    assert {
        "uq_analysis_attempt_active_version",
        "ix_analysis_attempt_recovery_lease",
        "ix_analysis_attempt_retry_after",
        "ix_analysis_outbox_pending",
    } <= indexes


def test_partial_active_attempt_and_owner_fencing(migrated_database: str) -> None:
    async def exercise() -> None:
        engine = create_async_engine(migrated_database)
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    attempt_id = uuid4()
                    await connection.execute(
                        text(
                            "INSERT INTO analysis_target "
                            "(bvid, cid, desired_analysis_version, write_generation) "
                            "VALUES (:bvid, :cid, :version, 1)"
                        ),
                        {"bvid": "BV1schema", "cid": 101, "version": "v1"},
                    )
                    await connection.execute(
                        text(
                            "INSERT INTO analysis_attempt "
                            "(attempt_id, bvid, cid, analysis_version, generation, status) "
                            "VALUES (:attempt_id, :bvid, :cid, :version, 1, 'queued')"
                        ),
                        {
                            "attempt_id": attempt_id,
                            "bvid": "BV1schema",
                            "cid": 101,
                            "version": "v1",
                        },
                    )
                    await connection.execute(
                        text(
                            "UPDATE analysis_target SET owner_attempt_id = :attempt_id "
                            "WHERE bvid = :bvid AND cid = :cid"
                        ),
                        {"attempt_id": attempt_id, "bvid": "BV1schema", "cid": 101},
                    )
                    await _expect_integrity_error(
                        connection,
                        "INSERT INTO analysis_attempt "
                        "(attempt_id, bvid, cid, analysis_version, generation, status) "
                        "VALUES (:attempt_id, :bvid, :cid, :version, 2, 'analyzing')",
                        {
                            "attempt_id": uuid4(),
                            "bvid": "BV1schema",
                            "cid": 101,
                            "version": "v1",
                        },
                    )
                    await connection.execute(
                        text(
                            "INSERT INTO analysis_attempt "
                            "(attempt_id, bvid, cid, analysis_version, generation, status) "
                            "VALUES (:attempt_id, :bvid, :cid, :version, 2, 'completed')"
                        ),
                        {
                            "attempt_id": uuid4(),
                            "bvid": "BV1schema",
                            "cid": 101,
                            "version": "v1",
                        },
                    )
                    owner = await connection.scalar(
                        text(
                            "SELECT owner_attempt_id FROM analysis_target "
                            "WHERE bvid = :bvid AND cid = :cid"
                        ),
                        {"bvid": "BV1schema", "cid": 101},
                    )
                    assert owner == attempt_id
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_outbox_delivery_key_and_check_constraints(migrated_database: str) -> None:
    async def exercise() -> None:
        engine = create_async_engine(migrated_database)
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    attempt_id = uuid4()
                    event_id = uuid4()
                    await connection.execute(
                        text(
                            "INSERT INTO analysis_target "
                            "(bvid, cid, desired_analysis_version, write_generation) "
                            "VALUES ('BV1outbox', 202, 'v1', 1)"
                        )
                    )
                    await connection.execute(
                        text(
                            "INSERT INTO analysis_attempt "
                            "(attempt_id, bvid, cid, analysis_version, generation, status) "
                            "VALUES (:attempt_id, 'BV1outbox', 202, 'v1', 1, 'queued')"
                        ),
                        {"attempt_id": attempt_id},
                    )
                    await connection.execute(
                        text(
                            "INSERT INTO analysis_outbox "
                            "(event_id, attempt_id, generation, dispatch_epoch) "
                            "VALUES (:event_id, :attempt_id, 1, 0)"
                        ),
                        {"event_id": event_id, "attempt_id": attempt_id},
                    )
                    await _expect_integrity_error(
                        connection,
                        "INSERT INTO analysis_outbox "
                        "(event_id, attempt_id, generation, dispatch_epoch) "
                        "VALUES (:event_id, :attempt_id, 1, 0)",
                        {"event_id": uuid4(), "attempt_id": attempt_id},
                    )
                    await connection.execute(
                        text(
                            "INSERT INTO analysis_outbox "
                            "(event_id, attempt_id, generation, dispatch_epoch) "
                            "VALUES (:event_id, :attempt_id, 1, 1)"
                        ),
                        {"event_id": uuid4(), "attempt_id": attempt_id},
                    )
                    await _expect_integrity_error(
                        connection,
                        "INSERT INTO analysis_attempt "
                        "(attempt_id, bvid, cid, analysis_version, generation, status) "
                        "VALUES (:attempt_id, 'BV1outbox', 202, 'v2', 0, 'queued')",
                        {"attempt_id": uuid4()},
                    )
                    await _expect_integrity_error(
                        connection,
                        "INSERT INTO analysis_attempt "
                        "(attempt_id, bvid, cid, analysis_version, generation, status) "
                        "VALUES (:attempt_id, 'BV1outbox', 202, 'v2', 2, 'invalid')",
                        {"attempt_id": uuid4()},
                    )
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_result_declaration_and_metadata_constraints(migrated_database: str) -> None:
    async def exercise() -> None:
        engine = create_async_engine(migrated_database)
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    await connection.execute(
                        text(
                            "INSERT INTO analysis_target "
                            "(bvid, cid, desired_analysis_version, write_generation) "
                            "VALUES ('BV1result', 303, 'v1', 1)"
                        )
                    )
                    await _expect_integrity_error(
                        connection,
                        "INSERT INTO analysis_result "
                        "(bvid, cid, score, label, confidence, evidence_json, "
                        "analysis_version, analyzed_at, analysis_expires_at) "
                        "VALUES ('BV1result', 303, 101, 'high', 1, '[]'::jsonb, "
                        "'v1', now(), now())",
                        {},
                    )
                    await _expect_integrity_error(
                        connection,
                        "INSERT INTO video_declaration "
                        "(bvid, cid, state, checked_at, expires_at) "
                        "VALUES ('BV1result', 303, 'invalid', now(), now())",
                        {},
                    )
                    await _expect_integrity_error(
                        connection,
                        "INSERT INTO video_metadata (bvid, default_cid, checked_at) "
                        "VALUES ('BV1result', 0, now())",
                        {},
                    )
                    await _expect_integrity_error(
                        connection,
                        "INSERT INTO analysis_attempt "
                        "(attempt_id, bvid, cid, analysis_version, generation, status) "
                        "VALUES (:attempt_id, 'BV1missing', 999, 'v1', 1, 'queued')",
                        {"attempt_id": uuid4()},
                    )
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_migration_revision_is_at_head(migrated_database: str) -> None:
    [row] = asyncio.run(_query(migrated_database, "SELECT version_num FROM alembic_version"))
    assert row["version_num"] == "0001_initial"
