"""Store only values that differ from declared field defaults."""

from alembic import op
import sqlalchemy as sa


revision = "0007_sparse_config_defaults"
down_revision = "0006_explicit_network_settings"
branch_labels = None
depends_on = None


DEFAULTS = {
    "nodes": {
        "rxchannel": "Local/pseudo", "duplex": 2, "linktolink": False, "linkmongain": 0,
        "hangtime": 5000, "althangtime": 0, "totime": 180000, "idrecording": "|iNOTSET",
        "idtalkover": "", "idtime": 300000, "politeid": 30000, "context": "radio",
        "callerid": '"Repeater" <0000000000>', "accountcode": "RADIO", "unlinkedct": "ct2",
        "remotect": "ct3", "linkunkeyct": "ct8", "holdofftelem": False,
        "telemdefault": 2, "telemdynamic": True, "parrot": 0, "parrottime": 1000,
    },
    "simpleusb_settings": {
        "rxboost": False, "carrierfrom": "usbinvert", "ctcssfrom": "usbinvert",
        "deemphasis": False, "plfilter": True, "rxondelay": 0, "txoffdelay": 0,
        "invertptt": False, "preemphasis": False, "rxmixerset": 500,
        "txmixaset": 500, "txmixbset": 500,
    },
    "usbradio_settings": {
        "rxboost": True, "carrierfrom": "dsp", "ctcssfrom": "dsp", "rxdemod": "flat",
        "rxondelay": 0, "txoffdelay": 0, "txboost": False, "txprelim": True,
        "txlimonly": True, "txtoctype": "notone", "txmixa": "composite", "txmixb": "no",
        "rxlpf": 0, "rxhpf": 0, "txlpf": 0, "txhpf": 0, "invertptt": False,
        "rxmixerset": 500, "txmixaset": 500, "txmixbset": 500, "rxsquelchadj": 500,
        "rxvoiceadj": "0.5", "rxctcssadj": "0.5", "txctcssadj": 200, "rxctcssrelax": 1,
        "rxsqhyst": 3000, "voxhangtime": 2000, "txctcssdefault": "100.0",
        "rxctcssfreqs": "100.0,91.5", "txctcssfreqs": "100.0,91.5",
        "rxctcssoverride": False, "rxsquelchdelay": 30, "duplex3": 0, "clipledgpio": 0,
        "legacyaudioscaling": False, "eeprom": 0, "hdwtype": 0, "devstr": "", "serial": "",
    },
    "networks": {
        "registration_method": "http", "http_registration_server": "",
        "iax_registration_server": "", "iax_registration_port": 4569, "stats_enabled": False,
        "stats_post_url": "", "stats_post_interval": 60, "node_lookup_method": "both",
        "dns_node_domain": "", "max_dns_node_length": 6, "external_node_file": "",
    },
}


def _sparsify(table_name, defaults):
    bind = op.get_bind()
    columns = {column["name"]: column for column in sa.inspect(bind).get_columns(table_name)}
    table = sa.table(table_name, *[sa.column(key, columns[key]["type"]) for key in defaults])
    with op.batch_alter_table(table_name) as batch:
        for key, column in columns.items():
            if key in defaults:
                batch.alter_column(key, existing_type=column["type"], nullable=True,
                                   existing_nullable=False,
                                   existing_server_default=column.get("default"), server_default=None)
    for key, value in defaults.items():
        bind.execute(table.update().where(table.c[key] == value).values({key: None}))


def upgrade():
    # SQLite needs FK enforcement disabled while Alembic rebuilds referenced
    # tables to drop NOT NULL constraints. Alembic's autocommit block is
    # required because SQLite ignores this pragma inside a transaction.
    context = op.get_context()
    with context.autocommit_block():
        op.get_bind().exec_driver_sql("PRAGMA foreign_keys=OFF")
    for table_name, defaults in DEFAULTS.items():
        _sparsify(table_name, defaults)
    with context.autocommit_block():
        op.get_bind().exec_driver_sql("PRAGMA foreign_keys=ON")


def downgrade():
    context = op.get_context()
    with context.autocommit_block():
        op.get_bind().exec_driver_sql("PRAGMA foreign_keys=OFF")
    for table_name, defaults in DEFAULTS.items():
        table = sa.table(table_name, *[sa.column(key) for key in defaults])
        for key, value in defaults.items():
            op.get_bind().execute(table.update().where(table.c[key].is_(None)).values({key: value}))
        columns = {column["name"]: column for column in
                   sa.inspect(op.get_bind()).get_columns(table_name)}
        with op.batch_alter_table(table_name) as batch:
            for key, value in defaults.items():
                server_default = sa.true() if value is True else sa.false() if value is False else str(value)
                batch.alter_column(key, existing_type=columns[key]["type"], nullable=False,
                                   server_default=server_default)
    with context.autocommit_block():
        op.get_bind().exec_driver_sql("PRAGMA foreign_keys=ON")
