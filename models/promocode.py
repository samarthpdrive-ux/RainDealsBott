"""
models/promocode.py
"""

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, BigInteger
from sqlalchemy.sql import func
from database import Base


class PromoCode(Base):
    __tablename__ = "promocodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False, index=True)
    amount = Column(Float, nullable=False)
    max_uses = Column(Integer, default=1)
    used_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_by = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    def remaining_uses(self) -> str:
        if self.max_uses == 0:
            return "∞"
        return str(self.max_uses - self.used_count)

    def can_use(self) -> bool:
        if not self.is_active:
            return False
        if self.max_uses == 0:
            return True
        return self.used_count < self.max_uses