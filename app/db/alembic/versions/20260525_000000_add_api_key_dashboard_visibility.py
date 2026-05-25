"""add api key dashboard visibility flag

Revision ID: 20260525_000000_add_api_key_dashboard_visibility
Revises: 20260522_000000_add_limit_warmup_trigger
Create Date: 2026-05-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260525_000000_add_api_key_dashboard_visibility"
down_revision = "20260522_000000_add_limit_warmup_trigger"
branch_labels = None
depends_on = None


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, "api_keys")
    if not columns or "show_on_dashboard" in columns:
        return

    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.add_column(
            sa.Column(
                "show_on_dashboard",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, "api_keys")
    if not columns or "show_on_dashboard" not in columns:
        return

    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.drop_column("show_on_dashboard")
