# Standalone order manager

This is a separate admin web process. It does not import `bot_app.py`, start Telegram polling, or run the bot's deposit/order loops. It reads and updates the existing store database directly and uses Telegram's Bot API only to notify a customer after an admin marks an order delivered.

## Admin sections

- **Orders:** search by order ID, Telegram user ID, or product; filter by status; deliver eligible manual orders and queue customer notifications.
- **Products:** create products through the same ten-step flow as the bot (name, icon, category, price/freebie, description, delivery type/instructions, preorder, bulk pricing, and stock). The reseller path fetches a live provider catalog and balance, imports the selected service, and rechecks stock and affordability on save. Existing products can be edited, and own-product inventory is recalculated from non-empty lines.
- **Product configuration:** set delivery instructions/type, preorder behavior, low-stock threshold, bulk pricing tiers, provider/service mapping, reseller cost, and API visibility.
- **Users:** look up a customer by Telegram ID or username, inspect account statistics and recent orders, and ban/unban the account.
- **Deposits:** search and review transaction records, status, network, amount, and transaction hash. Verification remains with the bot's payment checker; the manager does not offer manual payment approval.
- **Providers:** create/edit provider connections and toggle availability. Existing API credentials are never rendered back into the form; blank secret fields preserve stored values.
- **Tickets:** inspect recent support tickets and mark them open/closed.
- **System:** toggle the shared bot maintenance setting.

Broadcasting and financial/deposit approval actions are intentionally not exposed as one-click operations. Product edits made in this separate process do not invalidate an already-running bot process's in-memory product cache immediately; they become visible when that cache refreshes.

## Local run

Run commands from the repository root so the manager can import the shared database and models:

```powershell
pip install -r manager_web/requirements.txt
$env:MANAGER_USERNAME = "your-admin-name"
$env:MANAGER_PASSWORD = "use-a-long-unique-password"
$env:MANAGER_SESSION_SECRET = "generate-a-long-random-secret"
$env:MANAGER_COOKIE_SECURE = "false"
python -m uvicorn manager_web.app:app --host 127.0.0.1 --port 8080
```

The process also needs the same database environment variables as the bot (`MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB`, and any required CA configuration), plus `BOT_TOKEN`. Configure `DELIVERY_BOT_TOKEN` when fulfilling manual API orders addressed to a customer's Telegram ID. Keep all credentials in environment variables; do not commit them.

Open `http://127.0.0.1:8080`. The manager creates one additional table, `manager_delivery_outbox`, for durable, retryable Telegram delivery notifications. Existing order/product/user tables remain shared with the bot.

## Separate Render service

Create a new **Web Service** from the same repository, with the repository root as its root directory. Use:

- Build command: `pip install -r manager_web/requirements.txt`
- Start command: `python -m uvicorn manager_web.app:app --host 0.0.0.0 --port $PORT`

Copy the database connection variables and `BOT_TOKEN` into this new service's environment, then set unique `MANAGER_USERNAME`, `MANAGER_PASSWORD`, and `MANAGER_SESSION_SECRET` values. Keep `MANAGER_COOKIE_SECURE=true` for HTTPS. This service has its own deployment and resource allocation; the Telegram bot does not need to import or host the manager.

Orders are queried in pages of 50. Delivery updates lock the order row, refuse already-completed/refunded orders, save the delivery, and enqueue a notification in the same transaction. The worker retries failed Telegram sends and the dashboard exposes a manual retry action after retry exhaustion. For API orders, set the customer's Telegram ID on the order or enter it in the delivery form; the manager will not send API-customer credentials to the API-key owner's account by default.
