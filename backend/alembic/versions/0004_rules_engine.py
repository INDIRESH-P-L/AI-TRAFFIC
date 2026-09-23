"""Alert rules engine.

Adds operator-defined alert rules with dedupe, cooldown and escalation, plus
the evaluation and delivery records that let a firing be explained after the
fact.

Revision ID: 0004_rules
Revises: 0003_clearance
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_rules"
down_revision = "0003_clearance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("condition_type", sa.String(length=48), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("intersection_id", sa.String(length=36), nullable=True),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("cooldown_sec", sa.Integer(), nullable=False),
        sa.Column("escalate_after_sec", sa.Integer(), nullable=True),
        sa.Column("escalate_to_severity", sa.String(length=32), nullable=True),
        sa.Column("delivery_channels", sa.JSON(), nullable=True),
        sa.Column("webhook_url", sa.String(length=512), nullable=True),
        sa.Column("email_to", sa.String(length=512), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(), nullable=True),
        sa.Column("last_fired_at", sa.DateTime(), nullable=True),
        sa.Column("fire_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_alert_rules_condition_type", "alert_rules", ["condition_type"])
    op.create_index("ix_alert_rules_intersection_id", "alert_rules", ["intersection_id"])

    op.create_table(
        "rule_evaluations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("subject_type", sa.String(length=48), nullable=False),
        sa.Column("subject_id", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("observed", sa.JSON(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("alert_id", sa.String(length=36), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["rule_id"], ["alert_rules.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rule_evaluations_rule_id", "rule_evaluations", ["rule_id"])
    op.create_index("ix_rule_evaluations_outcome", "rule_evaluations", ["outcome"])
    op.create_index("ix_rule_evaluations_evaluated_at", "rule_evaluations", ["evaluated_at"])

    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("alert_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_deliveries_alert_id", "alert_deliveries", ["alert_id"])
    op.create_index("ix_alert_deliveries_attempted_at", "alert_deliveries", ["attempted_at"])

    with op.batch_alter_table("alerts") as batch_op:
        batch_op.add_column(sa.Column("rule_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("dedupe_key", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("observed", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(sa.Column("last_occurrence_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column("escalated", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("escalated_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("original_severity", sa.String(length=32), nullable=True))

    op.create_index("ix_alerts_rule_id", "alerts", ["rule_id"])
    op.create_index("ix_alerts_dedupe_key", "alerts", ["dedupe_key"])


def downgrade() -> None:
    op.drop_index("ix_alerts_dedupe_key", table_name="alerts")
    op.drop_index("ix_alerts_rule_id", table_name="alerts")

    with op.batch_alter_table("alerts") as batch_op:
        for column in (
            "original_severity", "escalated_at", "escalated", "last_occurrence_at",
            "occurrence_count", "observed", "dedupe_key", "rule_id",
        ):
            batch_op.drop_column(column)

    op.drop_table("alert_deliveries")
    op.drop_table("rule_evaluations")
    op.drop_table("alert_rules")
