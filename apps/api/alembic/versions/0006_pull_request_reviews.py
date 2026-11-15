"""AI pull request reviews and their findings

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-14
"""
import sqlalchemy as sa
from alembic import op


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('pull_request_reviews',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('pr_id', sa.Uuid(), nullable=False),
    sa.Column('requested_by', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('queued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('pr_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('head_sha', sa.String(length=40), nullable=True),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('risk', sa.String(length=10), nullable=True),
    sa.Column('notes', sa.String(length=1500), nullable=True),
    sa.Column('files_total', sa.Integer(), nullable=False),
    sa.Column('files_reviewed', sa.Integer(), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('error', sa.String(length=500), nullable=True),
    sa.CheckConstraint("status IN ('queued', 'running', 'ready', 'failed')", name=op.f('ck_pull_request_reviews_status_valid')),
    sa.ForeignKeyConstraint(['pr_id'], ['pull_requests.id'], name=op.f('fk_pull_request_reviews_pr_id_pull_requests'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_pull_request_reviews_requested_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pull_request_reviews'))
    )
    op.create_index(op.f('ix_pull_request_reviews_pr_id'), 'pull_request_reviews', ['pr_id'], unique=False)
    op.create_table('review_findings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('review_id', sa.Uuid(), nullable=False),
    sa.Column('file_path', sa.String(length=500), nullable=False),
    sa.Column('start_line', sa.Integer(), nullable=False),
    sa.Column('end_line', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('confidence', sa.String(length=10), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('explanation', sa.Text(), nullable=False),
    sa.Column('suggestion', sa.Text(), nullable=False),
    sa.Column('origin', sa.String(length=5), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.CheckConstraint("confidence IN ('high', 'medium', 'low')", name=op.f('ck_review_findings_confidence_valid')),
    sa.CheckConstraint("origin IN ('ai', 'scan')", name=op.f('ck_review_findings_origin_valid')),
    sa.CheckConstraint("severity IN ('critical', 'high', 'medium', 'low', 'info')", name=op.f('ck_review_findings_severity_valid')),
    sa.CheckConstraint("status IN ('open', 'dismissed')", name=op.f('ck_review_findings_status_valid')),
    sa.ForeignKeyConstraint(['review_id'], ['pull_request_reviews.id'], name=op.f('fk_review_findings_review_id_pull_request_reviews'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_review_findings'))
    )
    op.create_index(op.f('ix_review_findings_review_id'), 'review_findings', ['review_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_review_findings_review_id'), table_name='review_findings')
    op.drop_table('review_findings')
    op.drop_index(op.f('ix_pull_request_reviews_pr_id'), table_name='pull_request_reviews')
    op.drop_table('pull_request_reviews')
