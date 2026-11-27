"""Store supported USBRadio options in explicit per-node columns."""

from alembic import op
import sqlalchemy as sa


revision = "0005_usbradio_settings"
down_revision = "0003_explicit_node_settings"
branch_labels = None
depends_on = None


DEFAULTS = {
    "rxboost": True, "carrierfrom": "dsp", "ctcssfrom": "dsp", "rxdemod": "flat",
    "rxondelay": 0, "txoffdelay": 0, "txboost": False, "txprelim": True,
    "txlimonly": True, "txtoctype": "notone", "txmixa": "composite", "txmixb": "no",
    "rxlpf": 0, "rxhpf": 0, "txlpf": 0, "txhpf": 0, "invertptt": False,
    "rxmixerset": 500, "txmixaset": 500, "txmixbset": 500, "rxsquelchadj": 500,
    "rxvoiceadj": "0.5", "rxctcssadj": "0.5", "txctcssadj": "200",
    "rxctcssrelax": 1, "rxsqhyst": 3000, "voxhangtime": 2000,
    "txctcssdefault": "100.0", "rxctcssfreqs": "100.0,91.5",
    "txctcssfreqs": "100.0,91.5", "rxctcssoverride": False,
    "rxsquelchdelay": 30, "duplex3": 0, "clipledgpio": 0,
    "legacyaudioscaling": False, "eeprom": 0, "hdwtype": 0,
    "devstr": "", "serial": "",
}


def _type(default):
    if isinstance(default, bool):
        return sa.Boolean()
    if isinstance(default, int):
        return sa.Integer()
    return sa.String(200)


def _sql_default(default):
    if default is True:
        return sa.true()
    if default is False:
        return sa.false()
    return str(default)


def _value(default, raw):
    if isinstance(default, bool):
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in {"yes", "true", "1", "on"}
    if isinstance(default, int):
        try:
            return int(raw)
        except ValueError:
            return default
    return raw


def upgrade() -> None:
    op.create_table(
        "usbradio_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("nodes.id"), nullable=False, unique=True),
        *[sa.Column(key, _type(default), nullable=False, server_default=_sql_default(default))
          for key, default in DEFAULTS.items()],
    )
    bind = op.get_bind()
    nodes = sa.table("nodes", sa.column("id", sa.Integer), sa.column("node_number", sa.Integer))
    values = sa.table(
        "config_values", sa.column("file_name", sa.String), sa.column("section", sa.String),
        sa.column("key", sa.String), sa.column("value", sa.Text),
    )
    target = sa.table("usbradio_settings", sa.column("node_id", sa.Integer),
                      *[sa.column(key, _type(default)) for key, default in DEFAULTS.items()])
    by_node = {str(row.node_number): row.id for row in bind.execute(sa.select(nodes))}
    existing = {}
    for row in bind.execute(sa.select(values.c.section, values.c.key, values.c.value).where(
            values.c.file_name == "usbradio.conf")):
        if row.section in by_node and row.key in DEFAULTS:
            existing.setdefault(row.section, {})[row.key] = row.value
    for section, node_id in by_node.items():
        row_values = {key: _value(default, existing.get(section, {}).get(key, default))
                      for key, default in DEFAULTS.items()}
        bind.execute(target.insert().values(node_id=node_id, **row_values))
    for section in existing:
        for key in existing[section]:
            bind.execute(values.delete().where(
                values.c.file_name == "usbradio.conf", values.c.section == section,
                values.c.key == key))


def downgrade() -> None:
    bind = op.get_bind()
    nodes = sa.table("nodes", sa.column("id", sa.Integer),
                     sa.column("node_number", sa.Integer))
    source = sa.table("usbradio_settings", sa.column("node_id", sa.Integer),
                      *[sa.column(key, _type(default)) for key, default in DEFAULTS.items()])
    values = sa.table("config_values", sa.column("file_name", sa.String),
                      sa.column("section", sa.String), sa.column("key", sa.String),
                      sa.column("value", sa.Text), sa.column("secret", sa.Boolean))
    rows = bind.execute(sa.select(nodes.c.node_number, *[source.c[key] for key in DEFAULTS])
                        .select_from(nodes.join(source, nodes.c.id == source.c.node_id))).fetchall()
    for row in rows:
        section = str(row.node_number)
        for key, default in DEFAULTS.items():
            value = row._mapping[key]
            serialized = ("yes" if value else "no") if isinstance(default, bool) else str(value)
            existing = bind.execute(sa.select(values.c.key).where(
                values.c.file_name == "usbradio.conf", values.c.section == section,
                values.c.key == key)).first()
            if existing:
                bind.execute(values.update().where(
                    values.c.file_name == "usbradio.conf", values.c.section == section,
                    values.c.key == key).values(value=serialized, secret=False))
            else:
                bind.execute(values.insert().values(file_name="usbradio.conf", section=section,
                                                    key=key, value=serialized, secret=False))
    op.drop_table("usbradio_settings")
