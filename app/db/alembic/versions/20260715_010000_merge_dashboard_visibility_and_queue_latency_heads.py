"""merge dashboard visibility and queue latency heads

Revision ID: 20260715_010000_merge_dashboard_visibility_and_queue_latency_heads
Revises: 20260525_010000_merge_accounts_alias_and_dashboard_visibility_heads,
         20260715_000000_add_request_log_queue_latency
Create Date: 2026-07-15
"""

from __future__ import annotations

revision = "20260715_010000_merge_dashboard_visibility_and_queue_latency_heads"
down_revision = (
    "20260525_010000_merge_accounts_alias_and_dashboard_visibility_heads",
    "20260715_000000_add_request_log_queue_latency",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
