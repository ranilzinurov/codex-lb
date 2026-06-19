from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.modules.shared.schemas import DashboardModel


class ExternalCodexUsageBucket(DashboardModel):
    started_at: datetime = Field(alias="startedAt")
    model: str = Field(min_length=1, max_length=128)
    reasoning_effort: str | None = Field(default=None, alias="reasoningEffort", max_length=32)
    service_tier: str | None = Field(default=None, alias="serviceTier", max_length=32)
    event_count: int = Field(alias="eventCount", ge=1)
    input_tokens: int = Field(alias="inputTokens", ge=0)
    cached_input_tokens: int = Field(alias="cachedInputTokens", ge=0)
    output_tokens: int = Field(alias="outputTokens", ge=0)
    reasoning_output_tokens: int = Field(alias="reasoningOutputTokens", ge=0)
    total_tokens: int = Field(alias="totalTokens", ge=0)


class ExternalCodexUsageIngestRequest(DashboardModel):
    source_name: str = Field(alias="sourceName", min_length=1, max_length=80)
    account_id: str = Field(alias="accountId", min_length=1, max_length=128)
    bucket_seconds: int = Field(alias="bucketSeconds", ge=60, le=86400)
    buckets: list[ExternalCodexUsageBucket] = Field(min_length=1, max_length=2000)


class ExternalCodexUsageIngestResponse(DashboardModel):
    source_name: str = Field(alias="sourceName")
    account_id: str = Field(alias="accountId")
    api_key_id: str = Field(alias="apiKeyId")
    bucket_count: int = Field(alias="bucketCount")
    request_log_count: int = Field(alias="requestLogCount")
    total_tokens: int = Field(alias="totalTokens")
