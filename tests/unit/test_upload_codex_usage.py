from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from scripts.upload_codex_usage import _collect_buckets


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _token_count(timestamp: str, *, input_tokens: int, cached: int, output: int) -> dict[str, object]:
    return {
        "type": "event_msg",
        "timestamp": timestamp,
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached,
                    "output_tokens": output,
                    "reasoning_output_tokens": 0,
                    "total_tokens": input_tokens + output,
                }
            },
        },
    }


def test_collect_buckets_uses_token_count_deltas(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    session = codex_home / "sessions" / "2026" / "06" / "19" / "session.jsonl"
    _write_jsonl(
        session,
        [
            {"type": "turn_context", "payload": {"model": "gpt-5.5", "effort": "high"}},
            _token_count("2026-06-19T10:00:00Z", input_tokens=100, cached=20, output=10),
            _token_count("2026-06-19T10:05:00Z", input_tokens=160, cached=70, output=15),
            _token_count("2026-06-19T10:10:00Z", input_tokens=220, cached=90, output=25),
        ],
    )

    buckets = _collect_buckets(
        codex_home=codex_home,
        since_timestamp=dt.datetime(2026, 6, 19, 10, 0, tzinfo=dt.UTC).timestamp(),
        bucket_seconds=1800,
    )

    assert buckets == [
        {
            "startedAt": "2026-06-19T10:00:00Z",
            "model": "gpt-5.5",
            "reasoningEffort": "high",
            "eventCount": 3,
            "inputTokens": 220,
            "cachedInputTokens": 90,
            "outputTokens": 25,
            "reasoningOutputTokens": 0,
            "totalTokens": 245,
        }
    ]


def test_collect_buckets_subtracts_snapshot_before_window(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    session = codex_home / "sessions" / "2026" / "06" / "19" / "session.jsonl"
    _write_jsonl(
        session,
        [
            {"type": "turn_context", "payload": {"model": "gpt-5.5", "effort": "medium"}},
            _token_count("2026-06-19T09:55:00Z", input_tokens=1000, cached=500, output=100),
            _token_count("2026-06-19T10:05:00Z", input_tokens=1200, cached=650, output=140),
        ],
    )

    buckets = _collect_buckets(
        codex_home=codex_home,
        since_timestamp=dt.datetime(2026, 6, 19, 10, 0, tzinfo=dt.UTC).timestamp(),
        bucket_seconds=1800,
    )

    assert buckets[0]["inputTokens"] == 200
    assert buckets[0]["cachedInputTokens"] == 150
    assert buckets[0]["outputTokens"] == 40
    assert buckets[0]["totalTokens"] == 240


def test_collect_buckets_treats_decreasing_total_as_reset(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    session = codex_home / "sessions" / "2026" / "06" / "19" / "session.jsonl"
    _write_jsonl(
        session,
        [
            {"type": "turn_context", "payload": {"model": "gpt-5.5", "effort": "medium"}},
            _token_count("2026-06-19T10:00:00Z", input_tokens=500, cached=300, output=50),
            _token_count("2026-06-19T10:05:00Z", input_tokens=100, cached=80, output=10),
        ],
    )

    buckets = _collect_buckets(
        codex_home=codex_home,
        since_timestamp=dt.datetime(2026, 6, 19, 10, 0, tzinfo=dt.UTC).timestamp(),
        bucket_seconds=1800,
    )

    assert buckets[0]["inputTokens"] == 600
    assert buckets[0]["cachedInputTokens"] == 380
    assert buckets[0]["outputTokens"] == 60
    assert buckets[0]["totalTokens"] == 660
