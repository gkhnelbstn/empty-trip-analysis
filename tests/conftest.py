from __future__ import annotations

import os

import pytest

TEST_DB = "empty_trips_test"


@pytest.fixture
def test_database(monkeypatch) -> None:
    """Point PG* at a fresh, throwaway database so tests never touch the real one."""
    psycopg = pytest.importorskip("psycopg")
    if not os.environ.get("PGHOST"):
        pytest.skip("PGHOST not set; skipping database tests")
    try:
        admin = psycopg.connect(dbname=os.environ.get("PGDATABASE", "postgres"), autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable: {exc}")
    with admin:
        admin.execute(f"drop database if exists {TEST_DB} with (force)")
        admin.execute(f"create database {TEST_DB}")
    monkeypatch.setenv("PGDATABASE", TEST_DB)
