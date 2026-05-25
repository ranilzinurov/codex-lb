from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.core import usage as usage_core
from app.core.config.settings import get_settings
from app.core.crypto import TokenEncryptor
from app.core.usage.types import UsageWindowRow
from app.core.utils.time import utcnow
from app.db.models import Account, UsageHistory
from app.modules.accounts.mappers import build_account_summaries
from app.modules.dashboard.builders import (
    build_dashboard_overview_summary,
    build_overview_timeframe,
    resolve_overview_timeframe,
)
from app.modules.dashboard.repository import DashboardRepository
from app.modules.dashboard.schemas import (
    DashboardApiKeyAttributionBucket,
    DashboardApiKeyUsageAttribution,
    DashboardApiKeyUsageAttributionEntry,
    DashboardApiKeyUsageAttributionWindow,
    DashboardOverviewResponse,
    DashboardOverviewTimeframeKey,
    DashboardUsageWindows,
    DepletionResponse,
)
from app.modules.dashboard.weekly_pace import build_weekly_credit_pace
from app.modules.request_logs.repository import ApiKeyAccountUsageAggregate
from app.modules.usage.builders import (
    align_bucket_window_start,
    build_activity_summaries,
    build_trends_from_buckets,
    build_usage_window_response,
)
from app.modules.usage.depletion_service import (
    compute_aggregate_depletion,
    compute_depletion_for_account,
    filter_depletion_history_since,
    prune_depletion_cache,
)
from app.modules.usage.mappers import usage_history_to_window_row


