from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


def _load_fingerprint_module():
    path = Path(__file__).parents[2] / "deploy" / "single-host" / "state_fingerprint.py"
    spec = importlib.util.spec_from_file_location("single_host_state_fingerprint", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fingerprint = _load_fingerprint_module()


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE accounts (
                id TEXT PRIMARY KEY,
                access_token_encrypted BLOB NOT NULL,
                refresh_token_encrypted BLOB NOT NULL,
                id_token_encrypted BLOB NOT NULL
            );
            CREATE TABLE api_keys (
                id TEXT PRIMARY KEY,
                key_hash TEXT NOT NULL
            );
            CREATE TABLE model_sources (
                id TEXT PRIMARY KEY,
                api_key_encrypted BLOB
            );
            CREATE TABLE automation_jobs (id TEXT PRIMARY KEY);
            INSERT INTO accounts VALUES ('account-1', X'0102', X'0304', X'0506');
            INSERT INTO api_keys VALUES ('key-1', 'hash-one');
            """
        )


def test_fingerprint_hides_secrets_and_accepts_monotonic_additions(tmp_path: Path) -> None:
    database = tmp_path / "store.db"
    _database(database)
    runtime = {"OPENAI_API_KEY": "runtime-secret", "LOG_LEVEL": "INFO"}
    before = fingerprint.build_state_fingerprint(database, runtime, "volume:codex-lb-data/store.db")

    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO api_keys VALUES ('key-2', 'hash-two')")
    after = fingerprint.build_state_fingerprint(database, runtime, "volume:codex-lb-data/store.db")

    serialized = json.dumps(before.to_mapping(), sort_keys=True)
    assert before.schema_version == 1
    assert "runtime-secret" not in serialized
    assert "account-1" not in serialized
    assert "key-1" not in serialized
    assert fingerprint.compare_fingerprints(before, after) == ()


def test_fingerprint_rejects_loss_storage_change_and_protected_value_change(tmp_path: Path) -> None:
    database = tmp_path / "store.db"
    _database(database)
    runtime = {"OPENAI_API_KEY": "runtime-secret"}
    before = fingerprint.build_state_fingerprint(database, runtime, "volume:codex-lb-data/store.db")

    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM accounts WHERE id = 'account-1'")
        connection.execute("UPDATE api_keys SET key_hash = 'changed' WHERE id = 'key-1'")
    after = fingerprint.build_state_fingerprint(database, runtime, "volume:other/store.db")

    violations = fingerprint.compare_fingerprints(before, after)

    assert any("storage identity changed" in item for item in violations)
    assert any("accounts decreased" in item for item in violations)
    assert any("protected value" in item for item in violations)
