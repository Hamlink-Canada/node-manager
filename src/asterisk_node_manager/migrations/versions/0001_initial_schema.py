"""Intentional migration-history reset: create the current fresh-install schema.

This is intentionally the only migration. The project is net new, so prior
migration history was consolidated and removed; this creates the current schema
from scratch and is not an upgrade path for previously deployed databases.
Configuration text columns use TEXT storage for versioned authenticated
ciphertext; encryption and decryption are handled by the application ORM.
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('changes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('actor', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('revision')
    )
    op.create_table('config_values',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('file_name', sa.String(length=200), nullable=False),
    sa.Column('section', sa.String(length=200), nullable=False),
    sa.Column('key', sa.String(length=200), nullable=False),
    sa.Column('default_value', sa.Text(), nullable=False),
    sa.Column('updated_value', sa.Text(), nullable=True),
    sa.Column('secret', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('file_name', 'section', 'key')
    )
    op.create_table('custom_lines',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('file_name', sa.String(length=200), nullable=False),
    sa.Column('section', sa.String(length=200), nullable=False),
    sa.Column('line_number', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('module_directives',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('section', sa.String(length=200), nullable=False),
    sa.Column('line_number', sa.Integer(), nullable=False),
    sa.Column('module', sa.String(length=255), nullable=False),
    sa.Column('action', sa.String(length=10), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('is_custom', sa.Boolean(), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), nullable=False),
    sa.Column('updated_module', sa.String(length=255), nullable=True),
    sa.Column('updated_action', sa.String(length=10), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('extension_rules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('context', sa.String(length=200), nullable=False),
    sa.Column('line_number', sa.Integer(), nullable=False),
    sa.Column('updated_line_number', sa.Integer(), nullable=True),
    sa.Column('directive', sa.String(length=10), nullable=False),
    sa.Column('extension', sa.String(length=255), nullable=True),
    sa.Column('priority', sa.String(length=80), nullable=False),
    sa.Column('application', sa.String(length=120), nullable=False),
    sa.Column('arguments', sa.Text(), nullable=True),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('is_custom', sa.Boolean(), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), nullable=False),
    sa.Column('updated_directive', sa.String(length=10), nullable=True),
    sa.Column('updated_extension', sa.String(length=255), nullable=True),
    sa.Column('updated_priority', sa.String(length=80), nullable=True),
    sa.Column('updated_application', sa.String(length=120), nullable=True),
    sa.Column('updated_arguments', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('custom_values',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('file_name', sa.String(length=200), nullable=False),
    sa.Column('section', sa.String(length=200), nullable=False),
    sa.Column('key', sa.String(length=200), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.Column('secret', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('file_name', 'section', 'key')
    )
    op.create_table('networks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('stable_key', sa.String(length=120), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('schema_version', sa.Integer(), nullable=False),
    sa.Column('registration_method', sa.String(length=10), nullable=True),
    sa.Column('http_registration_server', sa.String(length=255), nullable=True),
    sa.Column('iax_registration_server', sa.String(length=255), nullable=True),
    sa.Column('iax_registration_port', sa.Integer(), nullable=True),
    sa.Column('stats_enabled', sa.Boolean(), nullable=True),
    sa.Column('stats_post_url', sa.String(length=500), nullable=True),
    sa.Column('stats_post_interval', sa.Integer(), nullable=True),
    sa.Column('node_lookup_method', sa.String(length=10), nullable=True),
    sa.Column('dns_node_domain', sa.String(length=255), nullable=True),
    sa.Column('max_dns_node_length', sa.Integer(), nullable=True),
    sa.Column('external_node_file', sa.String(length=500), nullable=True),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stable_key')
    )
    op.create_table('settings',
    sa.Column('key', sa.String(length=120), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('generated_files',
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('file_name', sa.String(length=200), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['revision'], ['changes.revision'], ),
    sa.PrimaryKeyConstraint('revision', 'file_name')
    )
    op.create_table('nodes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('node_number', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('network_id', sa.Integer(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('rxchannel', sa.String(length=200), nullable=True),
    sa.Column('duplex', sa.Integer(), nullable=True),
    sa.Column('linktolink', sa.Boolean(), nullable=True),
    sa.Column('linkmongain', sa.Integer(), nullable=True),
    sa.Column('hangtime', sa.Integer(), nullable=True),
    sa.Column('althangtime', sa.Integer(), nullable=True),
    sa.Column('totime', sa.Integer(), nullable=True),
    sa.Column('idrecording', sa.String(length=200), nullable=True),
    sa.Column('idtalkover', sa.String(length=200), nullable=True),
    sa.Column('idtime', sa.Integer(), nullable=True),
    sa.Column('politeid', sa.Integer(), nullable=True),
    sa.Column('context', sa.String(length=80), nullable=True),
    sa.Column('callerid', sa.String(length=120), nullable=True),
    sa.Column('accountcode', sa.String(length=80), nullable=True),
    sa.Column('unlinkedct', sa.String(length=80), nullable=True),
    sa.Column('remotect', sa.String(length=80), nullable=True),
    sa.Column('linkunkeyct', sa.String(length=80), nullable=True),
    sa.Column('holdofftelem', sa.Boolean(), nullable=True),
    sa.Column('telemdefault', sa.Integer(), nullable=True),
    sa.Column('telemdynamic', sa.Boolean(), nullable=True),
    sa.Column('parrot', sa.Integer(), nullable=True),
    sa.Column('parrottime', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['network_id'], ['networks.id'], ),
    sa.CheckConstraint('node_number >= 1000', name='ck_nodes_node_number_min'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('node_number')
    )
    op.create_table('simpleusb_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('node_id', sa.Integer(), nullable=False),
    sa.Column('rxboost', sa.Boolean(), nullable=True),
    sa.Column('carrierfrom', sa.String(length=20), nullable=True),
    sa.Column('ctcssfrom', sa.String(length=20), nullable=True),
    sa.Column('deemphasis', sa.Boolean(), nullable=True),
    sa.Column('plfilter', sa.Boolean(), nullable=True),
    sa.Column('rxondelay', sa.Integer(), nullable=True),
    sa.Column('txoffdelay', sa.Integer(), nullable=True),
    sa.Column('invertptt', sa.Boolean(), nullable=True),
    sa.Column('preemphasis', sa.Boolean(), nullable=True),
    sa.Column('rxmixerset', sa.Integer(), nullable=True),
    sa.Column('txmixaset', sa.Integer(), nullable=True),
    sa.Column('txmixbset', sa.Integer(), nullable=True),
    sa.Column('devstr', sa.String(length=200), nullable=True),
    sa.Column('serial', sa.String(length=200), nullable=True),
    sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('node_id')
    )
    op.create_table('usbradio_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('node_id', sa.Integer(), nullable=False),
    sa.Column('rxboost', sa.Boolean(), nullable=True),
    sa.Column('carrierfrom', sa.String(length=20), nullable=True),
    sa.Column('ctcssfrom', sa.String(length=20), nullable=True),
    sa.Column('rxdemod', sa.String(length=20), nullable=True),
    sa.Column('rxondelay', sa.Integer(), nullable=True),
    sa.Column('txoffdelay', sa.Integer(), nullable=True),
    sa.Column('txboost', sa.Boolean(), nullable=True),
    sa.Column('txprelim', sa.Boolean(), nullable=True),
    sa.Column('txlimonly', sa.Boolean(), nullable=True),
    sa.Column('txtoctype', sa.String(length=20), nullable=True),
    sa.Column('txmixa', sa.String(length=20), nullable=True),
    sa.Column('txmixb', sa.String(length=20), nullable=True),
    sa.Column('rxlpf', sa.Integer(), nullable=True),
    sa.Column('rxhpf', sa.Integer(), nullable=True),
    sa.Column('txlpf', sa.Integer(), nullable=True),
    sa.Column('txhpf', sa.Integer(), nullable=True),
    sa.Column('invertptt', sa.Boolean(), nullable=True),
    sa.Column('rxmixerset', sa.Integer(), nullable=True),
    sa.Column('txmixaset', sa.Integer(), nullable=True),
    sa.Column('txmixbset', sa.Integer(), nullable=True),
    sa.Column('rxsquelchadj', sa.Integer(), nullable=True),
    sa.Column('rxvoiceadj', sa.String(length=20), nullable=True),
    sa.Column('rxctcssadj', sa.String(length=20), nullable=True),
    sa.Column('txctcssadj', sa.Integer(), nullable=True),
    sa.Column('rxctcssrelax', sa.Integer(), nullable=True),
    sa.Column('rxsqhyst', sa.Integer(), nullable=True),
    sa.Column('voxhangtime', sa.Integer(), nullable=True),
    sa.Column('txctcssdefault', sa.String(length=40), nullable=True),
    sa.Column('rxctcssfreqs', sa.String(length=200), nullable=True),
    sa.Column('txctcssfreqs', sa.String(length=200), nullable=True),
    sa.Column('rxctcssoverride', sa.Boolean(), nullable=True),
    sa.Column('rxsquelchdelay', sa.Integer(), nullable=True),
    sa.Column('duplex3', sa.Integer(), nullable=True),
    sa.Column('clipledgpio', sa.Integer(), nullable=True),
    sa.Column('legacyaudioscaling', sa.Boolean(), nullable=True),
    sa.Column('eeprom', sa.Integer(), nullable=True),
    sa.Column('hdwtype', sa.Integer(), nullable=True),
    sa.Column('devstr', sa.String(length=200), nullable=True),
    sa.Column('serial', sa.String(length=200), nullable=True),
    sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('node_id')
    )
    # AllStarLink is the sole network-specific profile included by default.
    networks = sa.table(
        "networks",
        sa.column("stable_key", sa.String),
        sa.column("name", sa.String),
        sa.column("schema_version", sa.Integer),
        sa.column("registration_method", sa.String),
        sa.column("http_registration_server", sa.String),
        sa.column("iax_registration_server", sa.String),
        sa.column("iax_registration_port", sa.Integer),
        sa.column("stats_enabled", sa.Boolean),
        sa.column("stats_post_url", sa.String),
        sa.column("stats_post_interval", sa.Integer),
        sa.column("node_lookup_method", sa.String),
        sa.column("dns_node_domain", sa.String),
        sa.column("max_dns_node_length", sa.Integer),
        sa.column("external_node_file", sa.String),
    )
    op.bulk_insert(networks, [{
        "stable_key": "allstarlink",
        "name": "AllStarLink",
        "schema_version": 2,
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
    }])


def downgrade() -> None:
    op.drop_table("usbradio_settings")
    op.drop_table("simpleusb_settings")
    op.drop_table("nodes")
    op.drop_table("generated_files")
    op.drop_table("custom_values")
    op.drop_table("extension_rules")
    op.drop_table("module_directives")
    op.drop_table("custom_lines")
    op.drop_table("config_values")
    op.drop_table("settings")
    op.drop_table("networks")
    op.drop_table("changes")
