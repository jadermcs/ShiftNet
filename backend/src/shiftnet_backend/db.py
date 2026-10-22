"""Postgres connection for the backend.

The backend writes the lexicon, so it needs a privileged connection: the database's own `postgres`
user (Supabase: Project Settings → Database → Connection string, session pooler or direct).
Never use it from the browser app, which only has the publishable key.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

ENV_VAR = "DATABASE_URL"


def database_url(url: str | None = None) -> str:
    url = url or os.environ.get(ENV_VAR)
    if not url:
        raise RuntimeError(f"Set {ENV_VAR} to a privileged Postgres connection string")
    return url


def connect(url: str | None = None) -> psycopg.Connection:
    # prepare_threshold=None: Supabase's transaction pooler does not support prepared statements.
    return psycopg.connect(database_url(url), row_factory=dict_row, prepare_threshold=None)


@contextmanager
def transaction(url: str | None = None) -> Iterator[psycopg.Connection]:
    """A connection whose work is committed on success and rolled back on any error."""
    with connect(url) as conn:
        with conn.transaction():
            yield conn
