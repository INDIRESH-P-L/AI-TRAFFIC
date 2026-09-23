"""Phase 0 provenance columns.

Adds two columns that let the platform record what it actually knows:

* `traffic_metrics.sample_window_sec` - the observation window a flow rate was
  extrapolated from. A null window means `flow_rate_vph` was not calculated,
  replacing the previous silent assumption of a one-minute sample.

* `emergency_events.safety_report` - the full Deterministic Safety Engine
  verdict for a preemption call. Preemption previously recorded
  `safety_clearance_passed = True` without running any check.

Revision ID: 0002_phase0
Revises: 0001_baseline
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_phase0"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("traffic_metrics") as batch_op:
        batch_op.add_column(sa.Column("sample_window_sec", sa.Float(), nullable=True))

    with op.batch_alter_table("emergency_events") as batch_op:
        batch_op.add_column(sa.Column("safety_report", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("emergency_events") as batch_op:
        batch_op.drop_column("safety_report")

    with op.batch_alter_table("traffic_metrics") as batch_op:
        batch_op.drop_column("sample_window_sec")
