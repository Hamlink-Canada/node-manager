"""Store network registration, status, and node-lookup settings in columns."""

import json

from alembic import op
import sqlalchemy as sa


revision = "0006_explicit_network_settings"
down_revision = "0005_usbradio_settings"
branch_labels = None
depends_on = None


COLUMNS = {
    "registration_method": (sa.String(10), "http"),
    "http_registration_server": (sa.String(255), ""),
    "iax_registration_server": (sa.String(255), ""),
    "iax_registration_port": (sa.Integer(), 4569),
    "stats_enabled": (sa.Boolean(), False),
    "stats_post_url": (sa.String(500), ""),
    "stats_post_interval": (sa.Integer(), 60),
    "node_lookup_method": (sa.String(10), "both"),
    "dns_node_domain": (sa.String(255), ""),
    "max_dns_node_length": (sa.Integer(), 6),
    "external_node_file": (sa.String(500), ""),
}


def _coerce(key, value, default):
    if key in {"stats_enabled"}:
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"yes", "true", "1", "on"}
    if key in {"iax_registration_port", "stats_post_interval", "max_dns_node_length"}:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    if isinstance(value, str):
        return value.strip()
    return default


def upgrade() -> None:
    for key, (column_type, default) in COLUMNS.items():
        server_default = (sa.true() if default is True else sa.false() if default is False
                          else str(default))
        op.add_column("networks", sa.Column(key, column_type, nullable=False,
                                             server_default=server_default))

    bind = op.get_bind()
    networks = sa.table(
        "networks", sa.column("id", sa.Integer), sa.column("stable_key", sa.String),
        sa.column("schema_version", sa.Integer), sa.column("config", sa.JSON),
        *[sa.column(key, column_type) for key, (column_type, _) in COLUMNS.items()],
    )
    for row in bind.execute(sa.select(networks.c.id, networks.c.stable_key,
                                     networks.c.config)).fetchall():
        legacy = row.config
        if isinstance(legacy, str):
            try:
                legacy = json.loads(legacy)
            except json.JSONDecodeError:
                legacy = {}
        legacy = legacy if isinstance(legacy, dict) else {}
        values = {key: _coerce(key, legacy.get(key, default), default)
                  for key, (_, default) in COLUMNS.items()}
        # AllStarLink's published endpoints and lookup defaults are the only
        # network-specific values seeded by this migration.
        if row.stable_key == "allstarlink":
            allstar_defaults = {
                "registration_method": "http",
                "http_registration_server": "register.allstarlink.org",
                "iax_registration_server": "register.allstarlink.org",
                "iax_registration_port": 4569,
                "stats_enabled": False,
                "stats_post_url": "http://stats.allstarlink.org/uhandler",
                "stats_post_interval": 60,
                "node_lookup_method": "dns",
                "dns_node_domain": "nodes.allstarlink.org",
                "max_dns_node_length": 6,
                "external_node_file": "/var/lib/asterisk/rpt_extnodes",
            }
            for key, value in allstar_defaults.items():
                if key not in legacy:
                    values[key] = value
        bind.execute(networks.update().where(networks.c.id == row.id)
                     .values(schema_version=2, **values))
    op.drop_column("networks", "config")


def downgrade() -> None:
    op.add_column("networks", sa.Column("config", sa.JSON(), nullable=False,
                                          server_default="{}"))
    for key in reversed(tuple(COLUMNS)):
        op.drop_column("networks", key)
