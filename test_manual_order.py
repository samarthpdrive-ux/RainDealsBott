import uuid
import requests

API_URL = "http://127.0.0.1:8081/api/reseller"

# Only reseller API key. No internal secret.
API_KEY = "AK__fKpvT2_4g5ILsrXys_Ig2gjQ6t7bQGxdpdFWLPHkqw"

# Manual product
PRODUCT_ID = "330001"

# Put the Telegram ID of the customer who should receive delivery.
# This customer must press Start in your separate Delivery Bot first.
CUSTOMER_TELEGRAM_ID = 7943742895


response = requests.post(
    f"{API_URL}?action=order",
    headers={
        "Authorization": f"Bearer {API_KEY}",
    },
    json={
        "product_id": PRODUCT_ID,
        "quantity": 1,
        "external_order_id": f"manual-test-{uuid.uuid4().hex}",
        "delivery_telegram_id": CUSTOMER_TELEGRAM_ID,
    },
    timeout=60,
)

print("STATUS:", response.status_code)
print(response.text)