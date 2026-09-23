"""Single-writer lease for the controller poller.

Revision ID: 0010_poller_lease
Revises: 0009_handover

Without this, two API replicas both poll every controller and write two
signal_state_logs rows per observation, doubling every measure derived from
that log. See app/ingest/lease.py for why a heartbeat lease rather than a
database lock.
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_poller_lease"
down_revision = "0009_handover"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "poller_leases",
        # The primary key IS the election: one row per named job, so two
        # instances cannot both believe they hold the same lease.
        sa.Column("name", sa.String(length=64), primary_key=True),
        sa.Column("holder_id", sa.String(length=128), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("poller_leases")
