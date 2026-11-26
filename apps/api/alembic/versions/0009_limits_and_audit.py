"""Atomic rate counters and the audit log

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from alembic import op


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('rate_counters',
    sa.Column('key', sa.String(length=200), nullable=False),
    sa.Column('window', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('key', 'window', name=op.f('pk_rate_counters'))
    )
    op.create_table('audit_logs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('target_type', sa.String(length=40), nullable=True),
    sa.Column('target_id', sa.String(length=64), nullable=True),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_audit_logs_actor_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], name=op.f('fk_audit_logs_org_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index('ix_audit_logs_org_id_created_at', 'audit_logs', ['org_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_audit_logs_org_id_created_at', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_table('rate_counters')
