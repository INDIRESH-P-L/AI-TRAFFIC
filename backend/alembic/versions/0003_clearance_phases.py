"""Track phases in yellow / all-red clearance.

No phase displays green during a clearance interval, so `active_phase` is null
then. The conflict check previously looked only at the green phase, which meant
a conflicting movement could be approved while the opposing approach was still
clearing the intersection.

Revision ID: 0003_clearance
Revises: 0002_phase0
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_clearance"
down_revision = "0002_phase0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("signal_controllers") as batch_op:
        batch_op.add_column(sa.Column("clearing_phases", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("signal_controllers") as batch_op:
        batch_op.drop_column("clearing_phases")
