"""Observed signal state history.

Every signal performance measure the platform reports - arrival-on-green,
split failures, progression, the corridor time-space diagram - needs to know
which phase was green at a given instant. A current-state snapshot cannot
answer that, so observed phase state is now logged on every controller poll.

Revision ID: 0005_signal_log
Revises: 0004_rules
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_signal_log"
down_revision = "0004_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_state_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("controller_id", sa.String(length=36), nullable=False),
        sa.Column("intersection_id", sa.String(length=36), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("green_phases", sa.JSON(), nullable=True),
        sa.Column("yellow_phases", sa.JSON(), nullable=True),
        sa.Column("red_phases", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("read_latency_ms", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_signal_state_logs_controller_id", "signal_state_logs", ["controller_id"])
    op.create_index("ix_signal_state_logs_intersection_id", "signal_state_logs", ["intersection_id"])
    op.create_index("ix_signal_state_logs_timestamp", "signal_state_logs", ["timestamp"])
    # Corridor and per-junction queries both scan by (intersection, time).
    op.create_index(
        "ix_signal_state_logs_intersection_time",
        "signal_state_logs",
        ["intersection_id", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_signal_state_logs_intersection_time", table_name="signal_state_logs")
    op.drop_index("ix_signal_state_logs_timestamp", table_name="signal_state_logs")
    op.drop_index("ix_signal_state_logs_intersection_id", table_name="signal_state_logs")
    op.drop_index("ix_signal_state_logs_controller_id", table_name="signal_state_logs")
    op.drop_table("signal_state_logs")
