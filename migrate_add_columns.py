"""
migrate_add_columns.py

One-off / idempotent migration for adding reseller support
to the existing products and orders tables.

Adds:

PRODUCTS
--------
source
reseller_service_id
reseller_cost
reseller_name

ORDERS
------
reseller_id
reseller_service_id
reseller_order_id

Existing columns are never removed or modified.

Run:

    python migrate_add_columns.py

This migration is safe to run more than once.
"""


from sqlalchemy import text

from database import engine


# ============================================================
# COLUMNS TO ADD
# ============================================================

COLUMN_ADDITIONS = [
    # --------------------------------------------------------
    # PRODUCTS
    # --------------------------------------------------------

    (
        "products",
        "source",
        "VARCHAR(20) NOT NULL DEFAULT 'own'",
    ),

    (
        "products",
        "reseller_service_id",
        "VARCHAR(255) NULL",
    ),

    (
        "products",
        "reseller_cost",
        "DECIMAL(20, 8) NULL",
    ),

    (
        "products",
        "reseller_name",
        "VARCHAR(255) NULL",
    ),

    # --------------------------------------------------------
    # ORDERS
    # --------------------------------------------------------

    (
        "orders",
        "reseller_id",
        "INT NULL",
    ),

    (
        "orders",
        "reseller_service_id",
        "VARCHAR(255) NULL",
    ),

    (
        "orders",
        "reseller_order_id",
        "VARCHAR(255) NULL",
    ),
]


# ============================================================
# CHECK WHETHER COLUMN EXISTS
# ============================================================

def _column_exists(
    conn,
    table: str,
    column: str,
) -> bool:

    result = conn.execute(
        text(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = :table
              AND column_name = :column
            """
        ),
        {
            "table": table,
            "column": column,
        },
    )

    count = result.scalar()

    return bool(count)


# ============================================================
# MAIN MIGRATION
# ============================================================

def main():

    print("=" * 60)
    print("DATABASE MIGRATION")
    print("Reseller Product / Order Support")
    print("=" * 60)

    with engine.begin() as conn:

        for table, column, column_definition in COLUMN_ADDITIONS:

            print(
                f"\n🔎 Checking {table}.{column} ..."
            )

            exists = _column_exists(
                conn,
                table,
                column,
            )

            if exists:

                print(
                    f"⏭  {table}.{column} already exists."
                )

                continue

            print(
                f"🔧 Adding {table}.{column} ..."
            )

            sql = (
                f"ALTER TABLE `{table}` "
                f"ADD COLUMN `{column}` "
                f"{column_definition}"
            )

            conn.execute(
                text(sql)
            )

            print(
                f"✅ Added {table}.{column}"
            )

    print()
    print("=" * 60)
    print("✅ MIGRATION COMPLETE")
    print("=" * 60)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()