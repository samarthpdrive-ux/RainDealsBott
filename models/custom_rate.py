"""Per-user product price overrides set by administrators."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class CustomRate(Base):
    __tablename__ = "custom_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    # NULL means the rate applies to every product for this user.
    product_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=True, index=True
    )
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
