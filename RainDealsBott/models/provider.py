# models/provider.py

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_type: Mapped[str] = mapped_column(String(50), nullable=False, default="generic")
    auth_type: Mapped[str] = mapped_column(String(50), nullable=False, default="api_key")
    api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    configuration: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationship: One Provider -> Many Products
    products: Mapped[List["Product"]] = relationship(
        "Product", back_populates="provider", lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<Provider(id={self.id}, name={self.name!r}, "
            f"provider_key={self.provider_key!r}, base_url={self.base_url!r}, "
            f"is_active={self.is_active})>"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider_key": self.provider_key,
            "base_url": self.base_url,
            "api_type": self.api_type,
            "auth_type": self.auth_type,
            "configuration": self.configuration,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }