"""Create generic configuration schema and seed the initial network profile."""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("settings",
        sa.Column("key", sa.String(120), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False))
    op.create_table("networks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stable_key", sa.String(120), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()))
    op.create_table("nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_number", sa.Integer(), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("network_id", sa.Integer(), sa.ForeignKey("networks.id")),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False))
    op.create_table("config_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_name", sa.String(200), nullable=False),
        sa.Column("section", sa.String(200), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("secret", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("file_name", "section", "key"))
    op.create_table("custom_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_name", sa.String(200), nullable=False),
        sa.Column("section", sa.String(200), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False))
    op.create_table("changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, unique=True))
    op.create_table("generated_files",
        sa.Column("revision", sa.Integer(), sa.ForeignKey("changes.revision"), primary_key=True),
        sa.Column("file_name", sa.String(200), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False))

    # This is the only network-specific default in the project.
    networks = sa.table("networks", sa.column("stable_key", sa.String), sa.column("name", sa.String),
                        sa.column("schema_version", sa.Integer), sa.column("config", sa.JSON))
    op.bulk_insert(networks, [{"stable_key": "allstarlink", "name": "AllStarLink",
                               "schema_version": 1, "config": {}}])
    settings = sa.table("settings", sa.column("key", sa.String), sa.column("value", sa.Text))
    op.bulk_insert(settings, [{"key": "advanced_node_networks", "value": "false"}])


def downgrade() -> None:
    op.drop_table("generated_files")
    op.drop_table("changes")
    op.drop_table("custom_lines")
    op.drop_table("config_values")
    op.drop_table("nodes")
    op.drop_table("networks")
    op.drop_table("settings")
