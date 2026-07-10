from __future__ import annotations

from fastapi import APIRouter, Depends, Security

from app.core.auth.dependencies import set_openai_error_format, validate_usage_api_key
from app.core.exceptions import DashboardBadRequestError
from app.dependencies import ExternalUsageContext, get_external_usage_context
from app.modules.api_keys.service import ApiKeyData
from app.modules.external_usage.schemas import (
    ExternalCodexUsageIngestRequest,
    ExternalCodexUsageIngestResponse,
)
from app.modules.external_usage.service import ExternalUsageValidationError

router = APIRouter(
    prefix="/api/external-usage",
    tags=["external-usage"],
    dependencies=[Depends(set_openai_error_format)],
)


@router.post("/codex-token-counts", response_model=ExternalCodexUsageIngestResponse)
async def ingest_codex_token_counts(
    payload: ExternalCodexUsageIngestRequest,
    api_key: ApiKeyData = Security(validate_usage_api_key),
    context: ExternalUsageContext = Depends(get_external_usage_context),
) -> ExternalCodexUsageIngestResponse:
    try:
        result = await context.service.ingest_codex_usage(payload, api_key=api_key)
    except ExternalUsageValidationError as exc:
        raise DashboardBadRequestError(str(exc), code="invalid_external_usage_payload") from exc
    return ExternalCodexUsageIngestResponse(
        sourceName=result.source_name,
        accountId=result.account_id,
        apiKeyId=result.api_key_id,
        bucketCount=result.bucket_count,
        requestLogCount=result.request_log_count,
        totalTokens=result.total_tokens,
    )
