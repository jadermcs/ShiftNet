"""Database fixtures: a SQLite file with the schema and the sample lexicon (seed/seed.sql), built once
per session and copied for each test."""

from __future__ import annotations

import shutil

import pytest

from shiftnet_backend import db


@pytest.fixture(scope="session")
def template_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("tpl") / "shiftnet.sqlite"
    with db.reader(path) as conn:
        db.seed(conn)
        conn.execute("pragma wal_checkpoint(truncate)")
    return path


@pytest.fixture
def db_path(template_db, tmp_path, monkeypatch):
    """A fresh copy of the template; also exported as SHIFTNET_DB for the CLI, the API and the MCP tools."""
    path = tmp_path / "shiftnet.sqlite"
    shutil.copy(template_db, path)
    monkeypatch.setenv(db.ENV_VAR, str(path))
    return path


@pytest.fixture
def conn(db_path):
    with db.reader(db_path) as c:
        yield c
