"""Corridor and network scale: coordination plans, TSP and AVL preemption records.

Revision ID: 0011_corridor_network
Revises: 0010_poller_lease
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_corridor_network"
down_revision = "0010_poller_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coordination_plans",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("corridor_id", sa.String(length=36), sa.ForeignKey("corridors.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("design_speed_kph", sa.Float(), nullable=False),
        sa.Column("speed_basis", sa.String(length=32), nullable=False),
        sa.Column("cycle_sec", sa.Integer(), nullable=False),
        sa.Column("cycle_basis", sa.String(length=48), nullable=False),
        sa.Column("coord_phase", sa.Integer(), nullable=False),
        sa.Column("junction_plans", sa.JSON(), nullable=False),
        sa.Column("bandwidth", sa.JSON(), nullable=True),
        sa.Column("safety_summary", sa.JSON(), nullable=True),
        sa.Column("uncoordinated", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("applied_by", sa.String(length=64), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("apply_results", sa.JSON(), nullable=True),
    )
    op.create_index("ix_coordination_plans_corridor_id", "coordination_plans", ["corridor_id"])

    with op.batch_alter_table("transit_events") as batch:
        batch.add_column(sa.Column("trip_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("decision", sa.String(length=48), nullable=True))
        batch.add_column(sa.Column("decision_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("command_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("distance_m", sa.Float(), nullable=True))
        batch.add_column(sa.Column("bearing_deg", sa.Float(), nullable=True))
        batch.add_column(sa.Column("vehicle_reported_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("details", sa.JSON(), nullable=True))

    with op.batch_alter_table("emergency_events") as batch:
        # Every existing row was an operator request.
        batch.add_column(sa.Column("trigger", sa.String(length=16), nullable=False,
                                   server_default="MANUAL"))
        batch.add_column(sa.Column("command_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("command_status", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("latitude", sa.Float(), nullable=True))
        batch.add_column(sa.Column("longitude", sa.Float(), nullable=True))
        batch.add_column(sa.Column("heading_deg", sa.Float(), nullable=True))
        batch.add_column(sa.Column("eta_sec", sa.Float(), nullable=True))
        batch.add_column(sa.Column("position_reported_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("details", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("emergency_events") as batch:
        for column in ("details", "position_reported_at", "eta_sec", "heading_deg",
                       "longitude", "latitude", "command_status", "command_id", "trigger"):
            batch.drop_column(column)
    with op.batch_alter_table("transit_events") as batch:
        for column in ("details", "vehicle_reported_at", "bearing_deg", "distance_m",
                       "command_id", "decision_reason", "decision", "trip_id"):
            batch.drop_column(column)
    op.drop_index("ix_coordination_plans_corridor_id", table_name="coordination_plans")
    op.drop_table("coordination_plans")
