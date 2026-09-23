"""Operator shift handover.

The generated snapshot is stored separately from the operator's notes and is
never overwritten by editing, so a reader can see both what the platform
reported and what the operator added. Sign-off freezes the record: a handover
the next shift has already acted on cannot be revised.

Revision ID: 0009_handover
Revises: 0008_incidents
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_handover"
down_revision = "0008_incidents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shift_handovers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("shift_start", sa.DateTime(), nullable=False),
        sa.Column("shift_end", sa.DateTime(), nullable=False),
        sa.Column("outgoing_operator", sa.String(length=64), nullable=False),
        sa.Column("incoming_operator", sa.String(length=64), nullable=True),
        sa.Column("generated_snapshot", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("operator_notes", sa.Text(), nullable=True),
        sa.Column("pending_actions", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("signed_off_at", sa.DateTime(), nullable=True),
        sa.Column("signed_off_by", sa.String(length=64), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shift_handovers_shift_end", "shift_handovers", ["shift_end"])
    op.create_index("ix_shift_handovers_status", "shift_handovers", ["status"])


def downgrade() -> None:
    op.drop_index("ix_shift_handovers_status", table_name="shift_handovers")
    op.drop_index("ix_shift_handovers_shift_end", table_name="shift_handovers")
    op.drop_table("shift_handovers")
