"""Create the tables used by Rate Control. Safe to run more than once.

Run: python migrate_rate_control.py
"""

from database import Base, engine
from models.product import Product  # noqa: F401 - registers referenced table metadata
from models.rate_control import ProductRateControl, RateControlAssignment


if __name__ == "__main__":
    Base.metadata.create_all(
        bind=engine,
        tables=[ProductRateControl.__table__, RateControlAssignment.__table__],
    )
    print("rate control tables are ready")
