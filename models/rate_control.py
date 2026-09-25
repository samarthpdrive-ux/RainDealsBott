"""Saved per-product prices used by the Custom Rates 'Rate Control' mode."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ProductRateControl(Base):
    """One reusable custom price for a product."""

    __tablename__ = "product_rate_controls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RateControlAssignment(Base):
    """Makes all configured Rate Control prices available to one user."""

    __tablename__ = "rate_control_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
