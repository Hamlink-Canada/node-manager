Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
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
    schema_version = Column(Integer, nullable=False, default=1)
    config = Column(JSON, nullable=False, default=dict)
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
