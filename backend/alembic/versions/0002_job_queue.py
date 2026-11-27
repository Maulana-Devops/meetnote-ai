"""job queue

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-27 00:00:00.000000+00:00

Tabel ini murni aditif. Tidak ada DROP/ALTER pada tabel lama.
"""

from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'job_queue',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('job_type', sa.String(length=40), nullable=False),
        sa.Column('meeting_id', sa.String(length=36), nullable=False),
        sa.Column('run_token', sa.String(length=36), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('worker_id', sa.String(length=100), nullable=True),
        sa.Column('error_category', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['meeting_id'], ['meetings.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_job_queue_status_created_at', 'job_queue', ['status', 'created_at']
    )
    op.create_index('ix_job_queue_meeting_id', 'job_queue', ['meeting_id'])


def downgrade() -> None:
    """Downgrade sengaja dinonaktifkan agar data rapat tidak terhapus."""
    raise RuntimeError(
        "Downgrade sengaja dinonaktifkan; gunakan backup/restore, bukan penghapusan skema."
    )
