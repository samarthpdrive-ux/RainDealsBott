"""
models/referral.py

Referral tracking model. Stores individual referral records.
Uses String with explicit lengths for MySQL compatibility.
Backref names avoid conflicts with existing User model columns.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    referrer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )

    referred_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        unique=True,
    )

    referral_code: Mapped[str] = mapped_column(
        String(100),  # ✅ MySQL requires VARCHAR length
        nullable=False,
    )

    earnings: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),  # ✅ Match User model's Decimal style
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )

    status: Mapped[str] = mapped_column(
        String(20),  # ✅ "active", "inactive", "banned"
        nullable=False,
        default="active",
        server_default="active",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # ------------------------------------------------------------
    # Relationships — NOTE: backref names deliberately chosen to
    # avoid conflict with User.referred_by (which is a Column, not
    # a relationship in your User model).
    # ------------------------------------------------------------

    referrer = relationship(
        "User",
        foreign_keys=[referrer_id],
        backref="referrals_made",  # ✅ Will appear as User.referrals_made
    )

    referred = relationship(
        "User",
        foreign_keys=[referred_id],
        backref="referral_record",  # ✅ Will appear as User.referral_record
        # NOT 'referred_by' — that already exists as a Column in User
    )

    @property
    def earnings_display(self) -> float:
        """Safe float conversion for Telegram display only."""
        return float(self.earnings)

    def __repr__(self) -> str:
        return (
            f"<Referral id={self.id} "
            f"referrer_id={self.referrer_id} "
            f"referred_id={self.referred_id}>"
        )