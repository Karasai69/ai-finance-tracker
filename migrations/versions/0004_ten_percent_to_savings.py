"""«10 процентов» — это отложенные деньги: переносим записи в «Отложил»

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE transactions SET category = 'savings', kind = 'save' WHERE category = 'ten_percent'"))
    # Лимиты бывают только у расходов, а накопления — не расход
    op.execute(sa.text("DELETE FROM budgets WHERE category = 'ten_percent'"))


def downgrade() -> None:
    # Отличить бывшие «10 процентов» от прочих накоплений уже нельзя — оставляем как есть
    pass
