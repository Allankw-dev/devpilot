"""Saved conversations with the code assistant

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-20
"""
import sqlalchemy as sa
from alembic import op


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('conversations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('repo_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], name=op.f('fk_conversations_org_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['repo_id'], ['repositories.id'], name=op.f('fk_conversations_repo_id_repositories'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_conversations_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversations'))
    )
    op.create_index('ix_conversations_org_id_user_id_updated_at', 'conversations', ['org_id', 'user_id', 'updated_at'], unique=False)
    op.create_table('conversation_messages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=10), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('citations', sa.JSON(), nullable=True),
    sa.Column('confidence', sa.String(length=10), nullable=True),
    sa.Column('missing_context', sa.Text(), nullable=True),
    sa.Column('sources_considered', sa.Integer(), nullable=True),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('user', 'assistant')", name=op.f('ck_conversation_messages_role_valid')),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_conversation_messages_conversation_id_conversations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversation_messages'))
    )
    op.create_index('ix_conversation_messages_conversation_id_created_at', 'conversation_messages', ['conversation_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_conversation_messages_conversation_id_created_at', table_name='conversation_messages')
    op.drop_table('conversation_messages')
    op.drop_index('ix_conversations_org_id_user_id_updated_at', table_name='conversations')
    op.drop_table('conversations')
