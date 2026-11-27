"""Add the network profile visibility setting."""

from alembic import op
import sqlalchemy as sa


revision = "0004_network_profile_controls"
down_revision = "0003_explicit_node_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    settings = sa.table("settings", sa.column("key", sa.String), sa.column("value", sa.Text))
    op.bulk_insert(settings, [{"key": "network_profiles_enabled", "value": "false"}])


def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key = 'network_profiles_enabled'")
