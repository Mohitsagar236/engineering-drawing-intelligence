from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    pages: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="QUEUED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    findings: Mapped[list["Finding"]] = relationship(back_populates="document", cascade="all, delete-orphan")

class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    page: Mapped[int] = mapped_column(Integer)
    source_text: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(String(255))
    classification: Mapped[str] = mapped_column(String(40), default="MANUAL_REVIEW")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    bbox: Mapped[str] = mapped_column(Text, default="[]")
    engine: Mapped[str] = mapped_column(String(40), default="fallback")
    document: Mapped[Document] = relationship(back_populates="findings")

class Material(Base):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    standard_name: Mapped[str] = mapped_column(String(255), unique=True)
    aliases: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="Unknown")
    asbestos_status: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    conditions: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(Text, default="Local reference; verify before use")
    verification_status: Mapped[str] = mapped_column(String(40), default="UNVERIFIED")
