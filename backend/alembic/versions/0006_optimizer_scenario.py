"""Optimiser recommendations and the scenario sandbox.

Scenario results get their own table rather than a flag on `traffic_metrics`.
A flag is one forgotten WHERE clause away from a hypothetical number appearing
on the operations map as a measurement; a separate table with different column
names cannot be mixed in by accident.

Revision ID: 0006_optimizer
Revises: 0005_signal_log
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_optimizer"
down_revision = "0005_signal_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scenario_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("intersection_id", sa.String(length=36), nullable=True),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("operator", sa.String(length=64), nullable=False),
        sa.Column("input_movements", sa.JSON(), nullable=False),
        sa.Column("scenario_cycle_length_sec", sa.Integer(), nullable=True),
        sa.Column("scenario_splits", sa.JSON(), nullable=True),
        sa.Column("scenario_expected_delay", sa.JSON(), nullable=True),
        sa.Column("calculation_trace", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("refusal_reason", sa.String(length=64), nullable=True),
        sa.Column("measured_baseline", sa.JSON(), nullable=True),
        sa.Column("comparison", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scenario_runs_intersection_id", "scenario_runs", ["intersection_id"])
    op.create_index("ix_scenario_runs_created_at", "scenario_runs", ["created_at"])

    op.create_table(
        "optimizer_recommendations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("intersection_id", sa.String(length=36), nullable=False),
        sa.Column("controller_id", sa.String(length=36), nullable=True),
        sa.Column("method_version", sa.String(length=48), nullable=False),
        sa.Column("demand_source", sa.String(length=48), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("missing_inputs", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("refusal_reason", sa.String(length=64), nullable=True),
        sa.Column("proposed_cycle_length_sec", sa.Integer(), nullable=True),
        sa.Column("proposed_splits", sa.JSON(), nullable=True),
        sa.Column("expected_delay", sa.JSON(), nullable=True),
        sa.Column("calculation_trace", sa.JSON(), nullable=True),
        sa.Column("safety_verdict", sa.JSON(), nullable=True),
        sa.Column("safety_passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_optimizer_recommendations_intersection_id",
        "optimizer_recommendations", ["intersection_id"],
    )
    op.create_index(
        "ix_optimizer_recommendations_created_at",
        "optimizer_recommendations", ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_optimizer_recommendations_created_at", table_name="optimizer_recommendations")
    op.drop_index("ix_optimizer_recommendations_intersection_id", table_name="optimizer_recommendations")
    op.drop_table("optimizer_recommendations")

    op.drop_index("ix_scenario_runs_created_at", table_name="scenario_runs")
    op.drop_index("ix_scenario_runs_intersection_id", table_name="scenario_runs")
    op.drop_table("scenario_runs")
