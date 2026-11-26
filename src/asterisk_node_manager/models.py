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
    settings = Column(JSON, nullable=False, default=dict)
    network = relationship("Network", back_populates="nodes")


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
