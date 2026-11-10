"""AI usage table, and an index so old webhook deliveries can be pruned cheaply

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-10
"""
import sqlalchemy as sa
from alembic import op


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('llm_usage',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=True),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('operation', sa.String(length=20), nullable=False),
    sa.Column('feature', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('error_code', sa.String(length=30), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('calls', sa.Integer(), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('ok', 'error')", name=op.f('ck_llm_usage_status_valid')),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], name=op.f('fk_llm_usage_org_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_llm_usage_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_llm_usage'))
    )
    op.create_index('ix_llm_usage_org_id_created_at', 'llm_usage', ['org_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_webhook_deliveries_received_at'), 'webhook_deliveries', ['received_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_webhook_deliveries_received_at'), table_name='webhook_deliveries')
    op.drop_index('ix_llm_usage_org_id_created_at', table_name='llm_usage')
    op.drop_table('llm_usage')
