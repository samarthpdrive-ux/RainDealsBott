from sqlalchemy import text
from database import engine

try:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        print("✅ MySQL Connected Successfully")

except Exception as e:
    print("❌ Connection Failed")
    print(e)