class DashboardService:
    def __init__(self, repo: DashboardRepository) -> None:
        self._repo = repo
        self._encryptor = TokenEncryptor()

    async def get_overview(
        self,
        timeframe_key: DashboardOverviewTimeframeKey = "7d",
    ) -> DashboardOverviewResponse:
        now = utcnow()
        overview_timeframe = resolve_overview_timeframe(timeframe_key)
        accounts = await self._repo.list_accounts()
        account_ids = [account.id for account in accounts]
        primary_usage = await self._repo.latest_usage_by_account("primary")
        secondary_usage = await self._repo.latest_usage_by_account("secondary")
        limit_warmups_by_account = await self._repo.latest_limit_warmups_by_account(account_ids)

        account_summaries = sorted(
            build_account_summaries(
                accounts=accounts,
                primary_usage=primary_usage,
                secondary_usage=secondary_usage,
                limit_warmups_by_account=limit_warmups_by_account,
                encryptor=self._encryptor,
                include_auth=False,
            ),
            key=lambda a: a.capacity_credits_primary or 0,
            reverse=True,
        )

        primary_rows_raw = _rows_from_latest(primary_usage)
        secondary_rows_raw = _rows_from_latest(secondary_usage)
        primary_rows, secondary_rows = usage_core.normalize_weekly_only_rows(
            primary_rows_raw,
            secondary_rows_raw,
        )

        bucket_since = now - timedelta(minutes=overview_timeframe.window_minutes)
        bucket_query_since = align_bucket_window_start(
            bucket_since,
            overview_timeframe.bucket_seconds,
        )
        bucket_rows = await self._repo.aggregate_logs_by_bucket(
            bucket_query_since,
            overview_timeframe.bucket_seconds,
        )
        trends, _, _ = build_trends_from_buckets(
            bucket_rows,
            bucket_since,
            bucket_seconds=overview_timeframe.bucket_seconds,
            bucket_count=overview_timeframe.bucket_count,
        )
        activity_aggregate = await self._repo.aggregate_activity_since(bucket_since)
        top_error = await self._repo.top_error_since(bucket_since)
        activity_metrics, activity_cost = build_activity_summaries(
            activity_aggregate,
            top_error=top_error,
        )

        summary = build_dashboard_overview_summary(
            accounts=accounts,
            primary_rows=primary_rows,
            secondary_rows=secondary_rows,
            activity_metrics=activity_metrics,
            activity_cost=activity_cost,
        )

        secondary_minutes = usage_core.resolve_window_minutes("secondary", secondary_rows)
        primary_window_minutes = usage_core.resolve_window_minutes("primary", primary_rows)

        windows = DashboardUsageWindows(
            primary=build_usage_window_response(
                window_key="primary",
                window_minutes=primary_window_minutes,
                usage_rows=primary_rows,
                accounts=accounts,
            ),
            secondary=build_usage_window_response(
                window_key="secondary",
                window_minutes=secondary_minutes,
                usage_rows=secondary_rows,
                accounts=accounts,
            ),
        )
        api_key_attribution = await self._build_api_key_attribution(
            accounts=accounts,
            primary_rows=primary_rows,
            secondary_rows=secondary_rows,
            now=now,
        )

        # Compute depletion separately for primary-window and secondary-window
        # accounts so the aggregate is not skewed by mixing different window
        # durations.  The response includes a "window" field that tells the
        # frontend which donut to render the safe-line marker on.
        normalized_primary_ids = {row.account_id for row in primary_rows}
        all_account_ids = set(primary_usage.keys()) | set(secondary_usage.keys())

        # Batch fetch: collect account IDs and determine the widest lookback
        # per window so we can issue at most 2 bulk queries instead of O(N).
        pri_fetch_ids: list[str] = []
        sec_fetch_ids: list[str] = []
        pri_since = now  # will be narrowed to the earliest needed
        sec_since = now
        # Per-account cutoffs for in-memory filtering after bulk fetch
        pri_cutoffs: dict[str, datetime] = {}
        sec_cutoffs: dict[str, datetime] = {}
        weekly_only_ids: set[str] = set()
        weekly_only_history_sources: dict[str, str] = {}

        for account_id in all_account_ids:
            if account_id in normalized_primary_ids:
                usage_entry = primary_usage[account_id]
                acct_window = usage_entry.window_minutes if usage_entry.window_minutes else 300
                acct_since = now - timedelta(minutes=acct_window)
                pri_fetch_ids.append(account_id)
                pri_cutoffs[account_id] = acct_since
                if acct_since < pri_since:
                    pri_since = acct_since
                if account_id in secondary_usage:
                    sec_entry = secondary_usage[account_id]
                    sec_window = sec_entry.window_minutes if sec_entry.window_minutes else 10080
                    s_since = now - timedelta(minutes=sec_window)
                    sec_fetch_ids.append(account_id)
                    sec_cutoffs[account_id] = s_since
                    if s_since < sec_since:
                        sec_since = s_since
            elif account_id in primary_usage:
                weekly_only_ids.add(account_id)
                primary_entry = primary_usage[account_id]
                sec_entry = secondary_usage.get(account_id)
                use_primary_stream = _should_use_weekly_primary_history(primary_entry, sec_entry)
                weekly_only_history_sources[account_id] = "primary" if use_primary_stream else "secondary"
                current_entry = primary_entry if use_primary_stream else sec_entry
                acct_window = current_entry.window_minutes if current_entry and current_entry.window_minutes else 10080
                acct_since = now - timedelta(minutes=acct_window)
                if use_primary_stream:
                    pri_fetch_ids.append(account_id)
                    pri_cutoffs[account_id] = acct_since
                    if acct_since < pri_since:
                        pri_since = acct_since
                else:
                    sec_fetch_ids.append(account_id)
                    sec_cutoffs[account_id] = acct_since
                    if acct_since < sec_since:
                        sec_since = acct_since
            else:
                sec_entry = secondary_usage[account_id]
                acct_window = sec_entry.window_minutes if sec_entry.window_minutes else 10080
                acct_since = now - timedelta(minutes=acct_window)
                sec_fetch_ids.append(account_id)
                sec_cutoffs[account_id] = acct_since
                if acct_since < sec_since:
                    sec_since = acct_since

        # Issue at most 2 bulk queries
        all_pri_rows = (
            await self._repo.bulk_usage_history_since(pri_fetch_ids, "primary", pri_since) if pri_fetch_ids else {}
        )
        all_sec_rows = (
            await self._repo.bulk_usage_history_since(sec_fetch_ids, "secondary", sec_since) if sec_fetch_ids else {}
        )

        # Filter in-memory to each account's actual cutoff
        primary_history: dict[str, list[UsageHistory]] = {}
        secondary_history: dict[str, list[UsageHistory]] = {}

        for account_id in all_account_ids:
            if account_id in normalized_primary_ids:
                cutoff = pri_cutoffs[account_id]
                rows = filter_depletion_history_since(all_pri_rows.get(account_id, []), cutoff)
                if rows:
                    primary_history[account_id] = rows
                if account_id in sec_cutoffs:
                    s_cutoff = sec_cutoffs[account_id]
                    s_rows = filter_depletion_history_since(all_sec_rows.get(account_id, []), s_cutoff)
                    if s_rows:
                        secondary_history[account_id] = s_rows
            elif account_id in weekly_only_ids:
                source = weekly_only_history_sources[account_id]
                if source == "primary":
                    cutoff = pri_cutoffs[account_id]
                    rows = filter_depletion_history_since(all_pri_rows.get(account_id, []), cutoff)
                else:
                    cutoff = sec_cutoffs[account_id]
                    rows = filter_depletion_history_since(all_sec_rows.get(account_id, []), cutoff)
                if rows:
                    secondary_history[account_id] = rows
            else:
                cutoff = sec_cutoffs[account_id]
                rows = filter_depletion_history_since(all_sec_rows.get(account_id, []), cutoff)
                if rows:
                    secondary_history[account_id] = rows

        pri_depletion, sec_depletion = _build_depletion_by_window(primary_history, secondary_history, now)
        settings = get_settings()
        weekly_credit_pace = build_weekly_credit_pace(
            accounts=accounts,
            account_summaries=account_summaries,
            secondary_history=secondary_history,
            now=now,
            usage_refresh_interval_seconds=settings.usage_refresh_interval_seconds,
        )

        additional_ts = await self._repo.latest_additional_recorded_at()
        return DashboardOverviewResponse(
            last_sync_at=_latest_recorded_at(primary_usage, secondary_usage, additional_ts),
            timeframe=build_overview_timeframe(overview_timeframe),
            accounts=account_summaries,
            summary=summary,
            windows=windows,
            trends=trends,
            depletion_primary=pri_depletion,
            depletion_secondary=sec_depletion,
            weekly_credit_pace=weekly_credit_pace,
            api_key_attribution=api_key_attribution,
        )

    async def _build_api_key_attribution(
        self,
        *,
        accounts: list[Account],
        primary_rows: list[UsageWindowRow],
        secondary_rows: list[UsageWindowRow],
        now: datetime,
    ) -> DashboardApiKeyUsageAttribution:
        primary = await self._build_api_key_attribution_window(
            window_key="primary",
            accounts=accounts,
            usage_rows=primary_rows,
            now=now,
        )
        secondary = await self._build_api_key_attribution_window(
            window_key="secondary",
            accounts=accounts,
            usage_rows=secondary_rows,
            now=now,
        )
        return DashboardApiKeyUsageAttribution(primary=primary, secondary=secondary)

    async def _build_api_key_attribution_window(
        self,
        *,
        window_key: str,
        accounts: list[Account],
        usage_rows: list[UsageWindowRow],
        now: datetime,
    ) -> DashboardApiKeyUsageAttributionWindow:
        account_by_id = {account.id: account for account in accounts}
        usage_by_account_id = {row.account_id: row for row in usage_rows if row.account_id in account_by_id}
        window_minutes = usage_core.resolve_window_minutes(window_key, usage_rows)
        since_by_account_id = _attribution_since_by_account_id(
            usage_by_account_id,
            window_key=window_key,
            now=now,
        )
        aggregates = await self._repo.aggregate_api_key_account_usage(since_by_account_id)

        entries = _build_api_key_attribution_entries(
            window_key=window_key,
            account_by_id=account_by_id,
            usage_by_account_id=usage_by_account_id,
            aggregates=aggregates,
        )
        total_estimated_used_credits = round(
            sum(_used_credits_for_row(row, account_by_id, window_key) for row in usage_by_account_id.values()),
            6,
        )
        return DashboardApiKeyUsageAttributionWindow(
            window_key=_dashboard_attribution_window_key(window_key),
            window_minutes=window_minutes,
            total_estimated_used_credits=total_estimated_used_credits,
            entries=entries,
        )


