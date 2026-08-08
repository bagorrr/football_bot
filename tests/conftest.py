"""Shared real-PostgreSQL test fixtures."""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from psycopg import conninfo, sql


@pytest.fixture
def fresh_database_url() -> Iterator[str]:
    """Create an isolated PostgreSQL database for migration lifecycle tests."""
    admin_database_url = os.environ["TEST_DATABASE_URL"]
    database_name = f"football_migration_{uuid4().hex}"
    isolated_database_url = conninfo.make_conninfo(
        admin_database_url,
        dbname=database_name,
    )
    with psycopg.connect(admin_database_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)),
        )
    try:
        yield isolated_database_url
    finally:
        with psycopg.connect(admin_database_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(database_name),
                ),
            )
