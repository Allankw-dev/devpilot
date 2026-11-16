"""AI analyses of failed CI runs

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-16
"""
import sqlalchemy as sa
from alembic import op


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('ci_analyses',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workflow_run_id', sa.Uuid(), nullable=False),
    sa.Column('requested_by', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('queued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('run_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('head_sha', sa.String(length=40), nullable=True),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('category', sa.String(length=20), nullable=True),
    sa.Column('confidence', sa.String(length=10), nullable=True),
    sa.Column('likely_cause', sa.Text(), nullable=True),
    sa.Column('suggested_fix', sa.Text(), nullable=True),
    sa.Column('failed_steps', sa.JSON(), nullable=True),
    sa.Column('evidence', sa.JSON(), nullable=True),
    sa.Column('notes', sa.String(length=1500), nullable=True),
    sa.Column('jobs_total', sa.Integer(), nullable=False),
    sa.Column('jobs_analyzed', sa.Integer(), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('error', sa.String(length=500), nullable=True),
    sa.CheckConstraint("category IS NULL OR category IN ('test_failure', 'build_error', 'lint_or_types', 'dependency', 'configuration', 'infrastructure', 'flaky_or_timeout', 'unknown')", name=op.f('ck_ci_analyses_category_valid')),
    sa.CheckConstraint("confidence IS NULL OR confidence IN ('high', 'medium', 'low')", name=op.f('ck_ci_analyses_confidence_valid')),
    sa.CheckConstraint("status IN ('queued', 'running', 'ready', 'failed')", name=op.f('ck_ci_analyses_status_valid')),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_ci_analyses_requested_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workflow_run_id'], ['workflow_runs.id'], name=op.f('fk_ci_analyses_workflow_run_id_workflow_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ci_analyses'))
    )
    op.create_index(op.f('ix_ci_analyses_workflow_run_id'), 'ci_analyses', ['workflow_run_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_ci_analyses_workflow_run_id'), table_name='ci_analyses')
    op.drop_table('ci_analyses')
