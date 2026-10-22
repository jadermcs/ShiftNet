"""Database fixtures.

DB tests run against a real Postgres with the app's migrations and seed applied. Point them at one:
  SHIFTNET_PG_BIN=/path/to/postgres/bin   start a throwaway server (initdb + pg_ctl) for the session
  TEST_DATABASE_URL=postgresql://…        an existing server where the test may create databases
Otherwise they are skipped. Supabase's auth schema and roles are stubbed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

APP = Path(__file__).resolve().parents[2] / "app" / "supabase"

SUPABASE_STUB = """
do $$ begin
  create role anon nologin; exception when duplicate_object then null; end $$;
do $$ begin
  create role authenticated nologin; exception when duplicate_object then null; end $$;
do $$ begin
  create role service_role nologin bypassrls; exception when duplicate_object then null; end $$;
create schema if not exists extensions;
grant usage on schema extensions to anon, authenticated;
create schema if not exists auth;
create table if not exists auth.users (id uuid primary key, is_anonymous boolean not null default false);
create or replace function auth.uid() returns uuid language sql stable as
  $$ select coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''),
                     nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')::uuid $$;
create or replace function auth.jwt() returns jsonb language sql stable as
  $$ select coalesce(nullif(current_setting('request.jwt.claims', true), ''), '{}')::jsonb $$;
"""


def _with_db(url: str, name: str) -> str:
    info = psycopg.conninfo.conninfo_to_dict(url)
    info["dbname"] = name
    return psycopg.conninfo.make_conninfo(**info)


@pytest.fixture(scope="session")
def pg_server():
    if url := os.environ.get("TEST_DATABASE_URL"):
        yield url
        return
    bin_dir = os.environ.get("SHIFTNET_PG_BIN")
    if not bin_dir:
        pytest.skip("set SHIFTNET_PG_BIN or TEST_DATABASE_URL to run database tests")
    tmp = Path(tempfile.mkdtemp(prefix="shiftnet-pg-"))
    data, sock = tmp / "data", tmp
    subprocess.run([f"{bin_dir}/initdb", "-D", data, "-U", "postgres", "-A", "trust"], check=True, capture_output=True)
    subprocess.run(
        [f"{bin_dir}/pg_ctl", "-D", data, "-w", "-l", tmp / "log", "-o", f"-p 55433 -k {sock} -c listen_addresses=''", "start"],
        check=True, capture_output=True,
    )
    try:
        yield f"postgresql://postgres@/postgres?host={sock}&port=55433"
    finally:
        subprocess.run([f"{bin_dir}/pg_ctl", "-D", data, "-m", "immediate", "stop"], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def template_db(pg_server):
    """A database with the stub, every migration and the seed, used as a template per test."""
    name = f"shiftnet_tpl_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(pg_server, autocommit=True) as c:
        c.execute(f'create database "{name}"')
    with psycopg.connect(_with_db(pg_server, name), autocommit=True) as c:
        c.execute(SUPABASE_STUB)
        for f in sorted((APP / "migrations").glob("*.sql")):
            c.execute(f.read_text())
        c.execute((APP / "seed.sql").read_text())
    yield name
    with psycopg.connect(pg_server, autocommit=True) as c:
        c.execute(f'drop database if exists "{name}" with (force)')


@pytest.fixture
def database_url(pg_server, template_db, monkeypatch):
    """A fresh copy of the template; also exported as DATABASE_URL for the CLI and MCP tools."""
    name = f"shiftnet_t_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(pg_server, autocommit=True) as c:
        c.execute(f'create database "{name}" template "{template_db}"')
    url = _with_db(pg_server, name)
    monkeypatch.setenv("DATABASE_URL", url)
    yield url
    with psycopg.connect(pg_server, autocommit=True) as c:
        c.execute(f'drop database if exists "{name}" with (force)')


@pytest.fixture
def conn(database_url):
    with psycopg.connect(database_url, row_factory=dict_row) as c:
        yield c
