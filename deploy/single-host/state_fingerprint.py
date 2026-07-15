"""Versioned, non-secret state fingerprints for single-host deployment."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

SCHEMA_VERSION = 1
COUNT_TABLES = ("accounts", "api_keys", "model_sources", "automation_jobs")
PROTECTED_COLUMNS = {
    "accounts": ("access_token_encrypted", "refresh_token_encrypted", "id_token_encrypted"),
    "api_keys": ("key_hash",),
    "proxy_endpoints": ("password_encrypted",),
    "dashboard_settings": (
        "password_hash",
        "guest_password_hash",
        "bootstrap_token_encrypted",
        "bootstrap_token_hash",
        "totp_secret_encrypted",
    ),
    "model_sources": ("api_key_encrypted",),
}
SECRET_KEY_FRAGMENTS = ("TOKEN", "KEY", "SECRET", "PASSWORD")


@dataclass(frozen=True, slots=True)
class StateFingerprint:
    schema_version: int
    storage_id: str
    record_counts: dict[str, int]
    protected_hashes: dict[str, str]

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: object) -> StateFingerprint:
        if not isinstance(value, dict):
            raise ValueError("fingerprint must be a JSON object")
        raw = cast(dict[str, object], value)
        schema_version = raw.get("schema_version")
        storage_id = raw.get("storage_id")
        record_counts = raw.get("record_counts")
        protected_hashes = raw.get("protected_hashes")
        if schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported fingerprint schema_version: {schema_version!r}")
        if not isinstance(storage_id, str) or not storage_id:
            raise ValueError("fingerprint storage_id must be a non-empty string")
        if not isinstance(record_counts, dict) or not all(
            isinstance(key, str) and isinstance(count, int) and count >= 0 for key, count in record_counts.items()
        ):
            raise ValueError("fingerprint record_counts must contain non-negative integers")
        if not isinstance(protected_hashes, dict) or not all(
            isinstance(key, str) and isinstance(digest, str) and len(digest) == 64
            for key, digest in protected_hashes.items()
        ):
            raise ValueError("fingerprint protected_hashes must contain SHA-256 strings")
        return cls(
            schema_version=SCHEMA_VERSION,
            storage_id=storage_id,
            record_counts=cast(dict[str, int], record_counts),
            protected_hashes=cast(dict[str, str], protected_hashes),
        )


def _sha256(value: bytes | str) -> str:
    payload = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalise(value: object) -> object:
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if value is None or isinstance(value, (str, int, float)):
        return value
    return str(value)


def _database_fingerprint(database_path: Path) -> tuple[dict[str, int], dict[str, str]]:
    counts = {table: 0 for table in COUNT_TABLES}
    protected: dict[str, str] = {}
    if not database_path.is_file():
        return counts, protected

    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
        tables = {
            str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        for table in COUNT_TABLES:
            if table in tables:
                counts[table] = int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])

        for table, expected_columns in PROTECTED_COLUMNS.items():
            if table not in tables:
                continue
            columns = {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()}
            identifier = "id" if "id" in columns else ""
            selected = tuple(column for column in expected_columns if column in columns)
            if not identifier or not selected:
                continue
            projection = ", ".join(f'"{column}"' for column in (identifier, *selected))
            rows = connection.execute(f'SELECT {projection} FROM "{table}" ORDER BY "{identifier}"').fetchall()
            for row in rows:
                stable_id = _sha256(f"{table}:{row[0]}")
                protected[f"db:{table}:{stable_id}"] = _sha256(
                    json.dumps([_normalise(value) for value in row[1:]], separators=(",", ":"), sort_keys=True)
                )
    return counts, protected


def build_state_fingerprint(
    database_path: Path | None, runtime_environment: dict[str, str], storage_id: str
) -> StateFingerprint:
    """Create a fingerprint without retaining protected source values."""

    counts, protected = (
        _database_fingerprint(database_path)
        if database_path is not None
        else ({table: 0 for table in COUNT_TABLES}, {})
    )
    for key, value in sorted(runtime_environment.items()):
        if any(fragment in key.upper() for fragment in SECRET_KEY_FRAGMENTS):
            protected[f"env:{key}"] = _sha256(value)
    return StateFingerprint(
        schema_version=SCHEMA_VERSION,
        storage_id=storage_id,
        record_counts=counts,
        protected_hashes=protected,
    )


def compare_fingerprints(before: StateFingerprint, after: StateFingerprint) -> tuple[str, ...]:
    """Return preservation violations; additions and count growth are allowed."""

    violations: list[str] = []
    if before.schema_version != after.schema_version:
        violations.append(f"fingerprint schema changed: before={before.schema_version} after={after.schema_version}")
    if before.storage_id != after.storage_id:
        violations.append(f"storage identity changed: before={before.storage_id} after={after.storage_id}")
    for table, before_count in sorted(before.record_counts.items()):
        after_count = after.record_counts.get(table, 0)
        if after_count < before_count:
            violations.append(f"record count for {table} decreased: before={before_count} after={after_count}")
    for name, before_hash in sorted(before.protected_hashes.items()):
        after_hash = after.protected_hashes.get(name)
        if after_hash != before_hash:
            violations.append(f"protected value changed or disappeared: {name}")
    return tuple(violations)
