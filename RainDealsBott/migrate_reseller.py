"""
migrate_reseller.py

Adds the database columns required for reseller-linked
products and reseller-linked orders.

Safe to run multiple times.
Existing data is preserved.
"""

from sqlalchemy import text

from database import engine


# ============================================================
# RESELLER COLUMNS
# ============================================================

COLUMN_ADDITIONS = [

    # ========================================================
    # PRODUCTS
    # ========================================================

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

    # ========================================================
    # ORDERS
    # ========================================================

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
# CHECK COLUMN
# ============================================================

def column_exists(conn, table_name, column_name):
    result = conn.execute(
        text(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {
            "table_name": table_name,
            "column_name": column_name,
        },
    )

    return result.scalar() > 0


# ============================================================
# MIGRATION
# ============================================================

def main():

    print()
    print("=" * 60)
    print("RESELLER DATABASE MIGRATION")
    print("=" * 60)

    with engine.begin() as conn:

        for table_name, column_name, definition in COLUMN_ADDITIONS:

            print()
            print(
                f"Checking {table_name}.{column_name}..."
            )

            # ------------------------------------------------
            # Already exists
            # ------------------------------------------------

            if column_exists(
                conn,
                table_name,
                column_name,
            ):
                print(
                    f"⏭️ Already exists: "
                    f"{table_name}.{column_name}"
                )
                continue

            # ------------------------------------------------
            # Add column
            # ------------------------------------------------

            sql = (
                f"ALTER TABLE `{table_name}` "
                f"ADD COLUMN `{column_name}` "
                f"{definition}"
            )

            print(
                f"🔧 Adding: "
                f"{table_name}.{column_name}"
            )

            conn.execute(
                text(sql)
            )

            print(
                f"✅ Added: "
                f"{table_name}.{column_name}"
            )

    print()
    print("=" * 60)
    print("✅ RESELLER MIGRATION COMPLETE")
    print("=" * 60)
    print()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()