def _build_depletion_by_window(
    primary_history: dict[str, list[UsageHistory]],
    secondary_history: dict[str, list[UsageHistory]],
    now,
) -> tuple[DepletionResponse | None, DepletionResponse | None]:
    """Compute depletion independently per window."""
    active_cache_keys = {(account_id, "standard", "primary") for account_id in primary_history}
    active_cache_keys.update((account_id, "standard", "secondary") for account_id in secondary_history)

    def _aggregate(history: dict[str, list[UsageHistory]], window: str) -> DepletionResponse | None:
        metrics = []
        for account_id, rows in history.items():
            m = compute_depletion_for_account(
                account_id=account_id,
                limit_name="standard",
                window=window,
                history=rows,
                now=now,
            )
            metrics.append(m)
        agg = compute_aggregate_depletion(metrics)
        if agg is None:
            return None
        return DepletionResponse(
            risk=agg.risk,
            risk_level=agg.risk_level,
            burn_rate=agg.burn_rate,
            safe_usage_percent=agg.safe_usage_percent,
            projected_exhaustion_at=agg.projected_exhaustion_at,
            seconds_until_exhaustion=agg.seconds_until_exhaustion,
        )

    primary_depletion = _aggregate(primary_history, "primary")
    secondary_depletion = _aggregate(secondary_history, "secondary")
    prune_depletion_cache(active_cache_keys)
    return primary_depletion, secondary_depletion


