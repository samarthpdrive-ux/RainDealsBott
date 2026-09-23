"""Create the tables for external reseller API keys and API orders.

Run once: python migrate_api_keys.py
"""

from sqlalchemy import inspect, text

from database import Base, engine
from models.order import Order  # noqa: F401 - registers referenced table metadata
from models.api_key import ApiKey, ApiOrder


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine, tables=[ApiKey.__table__, ApiOrder.__table__])
    columns = {column["name"] for column in inspect(engine).get_columns("api_keys")}
    if "encrypted_key" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE api_keys ADD COLUMN encrypted_key VARCHAR(255) NULL"))
        print("Added encrypted API key display column")
    print("API key tables are ready")
