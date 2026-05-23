"""add ai_pick table

Revision ID: a1b2c3d4e5f6
Revises: 564a1d904e05
Create Date: 2026-05-23

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '564a1d904e05'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ai_pick',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('calc_date', sa.Date(), nullable=False, unique=True),
        sa.Column('code', sa.String(10), nullable=False),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('reason', sa.String(300), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_ai_pick_calc_date', 'ai_pick', ['calc_date'])


def downgrade() -> None:
    op.drop_index('ix_ai_pick_calc_date', 'ai_pick')
    op.drop_table('ai_pick')
