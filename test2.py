import time
import uuid
import requests

BASE_URL = "https://raindealsbotapi.onrender.com"
API_KEY = "AK_Xl2R76jtYgZI149TQ9_h6s2cXVGD5Kx5Hd6BtTmQ_nM"


def test_create_manual_order(service_id, quantity, customer_telegram_id):
    """
    CRITICAL RULE: The recipient MUST open @raindeliverybot and press Start first!
    Telegram blocks messages from bots to users who haven't started a conversation.
    """
    url = f"{BASE_URL}/api/v1/order"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    client_order_id = f"manual-{int(time.time())}-{uuid.uuid4().hex[:8]}"

    payload = {
        "service_id": service_id,
        "quantity": quantity,
        "delivery_telegram_id": customer_telegram_id,  # Must be numeric integer ID
        "client_order_id": client_order_id
    }

    print(f"Placing manual order for Telegram ID: {customer_telegram_id}...")
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    print("Status Code:", response.status_code)
    print("Response JSON:", response.json())


if __name__ == "__main__":
    # Ensure customer started @raindeliverybot before executing
    test_create_manual_order(service_id=1, quantity=1, customer_telegram_id=7943742895)