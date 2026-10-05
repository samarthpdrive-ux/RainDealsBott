from sqlalchemy import Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class MaintenanceSetting(Base):
    __tablename__ = "maintenance_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
