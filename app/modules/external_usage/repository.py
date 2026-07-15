from __future__ import annotations

from collections.abc import Sequence
from typing import cast as typing_cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.usage.logs import RequestLogLike, calculated_cost_from_log
from app.db.models import Account, RequestLog
from app.db.session import sqlite_writer_section


class ExternalUsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def account_exists(self, account_id: str) -> bool:
        result = await self._session.execute(select(Account.id).where(Account.id == account_id).limit(1))
        return result.scalar_one_or_none() is not None

    async def account_plan_type(self, account_id: str) -> str | None:
        result = await self._session.execute(select(Account.plan_type).where(Account.id == account_id).limit(1))
        plan_type = result.scalar_one_or_none()
        return str(plan_type) if plan_type is not None else None

    async def replace_synthetic_logs(
        self,
        *,
        source: str,
        request_ids: Sequence[str],
        logs: Sequence[RequestLog],
    ) -> int:
        async with sqlite_writer_section():
            if request_ids:
                await self._session.execute(
                    delete(RequestLog).where(
                        RequestLog.source == source,
                        RequestLog.request_id.in_(list(request_ids)),
                    )
                )
            for log in logs:
                log.cost_usd = calculated_cost_from_log(typing_cast(RequestLogLike, log))
                self._session.add(log)
            await self._session.commit()
        return len(logs)
