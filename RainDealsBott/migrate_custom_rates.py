"""Create the custom_rates table. Safe to run more than once.

Run: python migrate_custom_rates.py
"""

from database import Base, engine
from models.product import Product  # noqa: F401 - registers referenced table metadata
from models.custom_rate import CustomRate  # noqa: F401 - registers table metadata


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine, tables=[CustomRate.__table__])
    print("custom_rates table is ready")
