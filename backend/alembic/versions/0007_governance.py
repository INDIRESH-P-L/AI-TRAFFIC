"""Governance: hash-chained audit ledger and scoped API keys.

Existing audit rows predate the chain and keep NULL sequence/hash values.
`verify_chain` only walks chained entries, so the ledger reports honestly that
history before this migration is unchained rather than claiming an integrity
guarantee it cannot provide for those rows.

Revision ID: 0007_governance
Revises: 0006_optimizer
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_governance"
down_revision = "0006_optimizer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.add_column(sa.Column("sequence", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("previous_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("entry_hash", sa.String(length=64), nullable=True))

    op.create_index("ix_audit_logs_sequence", "audit_logs", ["sequence"], unique=True)
    op.create_index("ix_audit_logs_entry_hash", "audit_logs", ["entry_hash"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=24), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index("ix_audit_logs_entry_hash", table_name="audit_logs")
    op.drop_index("ix_audit_logs_sequence", table_name="audit_logs")

    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.drop_column("entry_hash")
        batch_op.drop_column("previous_hash")
        batch_op.drop_column("sequence")
