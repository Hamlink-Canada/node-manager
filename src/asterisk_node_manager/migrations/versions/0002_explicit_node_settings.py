Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
"""Normalize common node and SimpleUSB settings into typed database fields."""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "0002_explicit_node_settings"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


SIMPLEUSB_DEFAULTS = {
    "rxboost": False,
    "carrierfrom": "usbinvert",
    "ctcssfrom": "usbinvert",
    "deemphasis": False,
    "plfilter": True,
    "rxondelay": 0,
    "txoffdelay": 0,
    "invertptt": False,
    "preemphasis": False,
    "rxmixerset": 500,
    "txmixaset": 500,
    "txmixbset": 500,
}

NODE_DEFAULTS = {
    "linktolink": False, "linkmongain": 0, "hangtime": 5000, "althangtime": 0,
    "totime": 180000, "idrecording": "|iNOTSET", "idtalkover": "", "idtime": 300000,
    "politeid": 30000, "context": "radio", "callerid": '"Repeater" <0000000000>',
    "accountcode": "RADIO", "unlinkedct": "ct2", "remotect": "ct3", "linkunkeyct": "ct8",
    "holdofftelem": False, "telemdefault": 2, "telemdynamic": True, "parrot": 0, "parrottime": 1000,
}


def upgrade() -> None:
    op.add_column("nodes", sa.Column("rxchannel", sa.String(200), nullable=False,
                                      server_default="Local/pseudo"))
    op.add_column("nodes", sa.Column("duplex", sa.Integer(), nullable=False, server_default="2"))
    for key, default in NODE_DEFAULTS.items():
        col_type = sa.Boolean() if isinstance(default, bool) else sa.Integer() if isinstance(default, int) else sa.String(200)
        server_default = sa.true() if default is True else sa.false() if default is False else str(default)
        op.add_column("nodes", sa.Column(key, col_type, nullable=False, server_default=server_default))
    op.create_table(
        "simpleusb_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("nodes.id"), nullable=False, unique=True),
        sa.Column("rxboost", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("carrierfrom", sa.String(20), nullable=False, server_default="usbinvert"),
        sa.Column("ctcssfrom", sa.String(20), nullable=False, server_default="usbinvert"),
        sa.Column("deemphasis", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("plfilter", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("rxondelay", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("txoffdelay", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invertptt", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("preemphasis", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rxmixerset", sa.Integer(), nullable=False, server_default="500"),
        sa.Column("txmixaset", sa.Integer(), nullable=False, server_default="500"),
        sa.Column("txmixbset", sa.Integer(), nullable=False, server_default="500"),
    )

    bind = op.get_bind()
    config_values = sa.table(
        "config_values",
        sa.column("file_name", sa.String), sa.column("section", sa.String),
        sa.column("key", sa.String), sa.column("value", sa.Text), sa.column("secret", sa.Boolean),
    )
    nodes = sa.table(
        "nodes", sa.column("id", sa.Integer), sa.column("node_number", sa.Integer),
        sa.column("settings", sa.JSON), sa.column("rxchannel", sa.String), sa.column("duplex", sa.Integer),
        *[sa.column(key, sa.Boolean if isinstance(default, bool) else
                    sa.Integer if isinstance(default, int) else sa.String)
          for key, default in NODE_DEFAULTS.items()],
    )
    usb_table = sa.table("simpleusb_settings", sa.column("node_id", sa.Integer),
                         *[sa.column(key, sa.Boolean if isinstance(default, bool) else
                                     sa.Integer if isinstance(default, int) else sa.String)
                           for key, default in SIMPLEUSB_DEFAULTS.items()])
    stored_usb: dict[str, dict[str, str]] = {}
    stored_rpt: dict[str, dict[str, str]] = {}
    for row in bind.execute(sa.select(config_values.c.section, config_values.c.key, config_values.c.value)
                            .where(config_values.c.file_name == "simpleusb.conf")):
        stored_usb.setdefault(row.section, {})[row.key] = row.value
    for row in bind.execute(sa.select(config_values.c.section, config_values.c.key, config_values.c.value)
                            .where(config_values.c.file_name == "rpt.conf")):
        stored_rpt.setdefault(row.section, {})[row.key] = row.value

    migrated_sections: set[str] = set()
    for row in bind.execute(sa.select(nodes.c.id, nodes.c.node_number, nodes.c.settings)).fetchall():
        migrated_sections.add(str(row.node_number))
        raw = row.settings
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = {}
        raw = raw if isinstance(raw, dict) else {}
        rpt_values = stored_rpt.get(str(row.node_number), {})
        rxchannel = str(raw.pop("rxchannel", rpt_values.get("rxchannel", "Local/pseudo")))
        try:
            duplex = int(raw.pop("duplex", rpt_values.get("duplex", "2")))
        except (TypeError, ValueError):
            duplex = 2
        node_values = {"rxchannel": rxchannel, "duplex": duplex}
        for key, default in NODE_DEFAULTS.items():
            value = raw.pop(key, rpt_values.get(key, default))
            if isinstance(default, bool):
                value = str(value).lower() in {"1", "true", "yes", "on"}
            elif isinstance(default, int):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = default
            else:
                value = str(value)
            node_values[key] = value
        bind.execute(nodes.update().where(nodes.c.id == row.id).values(**node_values))

        usb_values = stored_usb.get(str(row.node_number), {})
        values = {"node_id": row.id}
        for key, default in SIMPLEUSB_DEFAULTS.items():
            value = raw.pop(key, usb_values.get(key, default))
            if isinstance(default, bool):
                value = str(value).lower() in {"1", "true", "yes", "on"}
            elif isinstance(default, int):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = default
            else:
                value = str(value)
            values[key] = value
        bind.execute(usb_table.insert().values(**values))

        for key, value in raw.items():
            bind.execute(config_values.insert().values(file_name="rpt.conf", section=str(row.node_number),
                                                       key=key, value=str(value), secret=False))

    for section in migrated_sections:
        if section.isdigit():
            for key in SIMPLEUSB_DEFAULTS:
                bind.execute(config_values.delete().where(config_values.c.file_name == "simpleusb.conf",
                                                          config_values.c.section == section,
                                                          config_values.c.key == key))
    for section in migrated_sections:
        if section.isdigit():
            for key in NODE_DEFAULTS:
                bind.execute(config_values.delete().where(config_values.c.file_name == "rpt.conf",
                                                          config_values.c.section == section,
                                                          config_values.c.key == key))
            for key in ("rxchannel", "duplex"):
                bind.execute(config_values.delete().where(config_values.c.file_name == "rpt.conf",
                                                          config_values.c.section == section,
                                                          config_values.c.key == key))
    op.drop_column("nodes", "settings")


def downgrade() -> None:
    op.add_column("nodes", sa.Column("settings", sa.JSON(), nullable=False,
                                      server_default=sa.text("'{}'")))
    bind = op.get_bind()
    nodes = sa.table("nodes", sa.column("id", sa.Integer), sa.column("settings", sa.JSON),
                     *[sa.column(key, sa.Boolean if isinstance(default, bool) else
                                 sa.Integer if isinstance(default, int) else sa.String)
                       for key, default in NODE_DEFAULTS.items()],
                     sa.column("rxchannel", sa.String), sa.column("duplex", sa.Integer))
    usb = sa.table("simpleusb_settings", sa.column("node_id", sa.Integer),
                   *[sa.column(key, sa.Boolean if isinstance(default, bool) else
                               sa.Integer if isinstance(default, int) else sa.String)
                     for key, default in SIMPLEUSB_DEFAULTS.items()])
    usb_by_node = {row.node_id: {key: getattr(row, key) for key in SIMPLEUSB_DEFAULTS}
                   for row in bind.execute(sa.select(usb))}
    columns = list(NODE_DEFAULTS) + ["rxchannel", "duplex"]
    for row in bind.execute(sa.select(nodes)).fetchall():
        values = {key: getattr(row, key) for key in columns}
        values.update(usb_by_node.get(row.id, {}))
        bind.execute(nodes.update().where(nodes.c.id == row.id).values(settings=json.dumps(values)))
    op.drop_table("simpleusb_settings")
    op.drop_column("nodes", "duplex")
    op.drop_column("nodes", "rxchannel")
    for key in reversed(tuple(NODE_DEFAULTS)):
        op.drop_column("nodes", key)
