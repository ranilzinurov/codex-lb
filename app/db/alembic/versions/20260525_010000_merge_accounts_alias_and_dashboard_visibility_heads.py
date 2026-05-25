"""merge accounts alias and api key dashboard visibility heads

Revision ID: 20260525_010000_merge_accounts_alias_and_dashboard_visibility_heads
Revises: 20260513_000000_add_accounts_alias, 20260525_000000_add_api_key_dashboard_visibility
Create Date: 2026-05-25
"""

from __future__ import annotations

revision = "20260525_010000_merge_accounts_alias_and_dashboard_visibility_heads"
down_revision = (
    "20260513_000000_add_accounts_alias",
    "20260525_000000_add_api_key_dashboard_visibility",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