def _rows_from_latest(latest: dict[str, UsageHistory]) -> list[UsageWindowRow]:
    return [usage_history_to_window_row(entry) for entry in latest.values()]


def _should_use_weekly_primary_history(
    primary_entry: UsageHistory,
    secondary_entry: UsageHistory | None,
) -> bool:
    return usage_core.should_use_weekly_primary(
        usage_history_to_window_row(primary_entry),
        usage_history_to_window_row(secondary_entry) if secondary_entry is not None else None,
    )


def _latest_recorded_at(
    primary_usage: dict[str, UsageHistory],
    secondary_usage: dict[str, UsageHistory],
    additional_ts: datetime | None = None,
):
    timestamps = [
        entry.recorded_at
        for entry in list(primary_usage.values()) + list(secondary_usage.values())
        if entry.recorded_at is not None
    ]
    if additional_ts is not None:
        timestamps.append(additional_ts)
    return max(timestamps) if timestamps else None


def _attribution_since_by_account_id(
    usage_by_account_id: dict[str, UsageWindowRow],
    *,
    window_key: str,
    now: datetime,
) -> dict[str, datetime]:
    since_by_account_id: dict[str, datetime] = {}
    default_minutes = usage_core.default_window_minutes(window_key)
    for account_id, row in usage_by_account_id.items():
        window_minutes = row.window_minutes or default_minutes
        if window_minutes is None or window_minutes <= 0:
            continue
        since_by_account_id[account_id] = now - timedelta(minutes=window_minutes)
    return since_by_account_id


def _build_api_key_attribution_entries(
    *,
    window_key: str,
    account_by_id: dict[str, Account],
    usage_by_account_id: dict[str, UsageWindowRow],
    aggregates: list[ApiKeyAccountUsageAggregate],
) -> list[DashboardApiKeyUsageAttributionEntry]:
    aggregates_by_account_id: dict[str, list[ApiKeyAccountUsageAggregate]] = defaultdict(list)
    for row in aggregates:
        aggregates_by_account_id[row.account_id].append(row)

    entries: list[DashboardApiKeyUsageAttributionEntry] = []
    for account_id, usage_row in usage_by_account_id.items():
        account = account_by_id.get(account_id)
        if account is None:
            continue
        account_used_credits = _used_credits_for_row(usage_row, account_by_id, window_key)
        account_aggregates = aggregates_by_account_id.get(account_id, [])
        account_denominator = _account_attribution_denominator(account_aggregates)
        account_attributed_credits = 0.0

        for row in account_aggregates:
            if row.api_key_id is None or not row.api_key_show_on_dashboard:
                continue
            metric = _attribution_metric(row, account_denominator.metric)
            estimated_credits = account_used_credits * (metric / account_denominator.value)
            account_attributed_credits += estimated_credits
            entries.append(
                _api_key_attribution_entry(
                    bucket="api_key",
                    account_id=account_id,
                    account_email=account.email,
                    api_key_id=row.api_key_id,
                    api_key_name=row.api_key_name or row.api_key_id,
                    key_prefix=row.api_key_prefix,
                    request_count=row.request_count,
                    total_tokens=row.total_tokens,
                    cached_input_tokens=row.cached_input_tokens,
                    total_cost_usd=row.total_cost_usd,
                    estimated_credits=estimated_credits,
                    share_denominator_credits=account_used_credits,
                )
            )

        unattributed_credits = max(0.0, account_used_credits - account_attributed_credits)
        unattributed_logs = [
            row for row in account_aggregates if row.api_key_id is None or not row.api_key_show_on_dashboard
        ]
        if unattributed_credits > 0 or unattributed_logs:
            entries.append(
                _api_key_attribution_entry(
                    bucket="unattributed",
                    account_id=account_id,
                    account_email=account.email,
                    api_key_id=None,
                    api_key_name=None,
                    key_prefix=None,
                    request_count=sum(row.request_count for row in unattributed_logs),
                    total_tokens=sum(row.total_tokens for row in unattributed_logs),
                    cached_input_tokens=sum(row.cached_input_tokens for row in unattributed_logs),
                    total_cost_usd=round(sum(row.total_cost_usd for row in unattributed_logs), 6),
                    estimated_credits=unattributed_credits,
                    share_denominator_credits=account_used_credits,
                )
            )

    entries.sort(
        key=lambda item: (
            item.account_id,
            0 if item.bucket == "api_key" else 1,
            -(item.estimated_credits),
            item.api_key_name or "",
        )
    )
    return entries


