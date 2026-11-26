"""SQLAlchemy models for managed configuration and audit history."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class Network(Base):
    __tablename__ = "networks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stable_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    nodes: Mapped[list["Node"]] = relationship(back_populates="network")


class Node(Base):
    __tablename__ = "nodes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    network_id: Mapped[int | None] = mapped_column(ForeignKey("networks.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    network: Mapped[Network | None] = relationship(back_populates="nodes")


class ConfigValue(Base):
    __tablename__ = "config_values"
    __table_args__ = (UniqueConstraint("file_name", "section", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(String(200), nullable=False)
    section: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CustomLine(Base):
    __tablename__ = "custom_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(String(200), nullable=False)
    section: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class Change(Base):
    __tablename__ = "changes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)


class GeneratedFile(Base):
    __tablename__ = "generated_files"
    revision: Mapped[int] = mapped_column(ForeignKey("changes.revision"), primary_key=True)
    file_name: Mapped[str] = mapped_column(String(200), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
