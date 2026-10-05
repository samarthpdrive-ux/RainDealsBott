"""Add UPI payment/conversion fields to the deposits table.

Run once before deploying the matching code:
    python migrate_deposit_amounts.py

The migration is idempotent and never changes existing deposit values.
"""

from sqlalchemy import text

from database import engine


COLUMNS = [
    ("received_amount", "DECIMAL(20, 8) NULL"),
    ("inr_amount", "DECIMAL(20, 2) NULL"),
    ("conversion_rate", "DECIMAL(20, 8) NULL"),
]


def column_exists(connection, column: str) -> bool:
    return bool(connection.execute(text("""
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = 'deposits'
          AND column_name = :column
    """), {"column": column}).scalar())


def main() -> None:
    with engine.begin() as connection:
        for column, definition in COLUMNS:
            if not column_exists(connection, column):
                connection.execute(text(
                    f"ALTER TABLE `deposits` ADD COLUMN `{column}` {definition}"
                ))
                print(f"Added deposits.{column}")
            else:
                print(f"deposits.{column} already exists")


if __name__ == "__main__":
    main()
