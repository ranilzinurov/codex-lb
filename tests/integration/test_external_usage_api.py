from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.crypto import TokenEncryptor
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus, RequestLog
from app.db.session import SessionLocal
from app.modules.accounts.repository import AccountsRepository
from app.modules.usage.repository import UsageRepository

pytestmark = pytest.mark.integration


def _make_account(account_id: str, email: str) -> Account:
    encryptor = TokenEncryptor()
    return Account(
        id=account_id,
        email=email,
        plan_type="pro",
        access_token_encrypted=encryptor.encrypt("access"),
        refresh_token_encrypted=encryptor.encrypt("refresh"),
        id_token_encrypted=encryptor.encrypt("id"),
        last_refresh=utcnow(),
        status=AccountStatus.ACTIVE,
        deactivation_reason=None,
    )


@pytest.mark.asyncio
async def test_external_codex_usage_ingest_writes_synthetic_request_logs(async_client, db_setup):
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        usage_repo = UsageRepository(session)
        await accounts_repo.upsert(_make_account("acc_external_usage", "external@example.com"))
        await usage_repo.add_entry(
            "acc_external_usage",
            20.0,
            window="primary",
            window_minutes=300,
            recorded_at=utcnow() - timedelta(minutes=1),
        )

    created = await async_client.post(
        "/api/api-keys/",
        json={"name": "ranil", "showOnDashboard": True},
    )
    assert created.status_code == 200
    api_key = created.json()["key"]
    api_key_id = created.json()["id"]

    started_at = (utcnow() - timedelta(minutes=30)).replace(microsecond=0)
    payload = {
        "sourceName": "ranil",
        "accountId": "acc_external_usage",
        "bucketSeconds": 1800,
        "buckets": [
            {
                "startedAt": started_at.isoformat() + "Z",
                "model": "gpt-5.5",
                "reasoningEffort": "medium",
                "eventCount": 3,
                "inputTokens": 1000,
                "cachedInputTokens": 800,
                "outputTokens": 50,
                "reasoningOutputTokens": 10,
                "totalTokens": 1050,
            }
        ],
    }
    first = await async_client.post(
        "/api/external-usage/codex-token-counts",
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
    )
    assert first.status_code == 200
    assert first.json() == {
        "sourceName": "ranil",
        "accountId": "acc_external_usage",
        "apiKeyId": api_key_id,
        "bucketCount": 1,
        "requestLogCount": 1,
        "totalTokens": 1050,
    }

    async with SessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(RequestLog).where(RequestLog.source.like("external_codex_usage:ranil:%"))
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    row = rows[0]
    assert row.account_id == "acc_external_usage"
    assert row.api_key_id == api_key_id
    assert row.model == "gpt-5.5"
    assert row.reasoning_effort == "medium"
    assert row.input_tokens == 1000
    assert row.cached_input_tokens == 800
    assert row.output_tokens == 50
    assert row.reasoning_tokens == 10
    assert row.status == "success"
    assert row.transport == "external_codex_usage"

    payload["buckets"][0]["inputTokens"] = 2000
    payload["buckets"][0]["cachedInputTokens"] = 1500
    payload["buckets"][0]["totalTokens"] = 2050
    second = await async_client.post(
        "/api/external-usage/codex-token-counts",
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
    )
    assert second.status_code == 200

    async with SessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(RequestLog).where(RequestLog.source.like("external_codex_usage:ranil:%"))
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].input_tokens == 2000
    assert rows[0].cached_input_tokens == 1500

    logs = await async_client.get("/api/request-logs?apiKeyId=" + api_key_id)
    assert logs.status_code == 200
    body = logs.json()
    assert body["total"] == 1
    assert body["requests"][0]["apiKeyName"] == "ranil"
    assert body["requests"][0]["source"].startswith("external_codex_usage:ranil:")

    dashboard = await async_client.get("/api/dashboard/overview")
    assert dashboard.status_code == 200
    attribution_entries = dashboard.json()["apiKeyAttribution"]["primary"]["entries"]
    ranil_entry = next(entry for entry in attribution_entries if entry["apiKeyId"] == api_key_id)
    assert ranil_entry["apiKeyName"] == "ranil"
    assert ranil_entry["requestCount"] == 1
    assert ranil_entry["totalTokens"] == 2050


@pytest.mark.asyncio
async def test_external_codex_usage_ingest_requires_valid_api_key(async_client, db_setup):
    response = await async_client.post(
        "/api/external-usage/codex-token-counts",
        json={
            "sourceName": "ranil",
            "accountId": "acc_external_usage",
            "bucketSeconds": 1800,
            "buckets": [],
        },
    )
    assert response.status_code in {401, 422}
