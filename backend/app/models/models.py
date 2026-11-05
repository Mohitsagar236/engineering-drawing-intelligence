from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    pages: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="QUEUED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    findings: Mapped[list[Finding]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    source_text: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(String(255))
    classification: Mapped[str] = mapped_column(String(40), default="MANUAL_REVIEW")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    bbox: Mapped[str] = mapped_column(Text, default="[]")
    engine: Mapped[str] = mapped_column(String(40), default="unknown")
    document: Mapped[Document] = relationship(back_populates="findings")


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    standard_name: Mapped[str] = mapped_column(String(255), unique=True)
    aliases: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="Unknown")
    asbestos_status: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    conditions: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(Text, default="")
    verification_status: Mapped[str] = mapped_column(String(40), default="UNVERIFIED")
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    manufacturer: Mapped[str] = mapped_column(
        String(255), default="", server_default=""
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=func.now(),
    )


class Job(Base):
    __tablename__ = "processing_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    path: Mapped[str] = mapped_column(Text)
    engine: Mapped[str] = mapped_column(String(40))
    preprocessing: Mapped[str] = mapped_column(Text, default="{}")
    runtime_config: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    status: Mapped[str] = mapped_column(String(40), default="QUEUED", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Page(Base):
    __tablename__ = "document_pages"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("processing_jobs.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(Text)


class Evidence(Base):
    __tablename__ = "finding_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id"), unique=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("processing_jobs.id"), index=True)
    material_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("materials.id"), nullable=True
    )
    is_material: Mapped[int] = mapped_column(Integer, default=0)
    match_score: Mapped[float] = mapped_column(Float, default=0)
    method: Mapped[str] = mapped_column(String(40), default="none")
    explanation: Mapped[str] = mapped_column(Text)
    reference_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    alternatives: Mapped[str] = mapped_column(Text, default="[]")


class Audit(Base):
    __tablename__ = "audit_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[int] = mapped_column(Integer)
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Review(Base):
    __tablename__ = "manual_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id"), index=True)
    actor: Mapped[str] = mapped_column(String(100))
    classification: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RevokedSession(Base):
    __tablename__ = "revoked_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)
