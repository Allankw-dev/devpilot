"""Code indexing: per-repo index state, per-file hashes, and embedded code chunks

The embedding column is 768 dimensions (app.db.models.EMBEDDING_COLUMN_DIMENSIONS).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-11
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('code_chunks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('repo_id', sa.Uuid(), nullable=False),
    sa.Column('path', sa.String(length=500), nullable=False),
    sa.Column('start_line', sa.Integer(), nullable=False),
    sa.Column('end_line', sa.Integer(), nullable=False),
    sa.Column('language', sa.String(length=30), nullable=True),
    sa.Column('symbol', sa.String(length=200), nullable=True),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('embedding', Vector(768), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['repo_id'], ['repositories.id'], name=op.f('fk_code_chunks_repo_id_repositories'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_code_chunks'))
    )
    op.create_index('ix_code_chunks_embedding', 'code_chunks', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index('ix_code_chunks_repo_id_path', 'code_chunks', ['repo_id', 'path'], unique=False)
    op.create_table('indexed_files',
    sa.Column('repo_id', sa.Uuid(), nullable=False),
    sa.Column('path', sa.String(length=500), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('chunk_count', sa.Integer(), nullable=False),
    sa.Column('chunks_skipped', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['repo_id'], ['repositories.id'], name=op.f('fk_indexed_files_repo_id_repositories'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('repo_id', 'path', name=op.f('pk_indexed_files'))
    )
    op.create_table('repository_indexes',
    sa.Column('repo_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('requested_by', sa.Uuid(), nullable=True),
    sa.Column('queued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('commit_sha', sa.String(length=40), nullable=True),
    sa.Column('embedding_model', sa.String(length=100), nullable=True),
    sa.Column('files_indexed', sa.Integer(), nullable=False),
    sa.Column('files_skipped', sa.Integer(), nullable=False),
    sa.Column('chunks_total', sa.Integer(), nullable=False),
    sa.Column('chunks_skipped', sa.Integer(), nullable=False),
    sa.Column('error', sa.String(length=500), nullable=True),
    sa.CheckConstraint("status IN ('queued', 'running', 'ready', 'failed')", name=op.f('ck_repository_indexes_status_valid')),
    sa.ForeignKeyConstraint(['repo_id'], ['repositories.id'], name=op.f('fk_repository_indexes_repo_id_repositories'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_repository_indexes_requested_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('repo_id', name=op.f('pk_repository_indexes'))
    )


def downgrade() -> None:
    op.drop_table('repository_indexes')
    op.drop_table('indexed_files')
    op.drop_index('ix_code_chunks_repo_id_path', table_name='code_chunks')
    op.drop_index('ix_code_chunks_embedding', table_name='code_chunks')
    op.drop_table('code_chunks')
