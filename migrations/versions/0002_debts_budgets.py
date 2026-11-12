"""Долги (кому дал / кто вернул) и лимиты по категориям

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("counterparty", sa.String(length=100), nullable=True))
    # У уже записанных долгов имя человека лежит в описании («Алижан»)
    op.execute("UPDATE transactions SET counterparty = description WHERE kind = 'lend' AND description <> ''")

    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("monthly_limit", sa.Numeric(12, 2), nullable=False),
        sa.UniqueConstraint("user_id", "category", name="uq_budgets_user_category"),
    )
    op.create_index("ix_budgets_user_id", "budgets", ["user_id"])


def downgrade() -> None:
    op.drop_table("budgets")
    with op.batch_alter_table("transactions") as batch:
        batch.drop_column("counterparty")
