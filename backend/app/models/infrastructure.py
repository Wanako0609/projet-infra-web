from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.services.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Infrastructure(Base):
    __tablename__ = "infrastructures"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=False, default="")
    owner_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Topologie complète au format graphe JSON : {schema_version, nodes, links}
    definition = Column(JSON, nullable=False, default=dict)
    status = Column(String(32), nullable=False, default="stopped")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    owner = relationship("User", back_populates="infrastructures")
    shares = relationship(
        "InfrastructureShare",
        back_populates="infrastructure",
        cascade="all, delete-orphan",
    )


class InfrastructureShare(Base):
    __tablename__ = "infrastructure_shares"
    __table_args__ = (
        UniqueConstraint(
            "infrastructure_id",
            "user_id",
            name="uq_infrastructure_share_user",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    infrastructure_id = Column(
        Integer,
        ForeignKey("infrastructures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # En V1, le partage est strictement en lecture seule
    permission = Column(String(32), nullable=False, default="read_only")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    infrastructure = relationship("Infrastructure", back_populates="shares")
    user = relationship("User", back_populates="shared_infrastructures")
