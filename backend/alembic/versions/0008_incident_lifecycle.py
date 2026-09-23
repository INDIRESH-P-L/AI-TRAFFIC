"""Incident lifecycle: SLA timers, append-only timeline, traceable evidence.

SLA targets are copied onto the incident at creation rather than read from
policy at report time, so changing a policy later does not retroactively
rewrite whether a past incident met its target.

Revision ID: 0008_incidents
Revises: 0007_governance
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_incidents"
down_revision = "0007_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.add_column(sa.Column("acknowledged_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("acknowledged_by", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("assigned_to", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("assigned_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("sla_acknowledge_sec", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("sla_resolve_sec", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("sla_acknowledge_breached", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("sla_resolve_breached", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    op.create_table(
        "incident_timeline",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("corrects_entry_id", sa.String(length=36), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_incident_timeline_incident_id", "incident_timeline", ["incident_id"])
    op.create_index("ix_incident_timeline_entry_type", "incident_timeline", ["entry_type"])
    op.create_index("ix_incident_timeline_timestamp", "incident_timeline", ["timestamp"])

    op.create_table(
        "incident_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_type", sa.String(length=32), nullable=False),
        sa.Column("source_table", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=True),
        sa.Column("attached_by", sa.String(length=64), nullable=False),
        sa.Column("attached_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_incident_evidence_incident_id", "incident_evidence", ["incident_id"])
    op.create_index("ix_incident_evidence_attached_at", "incident_evidence", ["attached_at"])


def downgrade() -> None:
    op.drop_table("incident_evidence")
    op.drop_table("incident_timeline")

    with op.batch_alter_table("incidents") as batch_op:
        for column in (
            "sla_resolve_breached", "sla_acknowledge_breached",
            "sla_resolve_sec", "sla_acknowledge_sec",
            "assigned_at", "assigned_to", "acknowledged_by", "acknowledged_at",
        ):
            batch_op.drop_column(column)
