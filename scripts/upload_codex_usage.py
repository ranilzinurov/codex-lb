#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

_TOKEN_USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload aggregate local Codex token_count usage to codex-lb.",
    )
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    parser.add_argument("--url", default=os.environ.get("CODEX_LB_URL"))
    parser.add_argument("--api-key", default=os.environ.get("CODEX_LB_API_KEY"))
    parser.add_argument("--account-id", default=os.environ.get("CODEX_LB_ACCOUNT_ID"))
    parser.add_argument("--source-name", default=os.environ.get("CODEX_LB_SOURCE_NAME", "ranil"))
    parser.add_argument("--lookback-hours", type=int, default=int(os.environ.get("CODEX_LB_LOOKBACK_HOURS", "48")))
    parser.add_argument("--bucket-seconds", type=int, default=int(os.environ.get("CODEX_LB_BUCKET_SECONDS", "1800")))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _iso_to_timestamp(value: str) -> float | None:
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _iter_jsonl_paths(codex_home: Path) -> list[Path]:
    roots = [codex_home / "sessions", codex_home / "archived_sessions"]
    paths: list[Path] = []
    for root in roots:
        paths.extend(Path(path) for path in glob.glob(str(root / "**" / "*.jsonl"), recursive=True))
    return paths


def _bucket_start(timestamp: float, bucket_seconds: int) -> dt.datetime:
    bucket_epoch = int(timestamp // bucket_seconds) * bucket_seconds
    return dt.datetime.fromtimestamp(bucket_epoch, tz=dt.UTC)


def _usage_snapshot(usage: dict[str, Any]) -> dict[str, int]:
    return {field: int(usage.get(field) or 0) for field in _TOKEN_USAGE_FIELDS}


def _usage_delta(
    current: dict[str, int],
    previous: dict[str, int] | None,
) -> dict[str, int]:
    if previous is None or current["total_tokens"] < previous["total_tokens"]:
        return current
    return {field: max(0, current[field] - previous[field]) for field in _TOKEN_USAGE_FIELDS}


def _collect_buckets(
    *,
    codex_home: Path,
    since_timestamp: float,
    bucket_seconds: int,
) -> list[dict[str, Any]]:
    aggregates: dict[tuple[dt.datetime, str, str | None], dict[str, Any]] = defaultdict(
        lambda: {
            "eventCount": 0,
            "inputTokens": 0,
            "cachedInputTokens": 0,
            "outputTokens": 0,
            "reasoningOutputTokens": 0,
            "totalTokens": 0,
        }
    )

    for path in _iter_jsonl_paths(codex_home):
        model: str | None = None
        effort: str | None = None
        previous_usage: dict[str, int] | None = None
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = item.get("payload") or {}
                    if item.get("type") == "turn_context":
                        model = payload.get("model") or model
                        effort = payload.get("effort") or payload.get("reasoning_effort") or effort
                        continue
                    if item.get("type") != "event_msg" or payload.get("type") != "token_count":
                        continue
                    timestamp_raw = item.get("timestamp")
                    if not isinstance(timestamp_raw, str):
                        continue
                    timestamp = _iso_to_timestamp(timestamp_raw)
                    if timestamp is None:
                        continue
                    usage = ((payload.get("info") or {}).get("last_token_usage") or {})
                    if not isinstance(usage, dict):
                        continue
                    current_usage = _usage_snapshot(usage)
                    delta_usage = _usage_delta(current_usage, previous_usage)
                    previous_usage = current_usage
                    if timestamp < since_timestamp:
                        continue
                    if delta_usage["total_tokens"] <= 0:
                        continue
                    resolved_model = model or "unknown"
                    started_at = _bucket_start(timestamp, bucket_seconds)
                    key = (started_at, resolved_model, effort)
                    bucket = aggregates[key]
                    bucket["eventCount"] += 1
                    bucket["inputTokens"] += delta_usage["input_tokens"]
                    bucket["cachedInputTokens"] += delta_usage["cached_input_tokens"]
                    bucket["outputTokens"] += delta_usage["output_tokens"]
                    bucket["reasoningOutputTokens"] += delta_usage["reasoning_output_tokens"]
                    bucket["totalTokens"] += delta_usage["total_tokens"]
        except OSError:
            continue

    buckets: list[dict[str, Any]] = []
    for (started_at, model, effort), values in sorted(aggregates.items()):
        if values["eventCount"] <= 0:
            continue
        buckets.append(
            {
                "startedAt": started_at.isoformat().replace("+00:00", "Z"),
                "model": model,
                "reasoningEffort": effort,
                "eventCount": values["eventCount"],
                "inputTokens": values["inputTokens"],
                "cachedInputTokens": values["cachedInputTokens"],
                "outputTokens": values["outputTokens"],
                "reasoningOutputTokens": values["reasoningOutputTokens"],
                "totalTokens": values["totalTokens"],
            }
        )
    return buckets


def _post_payload(*, url: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = url.rstrip("/") + "/api/external-usage/codex-token-counts"
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"upload failed: HTTP {exc.code}: {body}") from exc


def main() -> None:
    args = _parse_args()
    if not args.url:
        raise SystemExit("missing --url or CODEX_LB_URL")
    if not args.api_key:
        raise SystemExit("missing --api-key or CODEX_LB_API_KEY")
    if not args.account_id:
        raise SystemExit("missing --account-id or CODEX_LB_ACCOUNT_ID")
    if args.lookback_hours <= 0:
        raise SystemExit("--lookback-hours must be positive")

    since = dt.datetime.now(tz=dt.UTC).timestamp() - (args.lookback_hours * 3600)
    buckets = _collect_buckets(
        codex_home=Path(args.codex_home).expanduser(),
        since_timestamp=since,
        bucket_seconds=args.bucket_seconds,
    )
    payload = {
        "sourceName": args.source_name,
        "accountId": args.account_id,
        "bucketSeconds": args.bucket_seconds,
        "buckets": buckets,
    }
    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    if not buckets:
        print("no token_count buckets to upload")
        return
    result = _post_payload(url=args.url, api_key=args.api_key, payload=payload)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
