"""SQLAlchemy models compatible with SQLAlchemy 1.4 and 2.x."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from .database import Base
from .encryption import EncryptedText


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(120), primary_key=True)
    value = Column(Text, nullable=False)


class Network(Base):
    __tablename__ = "networks"
    id = Column(Integer, primary_key=True)
    stable_key = Column(String(120), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    schema_version = Column(Integer, nullable=False, default=2)
    registration_method = Column(String(10), nullable=True)
    http_registration_server = Column(String(255), nullable=True)
    iax_registration_server = Column(String(255), nullable=True)
    iax_registration_port = Column(Integer, nullable=True)
    stats_enabled = Column(Boolean, nullable=True)
    stats_post_url = Column(String(500), nullable=True)
    stats_post_interval = Column(Integer, nullable=True)
    node_lookup_method = Column(String(10), nullable=True)
    dns_node_domain = Column(String(255), nullable=True)
    max_dns_node_length = Column(Integer, nullable=True)
    external_node_file = Column(String(500), nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp())
    nodes = relationship("Node", back_populates="network")


class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (CheckConstraint("node_number >= 1000", name="ck_nodes_node_number_min"),)
    id = Column(Integer, primary_key=True)
    node_number = Column(Integer, unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    network_id = Column(ForeignKey("networks.id"))
    enabled = Column(Boolean, nullable=False, default=True)
    rxchannel = Column(String(200), nullable=True)
    duplex = Column(Integer, nullable=True)
    linktolink = Column(Boolean, nullable=True)
    linkmongain = Column(Integer, nullable=True)
    hangtime = Column(Integer, nullable=True)
    althangtime = Column(Integer, nullable=True)
    totime = Column(Integer, nullable=True)
    idrecording = Column(String(200), nullable=True)
    idtalkover = Column(String(200), nullable=True)
    idtime = Column(Integer, nullable=True)
    politeid = Column(Integer, nullable=True)
    context = Column(String(80), nullable=True)
    callerid = Column(String(120), nullable=True)
    accountcode = Column(String(80), nullable=True)
    unlinkedct = Column(String(80), nullable=True)
    remotect = Column(String(80), nullable=True)
    linkunkeyct = Column(String(80), nullable=True)
    holdofftelem = Column(Boolean, nullable=True)
    telemdefault = Column(Integer, nullable=True)
    telemdynamic = Column(Boolean, nullable=True)
    parrot = Column(Integer, nullable=True)
    parrottime = Column(Integer, nullable=True)
    network = relationship("Network", back_populates="nodes")
    simpleusb_settings = relationship("SimpleUSBSettings", back_populates="node",
                                      uselist=False, cascade="all, delete-orphan")
    usbradio_settings = relationship("USBRadioSettings", back_populates="node",
                                     uselist=False, cascade="all, delete-orphan")


class SimpleUSBSettings(Base):
    __tablename__ = "simpleusb_settings"
    id = Column(Integer, primary_key=True)
    node_id = Column(ForeignKey("nodes.id"), nullable=False, unique=True)
    rxboost = Column(Boolean, nullable=True)
    carrierfrom = Column(String(20), nullable=True)
    ctcssfrom = Column(String(20), nullable=True)
    deemphasis = Column(Boolean, nullable=True)
    plfilter = Column(Boolean, nullable=True)
    rxondelay = Column(Integer, nullable=True)
    txoffdelay = Column(Integer, nullable=True)
    invertptt = Column(Boolean, nullable=True)
    preemphasis = Column(Boolean, nullable=True)
    rxmixerset = Column(Integer, nullable=True)
    txmixaset = Column(Integer, nullable=True)
    txmixbset = Column(Integer, nullable=True)
    devstr = Column(String(200), nullable=True)
    serial = Column(String(200), nullable=True)
    node = relationship("Node", back_populates="simpleusb_settings")


class USBRadioSettings(Base):
    __tablename__ = "usbradio_settings"
    id = Column(Integer, primary_key=True)
    node_id = Column(ForeignKey("nodes.id"), nullable=False, unique=True)
    rxboost = Column(Boolean, nullable=True)
    carrierfrom = Column(String(20), nullable=True)
    ctcssfrom = Column(String(20), nullable=True)
    rxdemod = Column(String(20), nullable=True)
    rxondelay = Column(Integer, nullable=True)
    txoffdelay = Column(Integer, nullable=True)
    txboost = Column(Boolean, nullable=True)
    txprelim = Column(Boolean, nullable=True)
    txlimonly = Column(Boolean, nullable=True)
    txtoctype = Column(String(20), nullable=True)
    txmixa = Column(String(20), nullable=True)
    txmixb = Column(String(20), nullable=True)
    rxlpf = Column(Integer, nullable=True)
    rxhpf = Column(Integer, nullable=True)
    txlpf = Column(Integer, nullable=True)
    txhpf = Column(Integer, nullable=True)
    invertptt = Column(Boolean, nullable=True)
    rxmixerset = Column(Integer, nullable=True)
    txmixaset = Column(Integer, nullable=True)
    txmixbset = Column(Integer, nullable=True)
    rxsquelchadj = Column(Integer, nullable=True)
    rxvoiceadj = Column(String(20), nullable=True)
    rxctcssadj = Column(String(20), nullable=True)
    txctcssadj = Column(Integer, nullable=True)
    rxctcssrelax = Column(Integer, nullable=True)
    rxsqhyst = Column(Integer, nullable=True)
    voxhangtime = Column(Integer, nullable=True)
    txctcssdefault = Column(String(40), nullable=True)
    rxctcssfreqs = Column(String(200), nullable=True)
    txctcssfreqs = Column(String(200), nullable=True)
    rxctcssoverride = Column(Boolean, nullable=True)
    rxsquelchdelay = Column(Integer, nullable=True)
    duplex3 = Column(Integer, nullable=True)
    clipledgpio = Column(Integer, nullable=True)
    legacyaudioscaling = Column(Boolean, nullable=True)
    eeprom = Column(Integer, nullable=True)
    hdwtype = Column(Integer, nullable=True)
    devstr = Column(String(200), nullable=True)
    serial = Column(String(200), nullable=True)
    node = relationship("Node", back_populates="usbradio_settings")


class ConfigValue(Base):
    __tablename__ = "config_values"
    __table_args__ = (UniqueConstraint("file_name", "section", "key"),)
    id = Column(Integer, primary_key=True)
    file_name = Column(String(200), nullable=False)
    section = Column(String(200), nullable=False, default="")
    key = Column(String(200), nullable=False)
    default_value = Column(EncryptedText, nullable=False, default="")
    updated_value = Column(EncryptedText, nullable=True)
    secret = Column(Boolean, nullable=False, default=False)

    @property
    def value(self):
        """Effective value: an explicit update, or the stored default."""
        return self.updated_value if self.updated_value is not None else self.default_value

    @value.setter
    def value(self, value):
        self.updated_value = value


class CustomValue(Base):
    """Parsed user edits, merged over primary configuration values at render time."""
    __tablename__ = "custom_values"
    __table_args__ = (UniqueConstraint("file_name", "section", "key"),)
    id = Column(Integer, primary_key=True)
    file_name = Column(String(200), nullable=False)
    section = Column(String(200), nullable=False, default="")
    key = Column(String(200), nullable=False)
    value = Column(EncryptedText, nullable=False)
    secret = Column(Boolean, nullable=False, default=False)


class CustomLine(Base):
    __tablename__ = "custom_lines"
    id = Column(Integer, primary_key=True)
    file_name = Column(String(200), nullable=False)
    section = Column(String(200), nullable=False, default="")
    line_number = Column(Integer, nullable=False)
    content = Column(EncryptedText, nullable=False)
    is_default = Column(Boolean, nullable=False, default=False)
    is_deleted = Column(Boolean, nullable=False, default=False)


class ModuleDirective(Base):
    """A module load rule with a retained built-in value and optional override."""
    __tablename__ = "module_directives"
    id = Column(Integer, primary_key=True)
    section = Column(String(200), nullable=False, default="modules")
    line_number = Column(Integer, nullable=False)
    module = Column(String(255), nullable=False)
    action = Column(String(10), nullable=False)
    is_default = Column(Boolean, nullable=False, default=False)
    is_custom = Column(Boolean, nullable=False, default=False)
    is_deleted = Column(Boolean, nullable=False, default=False)
    updated_module = Column(String(255), nullable=True)
    updated_action = Column(String(10), nullable=True)

    @property
    def effective_module(self):
        return self.updated_module if self.is_custom and self.updated_module else self.module

    @property
    def effective_action(self):
        return self.updated_action if self.is_custom and self.updated_action else self.action

    def revert_to_default(self) -> None:
        self.updated_module = None
        self.updated_action = None
        self.is_custom = False
        self.is_deleted = False


class ExtensionRule(Base):
    """Structured dialplan rule retaining the original rule for future reset."""
    __tablename__ = "extension_rules"
    id = Column(Integer, primary_key=True)
    context = Column(String(200), nullable=False)
    line_number = Column(Integer, nullable=False)
    updated_line_number = Column(Integer, nullable=True)
    directive = Column(String(10), nullable=False)
    extension = Column(String(255), nullable=True)
    priority = Column(String(80), nullable=False)
    application = Column(String(120), nullable=False)
    arguments = Column(Text, nullable=True)
    is_default = Column(Boolean, nullable=False, default=False)
    is_custom = Column(Boolean, nullable=False, default=False)
    is_deleted = Column(Boolean, nullable=False, default=False)
    updated_directive = Column(String(10), nullable=True)
    updated_extension = Column(String(255), nullable=True)
    updated_priority = Column(String(80), nullable=True)
    updated_application = Column(String(120), nullable=True)
    updated_arguments = Column(Text, nullable=True)

    def revert_to_default(self) -> None:
        self.updated_directive = None
        self.updated_extension = None
        self.updated_priority = None
        self.updated_application = None
        self.updated_arguments = None
        self.updated_line_number = None
        self.is_custom = False
        self.is_deleted = False

    def render(self) -> str:
        overridden = self.is_default and self.is_custom
        directive = self.updated_directive if overridden else self.directive
        extension = self.updated_extension if overridden else self.extension
        priority = self.updated_priority if overridden else self.priority
        application = self.updated_application if overridden else self.application
        arguments = self.updated_arguments if overridden else self.arguments
        left = extension if directive.lower() == "exten" else None
        parts = [part for part in (left, priority, application) if part is not None]
        payload = ",".join(parts)
        if arguments is not None:
            payload += f"({arguments})"
        return f"{directive} => {payload}"


class Change(Base):
    __tablename__ = "changes"
    id = Column(Integer, primary_key=True)
    actor = Column(String(200), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    summary = Column(Text, nullable=False)
    revision = Column(Integer, unique=True, nullable=False)
    details = Column(JSON, nullable=False, default=dict)


class GeneratedFile(Base):
    __tablename__ = "generated_files"
    revision = Column(ForeignKey("changes.revision"), primary_key=True)
    file_name = Column(String(200), primary_key=True)
    sha256 = Column(String(64), nullable=False)
