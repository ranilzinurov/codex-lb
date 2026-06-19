from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from scripts.upload_codex_usage import _collect_buckets, _current_codex_weekly_window


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _token_count(
    timestamp: str,
    *,
    input_tokens: int,
    cached: int,
    output: int,
    resets_at: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
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
    }
    if resets_at is not None:
        payload["rate_limits"] = {
            "secondary": {
                "used_percent": 23.0,
                "window_minutes": 10080,
                "resets_at": resets_at,
            },
            "plan_type": "pro",
        }
    return {
        "type": "event_msg",
        "timestamp": timestamp,
        "payload": payload,
    }


def test_collect_buckets_sums_last_token_usage_events(tmp_path: Path) -> None:
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
            "inputTokens": 480,
            "cachedInputTokens": 180,
            "outputTokens": 50,
            "reasoningOutputTokens": 0,
            "totalTokens": 530,
        }
    ]


def test_collect_buckets_filters_before_window_without_subtracting_snapshot(tmp_path: Path) -> None:
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

    assert buckets[0]["inputTokens"] == 1200
    assert buckets[0]["cachedInputTokens"] == 650
    assert buckets[0]["outputTokens"] == 140
    assert buckets[0]["totalTokens"] == 1340


def test_current_codex_weekly_window_uses_latest_secondary_rate_limit(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    session = codex_home / "sessions" / "2026" / "06" / "19" / "session.jsonl"
    reset_at = int(dt.datetime(2026, 6, 25, 4, 39, 56, tzinfo=dt.UTC).timestamp())
    _write_jsonl(
        session,
        [
            _token_count("2026-06-19T09:55:00Z", input_tokens=100, cached=50, output=10, resets_at=reset_at - 3600),
            _token_count("2026-06-19T10:05:00Z", input_tokens=200, cached=150, output=20, resets_at=reset_at),
        ],
    )

    window = _current_codex_weekly_window(codex_home)

    assert window == (reset_at - 10080 * 60, reset_at)
