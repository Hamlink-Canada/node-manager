"""SQLAlchemy models compatible with SQLAlchemy 1.4 and 2.x."""

from sqlalchemy import (
    Boolean,
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
    registration_method = Column(String(10), nullable=False, default="http")
    http_registration_server = Column(String(255), nullable=False, default="")
    iax_registration_server = Column(String(255), nullable=False, default="")
    iax_registration_port = Column(Integer, nullable=False, default=4569)
    stats_enabled = Column(Boolean, nullable=False, default=False)
    stats_post_url = Column(String(500), nullable=False, default="")
    stats_post_interval = Column(Integer, nullable=False, default=60)
    node_lookup_method = Column(String(10), nullable=False, default="both")
    dns_node_domain = Column(String(255), nullable=False, default="")
    max_dns_node_length = Column(Integer, nullable=False, default=6)
    external_node_file = Column(String(500), nullable=False, default="")
    updated_at = Column(DateTime, nullable=False, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp())
    nodes = relationship("Node", back_populates="network")


class Node(Base):
    __tablename__ = "nodes"
    id = Column(Integer, primary_key=True)
    node_number = Column(Integer, unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    network_id = Column(ForeignKey("networks.id"))
    enabled = Column(Boolean, nullable=False, default=True)
    rxchannel = Column(String(200), nullable=False, default="Local/pseudo")
    duplex = Column(Integer, nullable=False, default=2)
    linktolink = Column(Boolean, nullable=False, default=False)
    linkmongain = Column(Integer, nullable=False, default=0)
    hangtime = Column(Integer, nullable=False, default=5000)
    althangtime = Column(Integer, nullable=False, default=0)
    totime = Column(Integer, nullable=False, default=180000)
    idrecording = Column(String(200), nullable=False, default="|iNOTSET")
    idtalkover = Column(String(200), nullable=False, default="")
    idtime = Column(Integer, nullable=False, default=300000)
    politeid = Column(Integer, nullable=False, default=30000)
    context = Column(String(80), nullable=False, default="radio")
    callerid = Column(String(120), nullable=False, default='"Repeater" <0000000000>')
    accountcode = Column(String(80), nullable=False, default="RADIO")
    unlinkedct = Column(String(80), nullable=False, default="ct2")
    remotect = Column(String(80), nullable=False, default="ct3")
    linkunkeyct = Column(String(80), nullable=False, default="ct8")
    holdofftelem = Column(Boolean, nullable=False, default=False)
    telemdefault = Column(Integer, nullable=False, default=2)
    telemdynamic = Column(Boolean, nullable=False, default=True)
    parrot = Column(Integer, nullable=False, default=0)
    parrottime = Column(Integer, nullable=False, default=1000)
    network = relationship("Network", back_populates="nodes")
    simpleusb_settings = relationship("SimpleUSBSettings", back_populates="node",
                                      uselist=False, cascade="all, delete-orphan")
    usbradio_settings = relationship("USBRadioSettings", back_populates="node",
                                     uselist=False, cascade="all, delete-orphan")


class SimpleUSBSettings(Base):
    __tablename__ = "simpleusb_settings"
    id = Column(Integer, primary_key=True)
    node_id = Column(ForeignKey("nodes.id"), nullable=False, unique=True)
    rxboost = Column(Boolean, nullable=False, default=False)
    carrierfrom = Column(String(20), nullable=False, default="usbinvert")
    ctcssfrom = Column(String(20), nullable=False, default="usbinvert")
    deemphasis = Column(Boolean, nullable=False, default=False)
    plfilter = Column(Boolean, nullable=False, default=True)
    rxondelay = Column(Integer, nullable=False, default=0)
    txoffdelay = Column(Integer, nullable=False, default=0)
    invertptt = Column(Boolean, nullable=False, default=False)
    preemphasis = Column(Boolean, nullable=False, default=False)
    rxmixerset = Column(Integer, nullable=False, default=500)
    txmixaset = Column(Integer, nullable=False, default=500)
    txmixbset = Column(Integer, nullable=False, default=500)
    node = relationship("Node", back_populates="simpleusb_settings")


class USBRadioSettings(Base):
    __tablename__ = "usbradio_settings"
    id = Column(Integer, primary_key=True)
    node_id = Column(ForeignKey("nodes.id"), nullable=False, unique=True)
    rxboost = Column(Boolean, nullable=False, default=True)
    carrierfrom = Column(String(20), nullable=False, default="dsp")
    ctcssfrom = Column(String(20), nullable=False, default="dsp")
    rxdemod = Column(String(20), nullable=False, default="flat")
    rxondelay = Column(Integer, nullable=False, default=0)
    txoffdelay = Column(Integer, nullable=False, default=0)
    txboost = Column(Boolean, nullable=False, default=False)
    txprelim = Column(Boolean, nullable=False, default=True)
    txlimonly = Column(Boolean, nullable=False, default=True)
    txtoctype = Column(String(20), nullable=False, default="notone")
    txmixa = Column(String(20), nullable=False, default="composite")
    txmixb = Column(String(20), nullable=False, default="no")
    rxlpf = Column(Integer, nullable=False, default=0)
    rxhpf = Column(Integer, nullable=False, default=0)
    txlpf = Column(Integer, nullable=False, default=0)
    txhpf = Column(Integer, nullable=False, default=0)
    invertptt = Column(Boolean, nullable=False, default=False)
    rxmixerset = Column(Integer, nullable=False, default=500)
    txmixaset = Column(Integer, nullable=False, default=500)
    txmixbset = Column(Integer, nullable=False, default=500)
    rxsquelchadj = Column(Integer, nullable=False, default=500)
    rxvoiceadj = Column(String(20), nullable=False, default="0.5")
    rxctcssadj = Column(String(20), nullable=False, default="0.5")
    txctcssadj = Column(Integer, nullable=False, default=200)
    rxctcssrelax = Column(Integer, nullable=False, default=1)
    rxsqhyst = Column(Integer, nullable=False, default=3000)
    voxhangtime = Column(Integer, nullable=False, default=2000)
    txctcssdefault = Column(String(40), nullable=False, default="100.0")
    rxctcssfreqs = Column(String(200), nullable=False, default="100.0,91.5")
    txctcssfreqs = Column(String(200), nullable=False, default="100.0,91.5")
    rxctcssoverride = Column(Boolean, nullable=False, default=False)
    rxsquelchdelay = Column(Integer, nullable=False, default=30)
    duplex3 = Column(Integer, nullable=False, default=0)
    clipledgpio = Column(Integer, nullable=False, default=0)
    legacyaudioscaling = Column(Boolean, nullable=False, default=False)
    eeprom = Column(Integer, nullable=False, default=0)
    hdwtype = Column(Integer, nullable=False, default=0)
    devstr = Column(String(200), nullable=False, default="")
    serial = Column(String(200), nullable=False, default="")
    node = relationship("Node", back_populates="usbradio_settings")


class ConfigValue(Base):
    __tablename__ = "config_values"
    __table_args__ = (UniqueConstraint("file_name", "section", "key"),)
    id = Column(Integer, primary_key=True)
    file_name = Column(String(200), nullable=False)
    section = Column(String(200), nullable=False, default="")
    key = Column(String(200), nullable=False)
    value = Column(Text, nullable=False)
    secret = Column(Boolean, nullable=False, default=False)


class CustomLine(Base):
    __tablename__ = "custom_lines"
    id = Column(Integer, primary_key=True)
    file_name = Column(String(200), nullable=False)
    section = Column(String(200), nullable=False, default="")
    line_number = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)


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
