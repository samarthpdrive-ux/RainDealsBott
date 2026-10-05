"""
Reseller configuration model.

Stores reseller connection information separately from Product.
"""

from typing import Optional

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Reseller(Base):
    __tablename__ = "resellers"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
    )

    base_url: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    api_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )

    def __repr__(self) -> str:
        return (
            f"<Reseller "
            f"id={self.id} "
            f"name={self.name!r} "
            f"active={self.is_active}>"
        )