"""Safe sample data used only by the isolated demo mode."""

from __future__ import annotations

from sqlalchemy import select

from .database import session_factory
from .migrate import upgrade_database
from .models import Change, ConfigValue, Node, Setting, SimpleUSBSettings

DEMO_USERNAME = "demo"


def initialize_demo(database) -> None:
    """Create the schema and seed a small, generic demonstration database."""
    upgrade_database(database)
    sessions = session_factory(database)
    try:
        with sessions.begin() as db:
            if (db.scalar(select(Change.id).limit(1)) is not None
                    or db.scalar(select(Node.id).limit(1)) is not None):
                return

            advanced_networks = db.get(Setting, "advanced_node_networks")
            if advanced_networks is not None:
                advanced_networks.value = "false"

            db.add_all([
                Node(node_number=1000, name="Demo Node North", duplex=0,
                     rxchannel="SimpleUSB/1000", simpleusb_settings=SimpleUSBSettings()),
                Node(node_number=1001, name="Demo Node South", duplex=0,
                     rxchannel="SimpleUSB/1001", simpleusb_settings=SimpleUSBSettings()),
                ConfigValue(file_name="iax.conf", section="general", key="bindport",
                            value="4569", secret=False),
                ConfigValue(file_name="extensions.conf", section="demo", key="exten",
                            value="s,1,Answer()", secret=False),
                Change(actor=DEMO_USERNAME, summary="Loaded demonstration data", revision=1,
                       details={"record": "demo", "operation": "initialize"}),
            ])
    finally:
        sessions.kw["bind"].dispose()
