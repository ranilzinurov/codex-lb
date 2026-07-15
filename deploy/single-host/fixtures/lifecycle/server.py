from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DATABASE = Path("/var/lib/codex-lb/store.db")
VERSION = os.environ["FIXTURE_VERSION"]
FAIL_READY = os.environ.get("FAIL_READY") == "1"
TEST_SECRET = os.environ["TEST_SECRET"]


def initialize_database() -> None:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    DATABASE.parent.chmod(0o777)
    secret_hash = hashlib.sha256(TEST_SECRET.encode("utf-8")).hexdigest()
    with sqlite3.connect(DATABASE) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                access_token_encrypted BLOB NOT NULL,
                refresh_token_encrypted BLOB NOT NULL,
                id_token_encrypted BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS api_keys (id TEXT PRIMARY KEY, key_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS model_sources (id TEXT PRIMARY KEY, api_key_encrypted BLOB);
            CREATE TABLE IF NOT EXISTS automation_jobs (id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS lifecycle_meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO accounts VALUES (?, ?, ?, ?)",
            ("control-account", b"access-token", b"refresh-token", b"id-token"),
        )
        connection.execute("INSERT OR IGNORE INTO api_keys VALUES (?, ?)", ("control-key", secret_hash))
        connection.execute(
            "INSERT INTO lifecycle_meta(name, value) VALUES ('version', ?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
            (VERSION,),
        )
    DATABASE.chmod(0o666)


def state() -> dict[str, object]:
    with sqlite3.connect(DATABASE) as connection:
        accounts = int(connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])
        api_keys = int(connection.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0])
        secret_hash = str(connection.execute("SELECT key_hash FROM api_keys WHERE id='control-key'").fetchone()[0])
        version = str(connection.execute("SELECT value FROM lifecycle_meta WHERE name='version'").fetchone()[0])
    return {"accounts": accounts, "api_keys": api_keys, "secret_hash": secret_hash, "version": version}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler contract
        if self.path == "/health/ready":
            status = HTTPStatus.SERVICE_UNAVAILABLE if FAIL_READY else HTTPStatus.OK
            payload = {"ready": not FAIL_READY, "version": VERSION}
        elif self.path == "/state":
            status = HTTPStatus.OK
            payload = state()
        else:
            status = HTTPStatus.NOT_FOUND
            payload = {"error": "not found"}
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


initialize_database()
ThreadingHTTPServer(("0.0.0.0", 2455), Handler).serve_forever()
