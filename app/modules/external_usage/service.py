from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from app.db.models import RequestLog
from app.modules.api_keys.service import ApiKeyData
from app.modules.external_usage.repository import ExternalUsageRepository
from app.modules.external_usage.schemas import ExternalCodexUsageBucket, ExternalCodexUsageIngestRequest

_SOURCE_PREFIX = "external_codex_usage"
_SLUG_PATTERN = re.compile(r"[^a-z0-9_.-]+")


class ExternalUsageValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExternalUsageIngestResult:
    source_name: str
    account_id: str
    api_key_id: str
    bucket_count: int
    request_log_count: int
    total_tokens: int


class ExternalUsageService:
    def __init__(self, repository: ExternalUsageRepository) -> None:
        self._repository = repository

    async def ingest_codex_usage(
        self,
        payload: ExternalCodexUsageIngestRequest,
        *,
        api_key: ApiKeyData,
    ) -> ExternalUsageIngestResult:
        source_name = _normalize_source_name(payload.source_name)
        account_id = payload.account_id.strip()
        if api_key.account_assignment_scope_enabled and account_id not in set(api_key.assigned_account_ids):
            raise ExternalUsageValidationError(f"API key is not assigned to accountId: {account_id}")
        if not await self._repository.account_exists(account_id):
            raise ExternalUsageValidationError(f"Unknown accountId: {account_id}")

        plan_type = await self._repository.account_plan_type(account_id)
        source = _source_value(source_name)
        logs = [
            _bucket_to_log(
                bucket,
                account_id=account_id,
                api_key_id=api_key.id,
                source=source,
                source_name=source_name,
                plan_type=plan_type,
            )
            for bucket in payload.buckets
        ]
        request_ids = [log.request_id for log in logs]
        inserted = await self._repository.replace_synthetic_logs(
            source=source,
            request_ids=request_ids,
            logs=logs,
        )
        return ExternalUsageIngestResult(
            source_name=source_name,
            account_id=account_id,
            api_key_id=api_key.id,
            bucket_count=len(payload.buckets),
            request_log_count=inserted,
            total_tokens=sum(max(0, bucket.total_tokens) for bucket in payload.buckets),
        )


def _normalize_source_name(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise ExternalUsageValidationError("sourceName is required")
    return normalized


def _source_slug(source_name: str) -> str:
    slug = _SLUG_PATTERN.sub("-", source_name.lower()).strip("-")
    return slug or "external"


def _source_value(source_name: str) -> str:
    digest = hashlib.sha256(source_name.encode("utf-8")).hexdigest()[:12]
    return f"{_SOURCE_PREFIX}:{_source_slug(source_name)}:{digest}"


def _bucket_to_log(
    bucket: ExternalCodexUsageBucket,
    *,
    account_id: str,
    api_key_id: str,
    source: str,
    source_name: str,
    plan_type: str | None,
) -> RequestLog:
    output_tokens = max(0, int(bucket.output_tokens))
    reasoning_tokens = max(0, int(bucket.reasoning_output_tokens))
    input_tokens = max(0, int(bucket.input_tokens))
    cached_tokens = min(max(0, int(bucket.cached_input_tokens)), input_tokens)
    return RequestLog(
        account_id=account_id,
        api_key_id=api_key_id,
        request_id=_request_id(
            source_name=source_name,
            account_id=account_id,
            started_at=bucket.started_at,
            model=bucket.model,
            reasoning_effort=bucket.reasoning_effort,
            service_tier=bucket.service_tier,
        ),
        requested_at=_as_naive_utc(bucket.started_at),
        model=bucket.model,
        plan_type=plan_type,
        source=source,
        transport="external_codex_usage",
        service_tier=bucket.service_tier,
        requested_service_tier=bucket.service_tier,
        actual_service_tier=bucket.service_tier,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
        reasoning_effort=bucket.reasoning_effort,
        latency_ms=None,
        latency_first_token_ms=None,
        status="success",
        error_code=None,
        error_message=f"{bucket.event_count} local Codex token_count event(s)",
    )


def _request_id(
    *,
    source_name: str,
    account_id: str,
    started_at: datetime,
    model: str,
    reasoning_effort: str | None,
    service_tier: str | None,
) -> str:
    raw = "|".join(
        [
            source_name,
            account_id,
            started_at.isoformat(),
            model,
            reasoning_effort or "",
            service_tier or "",
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"external-codex-{digest}"


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