@dataclass(frozen=True, slots=True)
class _AttributionDenominator:
    metric: Literal["cost", "tokens", "requests"]
    value: float


def _account_attribution_denominator(rows: list[ApiKeyAccountUsageAggregate]) -> _AttributionDenominator:
    total_cost = sum(max(0.0, row.total_cost_usd) for row in rows)
    if total_cost > 0:
        return _AttributionDenominator(metric="cost", value=total_cost)
    total_tokens = sum(max(0, row.total_tokens) for row in rows)
    if total_tokens > 0:
        return _AttributionDenominator(metric="tokens", value=float(total_tokens))
    total_requests = sum(max(0, row.request_count) for row in rows)
    return _AttributionDenominator(metric="requests", value=float(total_requests or 1))


def _attribution_metric(row: ApiKeyAccountUsageAggregate, metric: str) -> float:
    if metric == "cost":
        return max(0.0, row.total_cost_usd)
    if metric == "tokens":
        return float(max(0, row.total_tokens))
    return float(max(0, row.request_count))


def _used_credits_for_row(
    row: UsageWindowRow,
    account_by_id: dict[str, Account],
    window_key: str,
) -> float:
    account = account_by_id.get(row.account_id)
    capacity = usage_core.capacity_for_plan(account.plan_type if account else None, window_key)
    used_credits = usage_core.used_credits_from_percent(row.used_percent, capacity)
    return float(used_credits or 0.0)


def _api_key_attribution_entry(
    *,
    bucket: DashboardApiKeyAttributionBucket,
    account_id: str,
    account_email: str | None,
    api_key_id: str | None,
    api_key_name: str | None,
    key_prefix: str | None,
    request_count: int,
    total_tokens: int,
    cached_input_tokens: int,
    total_cost_usd: float,
    estimated_credits: float,
    share_denominator_credits: float,
) -> DashboardApiKeyUsageAttributionEntry:
    share_percent = 0.0
    if share_denominator_credits > 0:
        share_percent = (estimated_credits / share_denominator_credits) * 100.0
    return DashboardApiKeyUsageAttributionEntry(
        bucket=bucket,
        account_id=account_id,
        account_email=account_email,
        api_key_id=api_key_id,
        api_key_name=api_key_name,
        key_prefix=key_prefix,
        request_count=request_count,
        total_tokens=total_tokens,
        cached_input_tokens=cached_input_tokens,
        total_cost_usd=round(total_cost_usd, 6),
        estimated_credits=round(estimated_credits, 6),
        attribution_share_percent=round(share_percent, 6),
        is_attribution_estimated=True,
    )


def _dashboard_attribution_window_key(window_key: str) -> Literal["primary", "secondary"]:
    if window_key == "primary":
        return "primary"
    return "secondary"
