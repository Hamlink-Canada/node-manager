"""Add structured, secret-free audit details to change records."""

from alembic import op
import sqlalchemy as sa

revision = "0002_change_details"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "changes",
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("changes", "details")
