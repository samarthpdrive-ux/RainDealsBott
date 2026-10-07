from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from urllib.parse import parse_qs, quote

from aiogram import Bot
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from starlette.middleware.sessions import SessionMiddleware

import config
from database import SessionLocal, engine
from manager_web.outbox import ManagerDeliveryOutbox
from models.api_key import ApiOrder
from models.order import Order
from models.product import Product as _ProductModel
from models.provider import Provider as _ProviderModel
from models.user import User
from models.maintenance_setting import MaintenanceSetting
from models.deposit import Deposit
from models.ticket import Ticket
from services.reseller_manager import ResellerAPIError, ResellerManager


logger = logging.getLogger("manager_web")


@asynccontextmanager
async def lifespan(application: FastAPI):
    _ensure_security_config()
    await asyncio.to_thread(_ensure_schema)
    application.state.main_bot = Bot(token=config.BOT_TOKEN)
    application.state.delivery_bot = Bot(token=config.DELIVERY_BOT_TOKEN) if config.DELIVERY_BOT_TOKEN else None
    application.state.notification_task = asyncio.create_task(
        _notification_worker(), name="manager-delivery-outbox"
    )
    logger.info("Standalone order manager started; Telegram polling is not enabled here")
    try:
        yield
    finally:
        task = getattr(application.state, "notification_task", None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        for name in ("main_bot", "delivery_bot"):
            bot = getattr(application.state, name, None)
            if bot:
                await bot.session.close()


app = FastAPI(
    title="Rain Deals Order Manager",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("MANAGER_SESSION_SECRET") or secrets.token_urlsafe(48),
    max_age=8 * 60 * 60,
    same_site="lax",
    https_only=os.getenv("MANAGER_COOKIE_SECURE", "true").lower() == "true",
)

GENERAL_PENDING_STATUSES = ("pending_manual", "preorder", "processing")
MAX_DELIVERY_TEXT_LENGTH = 3000
OUTBOX_MAX_ATTEMPTS = 8
REFERRAL_COMMISSION_RATE = Decimal(str(getattr(config, "REFERRAL_COMMISSION_RATE", "0.05")))
REFERRAL_CREDIT_TO_BALANCE = getattr(config, "REFERRAL_CREDIT_TO_BALANCE", True)


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _now_naive_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ensure_security_config() -> None:
    required = ("MANAGER_USERNAME", "MANAGER_PASSWORD", "MANAGER_SESSION_SECRET")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Set required standalone manager environment variables: {', '.join(missing)}")
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is required so the manager can notify customers of delivery.")


def _ensure_schema() -> None:
    ManagerDeliveryOutbox.__table__.create(bind=engine, checkfirst=True)
    MaintenanceSetting.__table__.create(bind=engine, checkfirst=True)


def _csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def _verify_csrf(request: Request, submitted: str) -> None:
    expected = request.session.get("csrf", "")
    if not expected or not hmac.compare_digest(expected, submitted):
        raise HTTPException(status_code=403, detail="Form expired. Refresh the page and try again.")


def _require_manager(request: Request):
    if request.session.get("manager_authenticated") is not True:
        return RedirectResponse("/login", status_code=303)
    return None


def _parse_form(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


def _login_page(error: str = "") -> str:
    error_html = f'<p class="error">{escape(error)}</p>' if error else ""
    return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rain Deals Manager Login</title><style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:radial-gradient(ellipse at 18% 15%,#e8fbdc 0,transparent 35%),radial-gradient(ellipse at 90% 85%,#d9f1e9 0,transparent 32%),#f6f8f3;color:#16211d;font:16px system-ui,-apple-system,Segoe UI,sans-serif}}
main{{width:min(940px,100%);display:grid;grid-template-columns:1.05fr .95fr;overflow:hidden;background:#fff;border:1px solid #e4e9e1;border-radius:30px;box-shadow:0 32px 90px #172d1f1c,0 8px 24px #172d1f0d}}
.intro{{position:relative;padding:52px 42px;color:#f5fff5;background:radial-gradient(ellipse at 80% 15%,#b9f77b55,transparent 35%),linear-gradient(145deg,#15251e,#223a2d 65%,#315243);display:flex;flex-direction:column;justify-content:space-between;min-height:490px}}
.mark{{font-size:14px;letter-spacing:.15em;text-transform:uppercase;font-weight:800;color:#c8ff9e}}.intro h1{{font-size:clamp(34px,5vw,55px);letter-spacing:-.06em;line-height:1.02;margin:54px 0 14px}}.intro p{{color:#c7d7cb;line-height:1.6;max-width:360px}}.orb{{align-self:flex-end;width:120px;height:120px;border-radius:50%;background:radial-gradient(circle at 30% 25%,#f6ffde,#a8ec76 35%,#74b887 62%,#284d41);box-shadow:inset -15px -18px 30px #183c33aa,0 16px 42px #a7f58a44;transform:rotate(-18deg)}}
.login{{padding:54px 46px;align-self:center}}.login h2{{font-size:28px;letter-spacing:-.04em;margin:0 0 7px}}.login p{{color:#758279;margin:0 0 28px}}label{{display:block;margin:18px 0 7px;font-size:14px;font-weight:650}}input{{width:100%;padding:14px;border-radius:13px;border:1px solid #dbe3dc;background:#fbfcfa;color:#17221c;font:inherit;outline:none;transition:.2s}}input:focus{{border-color:#75b35e;box-shadow:0 0 0 4px #b8ed8833}}
button{{width:100%;margin-top:22px;padding:14px;border:0;border-radius:13px;background:#14221b;color:#d5ffb1;font-weight:750;font-size:16px;box-shadow:0 5px 0 #08110c;cursor:pointer;transition:transform .18s,box-shadow .18s}}button:hover{{transform:translateY(-2px);box-shadow:0 7px 0 #08110c}}.error{{color:#a3313c!important;background:#fff0ef;padding:10px 12px;border-radius:10px}}
@media(max-width:680px){{body{{padding:14px}}main{{grid-template-columns:1fr;border-radius:22px}}.intro{{min-height:230px;padding:28px}}.intro h1{{font-size:34px;margin:26px 0 6px}}.intro p{{margin:0}}.orb{{width:66px;height:66px;position:absolute;right:34px;top:42px}}.login{{padding:32px 26px}}}}
</style></head><body><main><section class="intro"><div><div class="mark">✳ RAIN DEALS · ADMIN</div><h1>Good to have you back.</h1><p>Your independent control room for orders, products, customers, and system status.</p></div><div class="orb"></div></section><section class="login"><h2>Sign in</h2><p>Enter your manager credentials to continue.</p>{error_html}
<form method="post" action="/login"><label>Admin username</label><input name="username" required autocomplete="username">
<label>Password</label><input name="password" type="password" required autocomplete="current-password"><button>Open control room&nbsp; →</button></form></section></main></body></html>"""


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz():
    return "ok"


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("manager_authenticated") is True:
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(_login_page())


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request):
    form = _parse_form(await request.body())
    correct_user = hmac.compare_digest(form.get("username", ""), os.getenv("MANAGER_USERNAME", ""))
    correct_password = hmac.compare_digest(form.get("password", ""), os.getenv("MANAGER_PASSWORD", ""))
    if not (correct_user and correct_password):
        return HTMLResponse(_login_page("Incorrect username or password."), status_code=401)
    request.session.clear()
    request.session["manager_authenticated"] = True
    request.session["csrf"] = secrets.token_urlsafe(32)
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    form = _parse_form(await request.body())
    _verify_csrf(request, form.get("csrf", ""))
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


def _order_status_filter(query, status: str):
    if status == "pending":
        return query.filter(Order.status.in_(GENERAL_PENDING_STATUSES))
    if status in {"completed", "refunded", "deleted"}:
        return query.filter(Order.status == status)
    if status == "all":
        return query
    return query.filter(Order.status.in_(GENERAL_PENDING_STATUSES))


def _status_label(status: str) -> tuple[str, str]:
    labels = {
        "pending_manual": ("Needs delivery", "pending"),
        "preorder": ("Awaiting stock", "pending"),
        "processing": ("Processing", "pending"),
        "completed": ("Delivered", "done"),
        "refunded": ("Refunded", "muted"),
        "deleted": ("Deleted", "muted"),
    }
    return labels.get(status, (status.replace("_", " ").title(), "muted"))


def _render_order_card(order: Order, username: str | None, full_name: str | None,
                       is_api_order: bool, outbox: ManagerDeliveryOutbox | None,
                       csrf: str) -> str:
    label, tone = _status_label(order.status)
    created = order.created_at.strftime("%d %b %Y, %H:%M UTC") if order.created_at else "—"
    user_label = f"@{username}" if username else (full_name or "Telegram user")
    user_link = f'<a href="tg://user?id={order.telegram_id}">{escape(user_label)}</a>'
    is_deliverable = order.status in ("pending_manual", "preorder") or (
        order.status == "processing" and order.delivery_type in ("manual", "hybrid")
    )
    amount = f"${_money(order.amount):.2f}"
    action_html = ""
    if is_deliverable:
        target_required = is_api_order and not order.delivery_telegram_id
        target_input = (
            '<label>Customer Telegram ID <input name="customer_telegram_id" inputmode="numeric" '
            'placeholder="Required for API order"></label>' if target_required else ""
        )
        action_html = f"""<details class="deliver"><summary>📨 Add delivery and notify</summary>
<form method="post" action="/orders/{order.id}/deliver" class="delivery-form">
<input type="hidden" name="csrf" value="{escape(csrf)}">{target_input}
<label>Delivery details <textarea name="delivery_text" required maxlength="{MAX_DELIVERY_TEXT_LENGTH}"
placeholder="Paste the account, key, link, or delivery instructions"></textarea></label>
<small>Details are kept private and sent to the configured recipient through Telegram.</small>
<button type="submit" class="deliver-button">Mark delivered & notify user</button></form></details>"""
    elif order.status == "completed":
        if outbox and outbox.status == "sent":
            action_html = '<p class="notice success">✅ Delivered and Telegram notification sent.</p>'
        elif outbox and outbox.status in ("queued", "sending"):
            action_html = '<p class="notice">⏳ Delivery saved; Telegram notification is being sent.</p>'
        elif outbox and outbox.status == "failed":
            action_html = f'''<p class="notice error">⚠️ Delivery saved, but notification failed: {escape(outbox.last_error or "Unknown error")}</p>
<form method="post" action="/notifications/{outbox.id}/retry"><input type="hidden" name="csrf" value="{escape(csrf)}">
<button class="secondary">Retry notification</button></form>'''
    return f"""<article class="order-card"><div class="card-head"><div><span class="order-number">Order #{order.id}</span>
<span class="badge {tone}">{escape(label)}</span></div><time>{escape(created)}</time></div>
<div class="order-grid"><div><small>Customer</small><strong>{user_link}</strong><code>{order.telegram_id}</code></div>
<div><small>Product</small><strong>{escape(order.product_name)}</strong><code>Product #{order.product_id or '—'}</code></div>
<div><small>Quantity</small><strong>{order.quantity or 1}</strong></div><div><small>Total</small><strong>{amount}</strong></div>
<div><small>Delivery type</small><strong>{escape(order.delivery_type or '—')}</strong></div></div>{action_html}</article>"""


def _management_nav(active: str) -> str:
    links = (("orders", "/", "Orders"), ("products", "/products", "Products"),
             ("users", "/users", "Customers"), ("deposits", "/deposits", "Deposits"),
             ("providers", "/providers", "Providers"), ("tickets", "/tickets", "Tickets"),
             ("system", "/system", "System"))
    return '<nav class="tabs">' + "".join(
        f'<a class="{"active" if key == active else ""}" href="{path}">{label}</a>'
        for key, path, label in links
    ) + "</nav>"


def _manager_page(title: str, body: str, csrf: str, active: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · Rain Deals Manager</title><style>
:root{{--page:#f5f8f3;--ink:#18231d;--muted:#75847a;--line:#e5ebe3;--panel:#fff;--lime:#c8ff9c;--forest:#183127;--mint:#eff8ea}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;color:var(--ink);background:radial-gradient(ellipse at 8% 0%,#e7f8da 0,transparent 27%),radial-gradient(ellipse at 100% 60%,#e6f4ec 0,transparent 28%),var(--page);font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}}a{{color:#32654a;text-decoration:none}}a:hover{{color:#17251c}}.wrap{{width:min(1320px,100% - 40px);margin:auto;padding:26px 0 70px}}header{{position:sticky;top:12px;z-index:5;display:flex;justify-content:space-between;align-items:center;gap:16px;padding:14px 18px;background:#ffffffd9;border:1px solid #e7ece5;border-radius:20px;box-shadow:0 12px 38px #263d2c10;backdrop-filter:blur(18px)}}header h1{{font-size:20px;letter-spacing:-.04em;margin:0}}.sub,small{{color:var(--muted)}}header .sub{{font-size:12px;margin:1px 0 0}}h2{{font-size:20px;letter-spacing:-.035em}}.tabs{{display:flex;gap:8px;overflow:auto;padding:17px 0}}.tabs a{{white-space:nowrap;padding:10px 16px;border-radius:12px;background:#ffffffa8;border:1px solid #e7ece5;color:#536158;transition:transform .2s,box-shadow .2s}}.tabs a:hover{{transform:translateY(-2px);box-shadow:0 7px 16px #1b36251a}}.tabs a.active{{background:var(--forest);border-color:var(--forest);color:#d8ffb9;box-shadow:0 5px 0 #0e1c15}}
button{{white-space:nowrap;padding:11px 15px;border-radius:12px;background:var(--forest);color:#e0ffca;border:0;box-shadow:0 4px 0 #0c1a12;cursor:pointer;font:650 14px inherit;transition:transform .18s,box-shadow .18s}}button:hover{{transform:translateY(-2px);box-shadow:0 6px 0 #0c1a12}}button.primary{{background:#183127;color:#d7ffb0}}button.danger{{background:#fff0ed;color:#9b3b30;box-shadow:0 4px 0 #f0d5d0}}input,textarea,select{{width:100%;background:#fbfcfa;border:1px solid #dfe7df;border-radius:12px;color:var(--ink);padding:12px 14px;font:inherit;margin:5px 0 12px;outline:none;transition:border-color .2s,box-shadow .2s}}input:focus,textarea:focus,select:focus{{border-color:#82b96c;box-shadow:0 0 0 4px #b8eb9438}}textarea{{min-height:90px}}label{{display:block;color:#425047;font-size:13px;font-weight:650}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}}.panel,.card{{position:relative;background:linear-gradient(145deg,#fff,#fbfdf9);border:1px solid #e4ebe2;border-radius:19px;padding:19px;margin:13px 0;box-shadow:0 10px 28px #253b2b0a,0 2px 5px #253b2b07;transition:transform .22s,box-shadow .22s}}.card:hover{{transform:translateY(-3px);box-shadow:0 18px 38px #253b2b14,0 5px 10px #253b2b08}}.row{{display:flex;gap:12px;align-items:center;flex-wrap:wrap}}.row>*{{flex:1}}.badge{{display:inline-flex;align-items:center;padding:5px 11px;border-radius:99px;background:#edf2ec;color:#546158;font-size:12px;font-weight:700}}.on{{color:#28774e}}.off{{color:#ab4a3c}}.search{{display:flex;gap:9px;align-items:center}}.search input{{flex:1}}.notice{{padding:13px 16px;border-radius:14px;background:#e8f7df;color:#2e6340;margin:12px 0;border:1px solid #d9edcd}}.table{{width:100%;border-collapse:collapse}}.table th,.table td{{padding:12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}.table th{{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}}code{{color:#486653;overflow-wrap:anywhere}}@media(max-width:650px){{.wrap{{width:calc(100% - 24px);padding-top:13px}}header{{top:6px;padding:12px 13px;border-radius:16px}}header h1{{font-size:17px}}.tabs{{padding:13px 0}}.tabs a{{padding:9px 12px;font-size:13px}}.row{{align-items:stretch}}.search{{flex-wrap:wrap}}.search input{{min-width:100%}}.panel,.card{{padding:15px;border-radius:16px}}}}
</style></head><body><main class="wrap"><header><div><h1>✳ Rain Deals <span style="font-weight:450;color:#708078">/ Control room</span></h1><p class="sub">{escape(title)} · Independent admin workspace</p></div>
<form method="post" action="/logout"><input type="hidden" name="csrf" value="{escape(csrf)}"><button>Sign out&nbsp; ↗</button></form></header>
{_management_nav(active)}{body}</main></body></html>"""


def _new_product_wizard(csrf: str, providers: list[_ProviderModel]) -> str:
    provider_options = '<option value="">Choose a configured provider</option>' + ''.join(
        f'<option value="{p.id}">{escape(p.name)}</option>' for p in providers if p.is_active
    )
    return f'''<style>
.wizard-heading{{display:flex;justify-content:space-between;align-items:center;gap:16px}}.eyebrow,.step-label{{font-size:11px;letter-spacing:.12em;font-weight:800;color:#4e8058}}.wizard-heading h2{{font-size:26px;margin:5px 0}}.step-counter{{padding:9px 13px;border-radius:12px;background:#183127;color:#d8ffb9;font-weight:800;box-shadow:0 4px 0 #0c1a12}}.progress-track{{height:7px;border-radius:99px;background:#e9eee7;margin:18px 0 24px;overflow:hidden}}.progress-track span{{display:block;height:100%;width:10%;border-radius:99px;background:linear-gradient(90deg,#8ecb70,#c8ff9c);transition:width .25s ease}}.wizard-step{{min-height:310px;padding:8px 2px}}.wizard-step h3{{font-size:clamp(24px,4vw,34px);letter-spacing:-.05em;margin:14px 0 26px;line-height:1.12}}.source-cards{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px;margin:20px 0}}.source-card,.check-card{{display:flex;align-items:flex-start;gap:12px;padding:17px;border:1px solid #e1e9df;background:#fbfdf9;border-radius:16px;cursor:pointer}}.source-card:has(input:checked){{border-color:#86b875;background:#f1f9eb;box-shadow:0 0 0 3px #b8eb9430}}.source-card input,.check-card input{{width:auto;margin:3px 0 0;accent-color:#32654a}}.source-card span,.check-card span{{display:grid;gap:4px}}.source-card small,.check-card small{{color:#75847a}}.price-box{{max-width:500px}}.check-card{{margin-top:14px}}.wizard-controls{{display:flex;justify-content:space-between;align-items:center;gap:12px;padding-top:17px;border-top:1px solid #e5ebe3}}.wizard-controls span{{font-size:12px;color:#75847a;font-weight:700}}.final-summary{{margin-top:18px;padding:13px 16px;background:#eff8ea;border-radius:13px;color:#34583c}}@media(max-width:600px){{.wizard-heading h2{{font-size:22px}}.wizard-step{{min-height:360px}}.source-cards{{grid-template-columns:1fr}}.wizard-controls{{gap:7px}}.wizard-controls button{{padding:10px 11px;font-size:13px}}}}
</style><section class="panel wizard"><div class="wizard-heading"><div><span class="eyebrow">PRODUCT BUILDER · 10 STEPS</span><h2>Create product</h2><p class="sub">Configure a store product, add free items, or import a live reseller listing.</p></div><div class="step-counter" id="step-counter">01 / 10</div></div>
<div class="progress-track"><span id="wizard-progress"></span></div><form method="post" action="/products/save" id="product-wizard"><input type="hidden" name="csrf" value="{escape(csrf)}"><input type="hidden" name="product_id" value=""><input type="hidden" name="reseller_service_id" id="reseller-service-id"><input type="hidden" name="reseller_cost" id="reseller-cost">
<section class="wizard-step" data-step="1"><span class="step-label">01 · SOURCE</span><h3>Where does this product come from?</h3><div class="source-cards"><label class="source-card"><input type="radio" name="source" value="own" checked><span><b>🏠 Own inventory</b><small>Deliver accounts or codes from your stock.</small></span></label><label class="source-card"><input type="radio" name="source" value="reseller"><span><b>🔗 Reseller import</b><small>Fetch a live catalog and map a provider item.</small></span></label></div>
<div id="provider-import" hidden><label>Provider<select name="provider_id" id="provider-select">{provider_options}</select></label><button type="button" id="fetch-catalog">Fetch live catalog&nbsp; ↗</button><span id="catalog-status" class="sub"></span><label>Available provider products<select id="catalog-select"><option value="">Fetch a catalog first</option></select></label><p id="provider-summary" class="sub"></p><label>Quantity to list<input name="reseller_import_quantity" id="import-quantity" type="number" min="1" value="1"></label></div></section>
<section class="wizard-step" data-step="2" hidden><span class="step-label">02 · IDENTITY</span><h3>Give it a clear product name</h3><label>Product name<input name="name" id="product-name" maxlength="255" placeholder="e.g. Gemini Advanced · 18 months"></label><small>Use a name customers can recognize quickly.</small></section>
<section class="wizard-step" data-step="3" hidden><span class="step-label">03 · APPEARANCE</span><h3>Choose its menu icon</h3><label>Icon or emoji<input name="icon" id="product-icon" maxlength="50" value="📦"></label><small>Examples: 🎬 · 📧 · 🔑 · 🤖</small></section>
<section class="wizard-step" data-step="4" hidden><span class="step-label">04 · DISCOVERY</span><h3>Place it in a category</h3><label>Category<input name="category" id="product-category" maxlength="255" value="general" placeholder="streaming, software, education…"></label></section>
<section class="wizard-step" data-step="5" hidden><span class="step-label">05 · PRICE</span><h3>Set a price—or make it a freebie</h3><div class="price-box"><label>Price per unit (USD)<input name="price" id="product-price" type="number" min="0" step="0.00000001" value="0.00"></label><label class="check-card"><input type="checkbox" id="freebie-toggle"> <span><b>🎁 This is a freebie</b><small>Set price to $0.00 and clearly mark it as free.</small></span></label></div><p id="cost-hint" class="sub"></p></section>
<section class="wizard-step" data-step="6" hidden><span class="step-label">06 · DETAILS</span><h3>Describe what the customer gets</h3><label>Description<textarea name="description" id="product-description" maxlength="5000" placeholder="What is included? How long is it valid?"></textarea></label></section>
<section class="wizard-step" data-step="7" hidden><span class="step-label">07 · FULFILMENT</span><h3>Choose how orders are delivered</h3><label>Delivery type<select name="delivery_type"><option value="automatic">Automatic · instant delivery</option><option value="manual">Manual · admin fulfills</option><option value="hybrid">Hybrid · automatic + manual</option></select></label></section>
<section class="wizard-step" data-step="8" hidden><span class="step-label">08 · CUSTOMER GUIDANCE</span><h3>Add useful delivery instructions</h3><label>Instructions shown after purchase<textarea name="delivery_instruction" maxlength="5000" placeholder="e.g. Change your password after first login. Optional."></textarea></label></section>
<section class="wizard-step" data-step="9" hidden><span class="step-label">09 · AVAILABILITY</span><h3>Set stock and listing behavior</h3><div class="grid"><label>Allow preorders<select name="preorder"><option value="0">No · hide/stop at zero stock</option><option value="1">Yes · accept orders while out of stock</option></select></label><label>Low-stock alert threshold<input name="low_stock_threshold" type="number" min="0" value="3"></label><label>Shop listing<select name="is_active"><option value="1">Enabled</option><option value="0">Disabled</option></select></label><label>Reseller API visibility<select name="api_enabled"><option value="1">Enabled</option><option value="0">Disabled</option></select></label></div></section>
<section class="wizard-step" data-step="10" hidden><span class="step-label">10 · STOCK & DISCOUNTS</span><h3>Add quantity tiers and inventory</h3><label>Bulk pricing tiers<textarea name="bulk_pricing" id="bulk-pricing" placeholder="1-10=5.00&#10;11-50=4.00&#10;51+=3.00"></textarea></label><small>Use MIN-MAX=PRICE or MIN+=PRICE, one tier per line. Leave blank for flat pricing.</small><div id="own-inventory"><label>Accounts / codes (one per line)<textarea name="inventory" id="product-inventory" placeholder="email1@example.com:password&#10;KEY-XXXX-YYYY"></textarea></label><small>Stock is calculated from the number of non-empty lines. This replaces existing inventory when editing.</small></div><div id="reseller-quantity-note" class="notice" hidden>Provider stock and wallet balance are checked before saving. The chosen quantity sets this listing’s available quantity.</div><div class="final-summary" id="wizard-summary"></div></section>
<div class="wizard-controls"><button type="button" id="wizard-back">← Back</button><span id="wizard-dots">Step 1 of 10</span><button type="button" class="primary" id="wizard-next">Continue →</button><button type="submit" class="primary" id="wizard-save" hidden>Save product&nbsp; ✓</button></div></form></section>
<script>
(()=>{{const form=document.getElementById('product-wizard'),steps=[...form.querySelectorAll('.wizard-step')],counter=document.getElementById('step-counter'),progress=document.getElementById('wizard-progress'),back=document.getElementById('wizard-back'),next=document.getElementById('wizard-next'),save=document.getElementById('wizard-save'),dots=document.getElementById('wizard-dots'),sourceInputs=[...form.querySelectorAll('input[name="source"]')],providerBox=document.getElementById('provider-import'),catalogSelect=document.getElementById('catalog-select'),catalogStatus=document.getElementById('catalog-status'),productPrice=document.getElementById('product-price'),freebie=document.getElementById('freebie-toggle');let step=1,products=[],providerBalance='0';
function source(){{return form.querySelector('input[name="source"]:checked').value}}function show(n){{step=n;steps.forEach(x=>x.hidden=Number(x.dataset.step)!==step);counter.textContent=String(step).padStart(2,'0')+' / 10';dots.textContent='Step '+step+' of 10';progress.style.width=(step*10)+'%';back.hidden=step===1;next.hidden=step===10;save.hidden=step!==10;if(step===10)summary()}}
function summary(){{const esc=v=>String(v).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));const n=document.getElementById('product-name').value||'Untitled product',p=productPrice.value||'0';let text='<b>Review:</b> '+esc(n)+' · '+(freebie.checked?'🎁 FREEBIE':'Selling price: $'+esc(p));if(source()==='reseller'){{const option=document.getElementById('provider-select').selectedOptions[0],provider=option?option.textContent:'Provider',quantity=Number(document.getElementById('import-quantity').value||0),unitCost=Number(document.getElementById('reseller-cost').value||0),service=document.getElementById('reseller-service-id').value;text+=' · '+esc(provider)+' · Import quantity: '+quantity+' · Provider cost: $'+unitCost.toFixed(2)+' each · Est. total: $'+(unitCost*quantity).toFixed(2)+' · Service: '+esc(service)}}else{{const count=document.getElementById('product-inventory').value.split(String.fromCharCode(10)).filter(line=>line.trim()).length;text+=' · Own inventory · '+count+' stock lines'}}document.getElementById('wizard-summary').innerHTML=text}}
function validCurrent(){{const panel=steps[step-1];if(step===1&&source()==='reseller'){{if(!document.getElementById('provider-select').value||!document.getElementById('reseller-service-id').value){{alert('Select a provider and fetch/select an in-stock product first.');return false}}if(!document.getElementById('import-quantity').value||Number(document.getElementById('import-quantity').value)<1){{alert('Choose a valid import quantity.');return false}}}}if(step===2&&document.getElementById('product-name').value.trim().length<2){{alert('Enter a product name with at least two characters.');return false}}if(step===5){{if(!freebie.checked&&(!productPrice.value||Number(productPrice.value)<=0)){{alert('Enter a positive price, or check the Freebie option to confirm a $0 price.');return false}}}}if(step===10&&source()==='own'&&!document.getElementById('product-inventory').value.trim()){{if(!confirm('No inventory lines entered. Save this product with zero stock?'))return false}}return true}}
back.addEventListener('click',()=>show(Math.max(1,step-1)));next.addEventListener('click',()=>{{if(validCurrent())show(Math.min(10,step+1))}});sourceInputs.forEach(x=>x.addEventListener('change',()=>{{providerBox.hidden=source()!=='reseller';document.getElementById('own-inventory').hidden=source()!=='own';document.getElementById('reseller-quantity-note').hidden=source()!=='reseller'}}));providerBox.hidden=true;document.getElementById('reseller-quantity-note').hidden=true;
freebie.addEventListener('change',()=>{{if(freebie.checked){{productPrice.value='0';productPrice.readOnly=true}}else{{productPrice.readOnly=false;if(Number(productPrice.value)===0)productPrice.value=''}}}});
document.getElementById('fetch-catalog').addEventListener('click',async()=>{{const id=document.getElementById('provider-select').value;if(!id){{catalogStatus.textContent='Choose a provider first.';return}}catalogStatus.textContent='Contacting provider…';try{{const response=await fetch('/providers/'+encodeURIComponent(id)+'/catalog',{{credentials:'same-origin'}}),data=await response.json();if(!response.ok)throw new Error(data.error||'Catalog fetch failed');products=data.products||[];providerBalance=data.balance||'0';catalogSelect.innerHTML='<option value="">Choose a provider product</option>'+products.map((p,i)=>'<option value="'+i+'">'+p.name.replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]))+' · $'+p.cost+' · stock '+(p.stock>=999999?'∞':p.stock)+'</option>').join('');catalogStatus.textContent=products.length+' in-stock items fetched';document.getElementById('provider-summary').textContent='Provider wallet balance: $'+providerBalance;}}catch(error){{catalogStatus.textContent=error.message}}}});
catalogSelect.addEventListener('change',()=>{{if(catalogSelect.value==='')return;const p=products[Number(catalogSelect.value)];if(!p)return;document.getElementById('reseller-service-id').value=p.service_id;document.getElementById('reseller-cost').value=p.cost;document.getElementById('product-name').value=p.name;document.getElementById('product-icon').value=p.icon;document.getElementById('product-category').value=p.category;document.getElementById('product-description').value=p.description;const affordable=p.cost>0?Math.floor(Number(providerBalance)/Number(p.cost)):0;const max=Math.min(Number(p.stock)||999999,affordable);const qty=document.getElementById('import-quantity');qty.max=max;qty.value=max>0?'1':'0';document.getElementById('provider-summary').textContent='Provider wallet: $'+providerBalance+' · Cost: $'+p.cost+' · Max affordable: '+max;document.getElementById('cost-hint').textContent='Provider cost: $'+p.cost+' · max importable: '+max;productPrice.value=p.cost;freebie.checked=false;productPrice.readOnly=false}});
form.addEventListener('submit',event=>{{const name=document.getElementById('product-name').value.trim();if(name.length<2){{event.preventDefault();show(2);alert('Enter a product name with at least two characters.');return}}if(!freebie.checked&&(!productPrice.value||Number(productPrice.value)<=0)){{event.preventDefault();show(5);alert('Enter a positive price or confirm the freebie option.');return}}if(source()==='reseller'&&!document.getElementById('reseller-service-id').value){{event.preventDefault();show(1);alert('Fetch and select a provider item first.');return}}if(!validCurrent())event.preventDefault()}});show(1)}})();
</script>'''


@app.get("/products", response_class=HTMLResponse)
async def products_page(request: Request, q: str = "", edit: int = 0):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    csrf = _csrf_token(request)
    search = q.strip()[:100]
    db = SessionLocal()
    try:
        query = db.query(_ProductModel)
        if search:
            query = query.filter(or_(_ProductModel.id == int(search), _ProductModel.name.ilike(f"%{search}%"))) if search.isdigit() else query.filter(_ProductModel.name.ilike(f"%{search}%"))
        products = query.order_by(_ProductModel.id.desc()).limit(100).all()
        current = db.query(_ProductModel).filter(_ProductModel.id == edit).first() if edit else None
        providers = db.query(_ProviderModel).order_by(_ProviderModel.name.asc()).all()
        rows = "".join(f'''<article class="card"><div class="row"><div><strong>#{p.id} · {escape(p.icon or '📦')} {escape(p.name)}</strong><br><small>{escape(p.category or 'General')} · ${_money(p.price):.2f}{' · 🎁 FREEBIE' if _money(p.price) == 0 else ''} · stock {p.stock} · {escape(p.source or 'own')}{' · tier pricing' if p.bulk_pricing else ''}</small></div><span class="badge {'on' if p.is_active else 'off'}">{'Shop enabled' if p.is_active else 'Disabled'}</span></div><div class="row"><a href="/products?edit={p.id}">Edit product</a><form method="post" action="/products/{p.id}/toggle"><input type="hidden" name="csrf" value="{escape(csrf)}"><button class="{'danger' if p.is_active else 'primary'}">{'Disable' if p.is_active else 'Enable'} shop</button></form><form method="post" action="/products/{p.id}/api-toggle"><input type="hidden" name="csrf" value="{escape(csrf)}"><button>{'Disable API' if p.api_enabled else 'Enable API'}</button></form></div></article>''' for p in products)
        inventory = (current.file_content or "") if current and current.source == "own" else ""
        title = f"Edit product #{current.id}" if current else "Add product"
        bulk = current.bulk_pricing if current else None
        bulk_text = json.dumps(bulk, indent=2) if isinstance(bulk, (dict, list)) else (bulk or "")
        provider_options = '<option value="">No provider</option>' + ''.join(
            f'<option value="{p.id}" {"selected" if current and current.provider_id == p.id else ""}>{escape(p.name)} · {"active" if p.is_active else "disabled"}</option>' for p in providers
        )
        form = f'''<section class="panel"><h2>{title}</h2><form method="post" action="/products/save"><input type="hidden" name="csrf" value="{escape(csrf)}"><input type="hidden" name="product_id" value="{current.id if current else ''}">
<div class="grid"><label>Name<input name="name" maxlength="255" required value="{escape(current.name if current else '')}"></label><label>Icon<input name="icon" maxlength="50" value="{escape(current.icon if current else '📦')}"></label><label>Retail price<input name="price" type="number" min="0" step="0.00000001" required value="{_money(current.price) if current else '0.00'}"></label><label>Category<input name="category" maxlength="255" value="{escape(current.category if current and current.category else 'General')}"></label>
<label>Source<select name="source"><option value="own" {"selected" if not current or current.source == 'own' else ""}>Own inventory</option><option value="reseller" {"selected" if current and current.source == 'reseller' else ""}>Reseller/provider</option></select></label>
<label>Provider<select name="provider_id">{provider_options}</select></label><label>Provider service ID<input name="reseller_service_id" value="{escape(current.reseller_service_id or '') if current else ''}" maxlength="255"></label><label>Provider cost<input name="reseller_cost" type="number" min="0" step="0.00000001" value="{_money(current.reseller_cost) if current and current.reseller_cost is not None else ''}"></label>
<label>Delivery type<select name="delivery_type">{''.join(f'<option value="{v}" {"selected" if current and current.delivery_type == v else ""}>{v.title()}</option>' for v in ('automatic','manual','hybrid'))}</select></label>
<label>Shop listing<select name="is_active"><option value="1" {"selected" if not current or current.is_active else ""}>Enabled</option><option value="0" {"selected" if current and not current.is_active else ""}>Disabled</option></select></label><label>Reseller API visibility<select name="api_enabled"><option value="1" {"selected" if not current or current.api_enabled else ""}>Enabled</option><option value="0" {"selected" if current and not current.api_enabled else ""}>Disabled</option></select></label>
<label>Allow preorder<select name="preorder"><option value="1" {"selected" if current and current.preorder else ""}>Yes</option><option value="0" {"selected" if not current or not current.preorder else ""}>No</option></select></label><label>Low-stock alert threshold<input name="low_stock_threshold" type="number" min="0" step="1" value="{current.low_stock_threshold if current else 3}"></label></div>
<label>Description<textarea name="description" maxlength="5000">{escape(current.description or '') if current else ''}</textarea></label><label>Delivery instruction<textarea name="delivery_instruction" maxlength="5000">{escape(current.delivery_instruction or '') if current else ''}</textarea></label>
<label>Bulk pricing tiers (JSON)<textarea name="bulk_pricing" placeholder='{{"10":{{"min":10,"max":49,"price":0.8}},"50":{{"min":50,"max":null,"price":0.7}}}}'>{escape(bulk_text)}</textarea></label><small>Leave blank to remove tiers. Each tier uses min, optional max, and per-unit price.</small>
<label>Inventory lines (used only for own products; one item per line)<textarea name="inventory">{escape(inventory)}</textarea></label><small>Saving own inventory replaces current stock and recalculates the count. Reseller inventory remains provider-managed.</small><p><button class="primary">Save product configuration</button> <a href="/products">Cancel</a></p></form></section>'''
        if not current:
            form = _new_product_wizard(csrf, providers)
    finally:
        db.close()
    body = f'''{form}<section><h2>Products ({len(products)} shown; maximum 100)</h2><form class="search" method="get"><input name="q" value="{escape(search)}" placeholder="Search product name or ID"><button>Search</button></form>{rows or '<p class="sub">No products found.</p>'}</section>'''
    notice = request.query_params.get("notice", "")
    if notice:
        body = f'<div class="notice">{escape(notice)}</div>' + body
    return HTMLResponse(_manager_page("Product management", body, csrf, "products"))


@app.post("/products/save")
async def product_save(request: Request):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    form = _parse_form(await request.body())
    _verify_csrf(request, form.get("csrf", ""))
    try:
        name, price = form.get("name", "").strip(), Decimal(form.get("price", ""))
        product_id = int(form["product_id"]) if form.get("product_id") else None
        if not name or len(name) > 255 or price < 0 or not price.is_finite():
            raise ValueError
        source = form.get("source", "own")
        if source not in {"own", "reseller"}:
            raise ValueError
        low_stock_threshold = int(form.get("low_stock_threshold", "3"))
        if low_stock_threshold < 0:
            raise ValueError
        provider_id = int(form["provider_id"]) if form.get("provider_id") else None
        reseller_quantity = int(form.get("reseller_import_quantity", "1"))
        reseller_cost = Decimal(form["reseller_cost"]) if form.get("reseller_cost", "").strip() else None
        if reseller_cost is not None and (reseller_cost < 0 or not reseller_cost.is_finite()):
            raise ValueError
        bulk_raw = form.get("bulk_pricing", "").strip()
        bulk_pricing = None
        if bulk_raw:
            if bulk_raw.startswith(("{", "[")):
                incoming_tiers = json.loads(bulk_raw)
            else:
                incoming_tiers = {}
                for line in bulk_raw.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    range_text, price_text = line.split("=", 1)
                    if "+" in range_text:
                        minimum, maximum = int(range_text.replace("+", "").strip()), None
                    elif "-" in range_text:
                        minimum_text, maximum_text = range_text.split("-", 1)
                        minimum, maximum = int(minimum_text.strip()), int(maximum_text.strip())
                    else:
                        raise ValueError
                    incoming_tiers[str(minimum)] = {"min": minimum, "max": maximum, "price": price_text.strip()}
            if isinstance(incoming_tiers, list):
                incoming_tiers = {str(item.get("min", "")): item for item in incoming_tiers if isinstance(item, dict)}
            if not isinstance(incoming_tiers, dict):
                raise ValueError
            bulk_pricing = {}
            for tier in incoming_tiers.values():
                if not isinstance(tier, dict):
                    raise ValueError
                minimum = int(tier["min"])
                maximum = int(tier["max"]) if tier.get("max") not in (None, "") else None
                tier_price = Decimal(str(tier["price"]))
                if minimum < 1 or (maximum is not None and maximum <= minimum) or tier_price < 0 or not tier_price.is_finite():
                    raise ValueError
                bulk_pricing[str(minimum)] = {"min": minimum, "max": maximum, "price": float(tier_price)}
            sorted_tiers = sorted(bulk_pricing.values(), key=lambda tier: tier["min"])
            for current_tier, next_tier in zip(sorted_tiers, sorted_tiers[1:]):
                if current_tier["max"] is None or current_tier["max"] >= next_tier["min"]:
                    raise ValueError
    except (ValueError, ArithmeticError, KeyError, TypeError, json.JSONDecodeError):
        return RedirectResponse("/products?notice=Check+product+fields+and+bulk+pricing+format", status_code=303)

    if source == "reseller":
        service_id = form.get("reseller_service_id", "").strip()
        if not provider_id or not service_id or reseller_quantity < 1:
            return RedirectResponse("/products?notice=Select+a+provider+product+and+positive+quantity", status_code=303)
        db = SessionLocal()
        try:
            provider = db.query(_ProviderModel).filter(
                _ProviderModel.id == provider_id, _ProviderModel.is_active.is_(True)
            ).first()
            if not provider:
                return RedirectResponse("/products?notice=Provider+not+found+or+disabled", status_code=303)
            provider_data = {"id": provider.id, "name": provider.name, "base_url": provider.base_url,
                             "api_key": provider.api_key, "api_secret": provider.api_secret,
                             "provider_key": provider.provider_key, "api_type": provider.api_type,
                             "auth_type": provider.auth_type, "configuration": provider.configuration,
                             "is_active": provider.is_active}
        finally:
            db.close()
        try:
            reseller_api = ResellerManager(api_key=provider_data["api_key"], base_url=provider_data["base_url"], provider_config=provider_data)
            async with asyncio.timeout(25):
                live_products = await reseller_api.get_products()
                live_balance = await reseller_api.get_balance()
            selected_item = next((item for item in live_products if isinstance(item, dict) and str(
                item.get("service_id") or item.get("productId") or item.get("product_id") or item.get("id") or ""
            ).strip() == service_id), None)
            if not selected_item:
                return RedirectResponse("/products?notice=Provider+product+is+no+longer+available", status_code=303)
            raw_cost = selected_item.get("price")
            if isinstance(raw_cost, dict):
                raw_cost = raw_cost.get("amount", 0)
            verified_cost = Decimal(str(raw_cost or 0))
            raw_stock = selected_item.get("stock")
            if raw_stock is None and isinstance(selected_item.get("availability"), dict):
                raw_stock = selected_item["availability"].get("available")
            live_stock = int(raw_stock) if raw_stock is not None else 999999
            affordable = int(Decimal(str(live_balance)) / verified_cost) if verified_cost > 0 else 0
            if verified_cost <= 0 or not verified_cost.is_finite() or selected_item.get("is_available") is False or live_stock <= 0:
                return RedirectResponse("/products?notice=Provider+product+is+unavailable+or+has+invalid+cost", status_code=303)
            max_quantity = min(live_stock, affordable) if live_stock < 999999 else affordable
            if reseller_quantity > max_quantity:
                return RedirectResponse(f"/products?notice=Quantity+exceeds+the+live+wallet+limit+of+{max_quantity}", status_code=303)
            reseller_cost = verified_cost
        except Exception as exc:
            logger.warning("Live reseller validation failed during product import (%s)", type(exc).__name__)
            return RedirectResponse("/products?notice=Could+not+verify+provider+balance+and+stock", status_code=303)
    db = SessionLocal()
    try:
        product = db.query(_ProductModel).filter(_ProductModel.id == product_id).with_for_update().first() if product_id else _ProductModel(source="own")
        if product is None:
            return RedirectResponse("/products?notice=Product+not+found", status_code=303)
        provider = db.query(_ProviderModel).filter(_ProviderModel.id == provider_id).first() if provider_id else None
        if source == "reseller" and (not provider or not form.get("reseller_service_id", "").strip()):
            return RedirectResponse("/products?notice=Reseller+products+need+a+provider+and+service+ID", status_code=303)
        if source == "own":
            inventory = [line.strip() for line in form.get("inventory", "").splitlines() if line.strip()]
            product.file_content, product.stock = "\n".join(inventory), len(inventory)
            product.provider_id = None
            product.reseller_service_id = None
            product.reseller_cost = None
            product.reseller_name = None
        else:
            product.provider_id = provider.id
            product.reseller_service_id = form.get("reseller_service_id", "").strip()[:255]
            product.reseller_cost = reseller_cost
            product.reseller_name = provider.name
            product.stock = reseller_quantity
            product.source = "reseller"
        product.name = name
        product.icon = form.get("icon", "📦").strip()[:50] or "📦"
        product.description = form.get("description", "").strip() or None
        product.category = form.get("category", "General").strip()[:255] or "General"
        product.price = price
        product.delivery_type = form.get("delivery_type") if form.get("delivery_type") in {"automatic", "manual", "hybrid"} else "manual"
        product.is_active = form.get("is_active") == "1"
        product.api_enabled = form.get("api_enabled") == "1"
        product.preorder = form.get("preorder") == "1"
        product.low_stock_threshold = low_stock_threshold
        product.delivery_instruction = form.get("delivery_instruction", "").strip() or None
        product.bulk_pricing = bulk_pricing
        product.source = source
        db.add(product)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Manager product save failed")
        return RedirectResponse("/products?notice=Could+not+save+product", status_code=303)
    finally:
        db.close()
    return RedirectResponse("/products?notice=Product+saved", status_code=303)


async def _set_product_flag(request: Request, product_id: int, flag: str):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    form = _parse_form(await request.body())
    _verify_csrf(request, form.get("csrf", ""))
    db = SessionLocal()
    try:
        product = db.query(_ProductModel).filter(_ProductModel.id == product_id).with_for_update().first()
        if not product:
            return RedirectResponse("/products?notice=Product+not+found", status_code=303)
        setattr(product, flag, not bool(getattr(product, flag)))
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/products?notice=Product+setting+updated", status_code=303)


@app.post("/products/{product_id}/toggle")
async def product_toggle(request: Request, product_id: int):
    return await _set_product_flag(request, product_id, "is_active")


@app.post("/products/{product_id}/api-toggle")
async def product_api_toggle(request: Request, product_id: int):
    return await _set_product_flag(request, product_id, "api_enabled")


@app.get("/deposits", response_class=HTMLResponse)
async def deposits_page(request: Request, status: str = "pending", q: str = "", page: int = 1):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    csrf, page_size = _csrf_token(request), 40
    status = status if status in {"pending", "completed", "failed", "all"} else "pending"
    search = q.strip()[:100]
    db = SessionLocal()
    try:
        query = db.query(Deposit)
        if status == "pending":
            query = query.filter(Deposit.status.notin_(("completed", "failed")))
        elif status != "all":
            query = query.filter(Deposit.status == status)
        if search:
            if search.isdigit():
                query = query.filter(or_(Deposit.id == int(search), Deposit.telegram_id == int(search)))
            else:
                query = query.filter(or_(Deposit.order_id.ilike(f"%{search}%"), Deposit.tx_hash.ilike(f"%{search}%")))
        total = query.count()
        page_count = max(1, (total + page_size - 1) // page_size)
        page = min(max(1, page), page_count)
        deposits = query.order_by(Deposit.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        rows = "".join(f'''<tr><td><a href="/deposits/{d.id}">#{d.id}</a></td><td><code>{d.telegram_id}</code></td><td>{escape(d.network or '—')}</td><td>${_money(d.received_amount or d.amount):.2f}{f' · ₹{_money(d.inr_amount):.2f}' if d.inr_amount is not None else ''}</td><td><span class="badge {'on' if d.status == 'completed' else 'off' if d.status == 'failed' else ''}">{escape(d.status or 'unknown')}</span></td><td>{d.created_at.strftime('%d %b %Y %H:%M') if d.created_at else '—'}</td></tr>''' for d in deposits)
        tabs = ''.join(f'<a class="{"active" if status == k else ""}" href="/deposits?status={k}">{label}</a>' for k, label in (("pending", "Needs review"), ("completed", "Completed"), ("failed", "Failed"), ("all", "All")))
    finally:
        db.close()
    body = f'''<section class="panel"><h2>Deposit activity</h2><p class="sub">Review payment records and transaction evidence. Automatic verification remains handled by the bot’s payment checker.</p><nav class="tabs">{tabs}</nav><form class="search" method="get"><input type="hidden" name="status" value="{status}"><input name="q" value="{escape(search)}" placeholder="Deposit ID, user ID, order reference, or TX hash"><button>Find deposit</button></form><p class="sub">{total} records · page {page} of {page_count}</p><div style="overflow:auto"><table class="table"><thead><tr><th>Deposit</th><th>Telegram user</th><th>Network</th><th>Amount</th><th>Status</th><th>Created</th></tr></thead><tbody>{rows or '<tr><td colspan="6">No deposits found.</td></tr>'}</tbody></table></div><nav class="tabs"><a href="/deposits?status={status}&page={max(1,page-1)}&q={quote(search)}">← Previous</a><a href="/deposits?status={status}&page={min(page+1,page_count)}&q={quote(search)}">Next →</a></nav></section>'''
    return HTMLResponse(_manager_page("Deposit activity", body, csrf, "deposits"))


@app.get("/deposits/{deposit_id}", response_class=HTMLResponse)
async def deposit_detail(request: Request, deposit_id: int):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    csrf = _csrf_token(request)
    db = SessionLocal()
    try:
        deposit = db.query(Deposit).filter(Deposit.id == deposit_id).first()
        if not deposit:
            body = '<section class="panel"><h2>Deposit not found</h2><a href="/deposits">Return to deposits</a></section>'
        else:
            amount = f"${_money(deposit.received_amount or deposit.amount):.2f}"
            if deposit.inr_amount is not None:
                amount += f" · ₹{_money(deposit.inr_amount):.2f} paid"
            body = f'''<section class="panel"><h2>Deposit #{deposit.id}</h2><div class="grid"><p>Telegram user<br><a href="/users/{deposit.telegram_id}"><code>{deposit.telegram_id}</code></a></p><p>Status<br><strong>{escape(deposit.status or 'unknown')}</strong></p><p>Amount<br><strong>{amount}</strong></p><p>Network<br><strong>{escape(deposit.network or '—')}</strong></p><p>Order reference<br><code>{escape(deposit.order_id or '—')}</code></p><p>Conversion rate<br><strong>{escape(str(deposit.conversion_rate or '—'))}</strong></p><p>Created<br><strong>{deposit.created_at.strftime('%Y-%m-%d %H:%M:%S') if deposit.created_at else '—'}</strong></p></div><label>Transaction hash<input readonly value="{escape(deposit.tx_hash or 'Not submitted')}"></label><p class="sub">This page is a review view only. Do not manually mark a payment complete unless the payment has been independently verified.</p><a href="/deposits">← Back to deposits</a></section>'''
    finally:
        db.close()
    return HTMLResponse(_manager_page("Deposit details", body, csrf, "deposits"), status_code=404 if 'not found' in body else 200)


@app.get("/providers", response_class=HTMLResponse)
async def providers_page(request: Request):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    csrf = _csrf_token(request)
    db = SessionLocal()
    try:
        providers = db.query(_ProviderModel).order_by(_ProviderModel.id.desc()).limit(100).all()
        rows = "".join(f'''<article class="card"><div class="row"><div><strong>#{p.id} · {escape(p.name)}</strong><br><small>Key <code>{escape(p.provider_key)}</code> · {escape(p.api_type)} · auth: {escape(p.auth_type)} · {escape(p.base_url)}</small></div><span class="badge {'on' if p.is_active else 'off'}">{'Active' if p.is_active else 'Disabled'}</span></div><div class="row"><a href="/providers?edit={p.id}">Edit configuration</a><form method="post" action="/providers/{p.id}/toggle"><input type="hidden" name="csrf" value="{escape(csrf)}"><button class="{'danger' if p.is_active else 'primary'}">{'Disable provider' if p.is_active else 'Enable provider'}</button></form></div></article>''' for p in providers)
        edit_id = int(request.query_params.get("edit", "0") or 0)
        current = db.query(_ProviderModel).filter(_ProviderModel.id == edit_id).first() if edit_id else None
    finally:
        db.close()
    provider_type = current.api_type if current else "generic"
    auth_type = current.auth_type if current else "header"
    form = f'''<section class="panel"><h2>{'Update provider' if current else 'Connect a provider'}</h2><p class="sub">Credentials are never displayed back in the page. Leave key/secret empty when editing to keep existing values.</p><form method="post" action="/providers/save"><input type="hidden" name="csrf" value="{escape(csrf)}"><input type="hidden" name="provider_id" value="{current.id if current else ''}"><div class="grid"><label>Provider name<input name="name" required maxlength="255" value="{escape(current.name if current else '')}"></label><label>Unique key<input name="provider_key" required maxlength="100" value="{escape(current.provider_key if current else '')}"></label><label>Base URL<input name="base_url" type="url" required maxlength="500" value="{escape(current.base_url if current else '')}"></label><label>API format<select name="api_type">{''.join(f'<option value="{v}" {"selected" if provider_type == v else ""}>{v}</option>' for v in ('generic','rest','excalibur'))}</select></label><label>Authentication<select name="auth_type">{''.join(f'<option value="{v}" {"selected" if auth_type == v else ""}>{v}</option>' for v in ('header','bearer','query','hmac','wmemail_open'))}</select></label><label>Status<select name="is_active"><option value="1" {"selected" if not current or current.is_active else ""}>Active</option><option value="0" {"selected" if current and not current.is_active else ""}>Disabled</option></select></label></div><div class="grid"><label>API key / token<input type="password" name="api_key" autocomplete="new-password" placeholder="{'Configured — leave blank to keep' if current and current.api_key else 'Enter provider key'}"></label><label>API secret<input type="password" name="api_secret" autocomplete="new-password" placeholder="{'Configured — leave blank to keep' if current and current.api_secret else 'Optional / required for HMAC'}"></label></div><label>Optional JSON configuration<textarea name="configuration" placeholder='{{"balance_path":"balance"}}'>{escape(current.configuration or '') if current else ''}</textarea></label><button class="primary">Save provider</button> <a href="/providers">Cancel</a></form></section>'''
    provider_rows = rows or '<p class="sub">No providers configured.</p>'
    body = form + f'<section><h2>Configured providers</h2>{provider_rows}</section>'
    notice = request.query_params.get("notice", "")
    if notice:
        body = f'<div class="notice">{escape(notice)}</div>' + body
    return HTMLResponse(_manager_page("Provider configuration", body, csrf, "providers"))


@app.post("/providers/save")
async def provider_save(request: Request):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    form = _parse_form(await request.body())
    _verify_csrf(request, form.get("csrf", ""))
    name, key, base_url = (form.get(k, "").strip() for k in ("name", "provider_key", "base_url"))
    provider_id = int(form["provider_id"]) if form.get("provider_id") else None
    if not name or not key or len(name) > 255 or len(key) > 100 or not base_url.startswith(("https://", "http://")):
        return RedirectResponse("/providers?notice=Check+provider+name,+key,+and+base+URL", status_code=303)
    configuration = form.get("configuration", "").strip()
    try:
        parsed_configuration = json.loads(configuration) if configuration else None
        if parsed_configuration is not None and not isinstance(parsed_configuration, dict):
            raise ValueError
    except (ValueError, json.JSONDecodeError):
        return RedirectResponse("/providers?notice=Configuration+must+be+a+JSON+object", status_code=303)
    db = SessionLocal()
    try:
        provider = db.query(_ProviderModel).filter(_ProviderModel.id == provider_id).with_for_update().first() if provider_id else _ProviderModel()
        if not provider:
            return RedirectResponse("/providers?notice=Provider+not+found", status_code=303)
        duplicate = db.query(_ProviderModel.id).filter(_ProviderModel.provider_key == key, _ProviderModel.id != provider.id).first() if provider_id else db.query(_ProviderModel.id).filter(_ProviderModel.provider_key == key).first()
        if duplicate:
            return RedirectResponse("/providers?notice=That+provider+key+is+already+in+use", status_code=303)
        provider.name, provider.provider_key, provider.base_url = name, key, base_url
        provider.api_type = form.get("api_type") if form.get("api_type") in {"generic", "rest", "excalibur"} else "generic"
        provider.auth_type = form.get("auth_type") if form.get("auth_type") in {"header", "bearer", "query", "hmac", "wmemail_open"} else "header"
        provider.configuration = json.dumps(parsed_configuration) if parsed_configuration is not None else None
        provider.is_active = form.get("is_active") == "1"
        if form.get("api_key", "").strip():
            provider.api_key = form["api_key"].strip()
        if form.get("api_secret", "").strip():
            provider.api_secret = form["api_secret"].strip()
        if provider.auth_type == "hmac" and not provider.api_secret:
            return RedirectResponse("/providers?notice=HMAC+providers+require+an+API+secret", status_code=303)
        db.add(provider)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Provider configuration save failed")
        return RedirectResponse("/providers?notice=Could+not+save+provider", status_code=303)
    finally:
        db.close()
    return RedirectResponse("/providers?notice=Provider+configuration+saved", status_code=303)


@app.get("/providers/{provider_id}/catalog")
async def provider_catalog(request: Request, provider_id: int):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    db = SessionLocal()
    try:
        provider = db.query(_ProviderModel).filter(
            _ProviderModel.id == provider_id, _ProviderModel.is_active.is_(True)
        ).first()
        if not provider:
            return JSONResponse({"error": "Provider not found or disabled."}, status_code=404)
        provider_data = {
            "id": provider.id,
            "name": provider.name,
            "base_url": provider.base_url,
            "api_key": provider.api_key,
            "api_secret": provider.api_secret,
            "provider_key": provider.provider_key,
            "api_type": provider.api_type,
            "auth_type": provider.auth_type,
            "configuration": provider.configuration,
            "is_active": provider.is_active,
        }
    finally:
        db.close()
    if not provider_data["api_key"] or not provider_data["base_url"]:
        return JSONResponse({"error": "Provider API key or base URL is missing."}, status_code=400)
    manager = ResellerManager(
        api_key=provider_data["api_key"],
        base_url=provider_data["base_url"],
        provider_config=provider_data,
    )
    try:
        async with asyncio.timeout(25):
            catalog = await manager.get_products()
            balance = await manager.get_balance()
    except (TimeoutError, ResellerAPIError) as exc:
        logger.warning("Web product import fetch failed for provider %s (%s)", provider_id, type(exc).__name__)
        return JSONResponse({"error": "Provider request failed. Check provider settings and try again."}, status_code=502)
    except Exception as exc:
        logger.error("Unexpected provider product fetch failure (%s)", type(exc).__name__)
        return JSONResponse({"error": "Could not fetch the provider catalog. Check server logs."}, status_code=502)
    items = []
    for raw in catalog if isinstance(catalog, list) else []:
        if not isinstance(raw, dict):
            continue
        service_id = str(raw.get("service_id") or raw.get("productId") or raw.get("product_id") or raw.get("id") or "").strip()
        name = str(raw.get("name") or raw.get("title") or "").strip()
        price_raw = raw.get("price")
        if isinstance(price_raw, dict):
            price_raw = price_raw.get("amount", 0)
        try:
            cost = Decimal(str(price_raw or 0))
            if not cost.is_finite() or cost < 0:
                continue
        except Exception:
            continue
        stock_raw = raw.get("stock")
        if stock_raw is None and isinstance(raw.get("availability"), dict):
            stock_raw = raw["availability"].get("available")
        try:
            stock = int(stock_raw) if stock_raw is not None else 999999
        except (ValueError, TypeError):
            stock = 999999
        if not service_id or not name or stock <= 0 or raw.get("is_available") is False:
            continue
        items.append({
            "service_id": service_id,
            "name": name[:255],
            "cost": str(cost),
            "stock": stock,
            "icon": str(raw.get("emoji") or "📦")[:50],
            "category": str(raw.get("productType") or "reseller")[:255],
            "description": str(raw.get("description") or f"Imported from {provider_data['name']}")[:5000],
        })
    return JSONResponse({"provider_id": provider_id, "provider": provider_data["name"], "balance": str(balance), "products": items})


@app.post("/providers/{provider_id}/toggle")
async def provider_toggle(request: Request, provider_id: int):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    form = _parse_form(await request.body())
    _verify_csrf(request, form.get("csrf", ""))
    db = SessionLocal()
    try:
        provider = db.query(_ProviderModel).filter(_ProviderModel.id == provider_id).with_for_update().first()
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        provider.is_active = not provider.is_active
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/providers?notice=Provider+status+updated", status_code=303)


@app.get("/tickets", response_class=HTMLResponse)
async def tickets_page(request: Request, status: str = "Open"):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    csrf = _csrf_token(request)
    db = SessionLocal()
    try:
        query = db.query(Ticket).order_by(Ticket.id.desc())
        if status in {"Open", "Closed"}:
            query = query.filter(Ticket.status == status)
        tickets = query.limit(100).all()
        cards = "".join(f'''<article class="card"><div class="row"><strong>Ticket #{t.id} · {escape(t.category or 'General')} · {escape(t.priority or 'Normal')}</strong><span class="badge {'on' if t.status == 'Open' else ''}">{escape(t.status)}</span></div><p>{escape(t.message[:1200])}</p><small>User database ID {t.user_id} · <a href="/users/{t.user.telegram_id if t.user else 0}">Open customer</a> · {t.created_at.strftime('%d %b %Y %H:%M') if t.created_at else '—'}</small>{f'<p><strong>Admin reply:</strong> {escape(t.admin_response)}</p>' if t.admin_response else ''}<form method="post" action="/tickets/{t.id}/close"><input type="hidden" name="csrf" value="{escape(csrf)}"><button class="{'danger' if t.status == 'Open' else ''}">{'Close ticket' if t.status == 'Open' else 'Mark open'}</button></form></article>''' for t in tickets)
    finally:
        db.close()
    body = f'''<nav class="tabs"><a href="/tickets?status=Open">Open</a><a href="/tickets?status=Closed">Closed</a><a href="/tickets?status=all">All</a></nav>{cards or '<p class="sub">No tickets found.</p>'}'''
    return HTMLResponse(_manager_page("Support tickets", body, csrf, "tickets"))


@app.post("/tickets/{ticket_id}/close")
async def ticket_toggle(request: Request, ticket_id: int):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    form = _parse_form(await request.body())
    _verify_csrf(request, form.get("csrf", ""))
    db = SessionLocal()
    try:
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).with_for_update().first()
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        ticket.status = "Closed" if ticket.status == "Open" else "Open"
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/tickets", status_code=303)


@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, q: str = ""):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    csrf, search = _csrf_token(request), q.strip()[:100]
    db = SessionLocal()
    try:
        users = []
        if search:
            query = db.query(User)
            query = query.filter(or_(User.telegram_id == int(search), User.id == int(search))) if search.isdigit() else query.filter(User.username.ilike(f"%{search.lstrip('@')}%"))
            users = query.order_by(User.id.desc()).limit(50).all()
        cards = "".join(f'''<article class="card"><div class="row"><div><strong>{escape(u.full_name)} {'@'+escape(u.username) if u.username else ''}</strong><br><small>User ID <code>{u.telegram_id}</code> · balance ${_money(u.balance):.2f} · spent ${_money(u.total_spent):.2f} · orders {u.total_orders}</small></div><span class="badge {'off' if u.is_banned else 'on'}">{'Banned' if u.is_banned else 'Active'}</span></div><div class="row"><a href="/users/{u.telegram_id}">View details and orders</a><form method="post" action="/users/{u.telegram_id}/ban"><input type="hidden" name="csrf" value="{escape(csrf)}"><button class="{'danger' if not u.is_banned else 'primary'}">{'Ban user' if not u.is_banned else 'Unban user'}</button></form></div></article>''' for u in users)
    finally:
        db.close()
    body = f'''<section class="panel"><h2>Find a customer</h2><form class="search" method="get"><input name="q" value="{escape(search)}" placeholder="Telegram user ID, database ID, or username" required><button>Search</button></form><small>Search by exact Telegram ID or partial username.</small></section>{cards or ('<p class="sub">Enter a search to find users.</p>' if not search else '<p class="sub">No matching users.</p>')}'''
    return HTMLResponse(_manager_page("Customer lookup", body, csrf, "users"))


@app.get("/users/{telegram_id}", response_class=HTMLResponse)
async def user_detail(request: Request, telegram_id: int):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    csrf = _csrf_token(request)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if not user:
            return HTMLResponse(_manager_page("Customer not found", '<p class="sub">No customer with that Telegram ID.</p><a href="/users">Back to search</a>', csrf, "users"), status_code=404)
        orders = db.query(Order).filter(Order.telegram_id == telegram_id).order_by(Order.created_at.desc()).limit(100).all()
        order_rows = "".join(f'<tr><td><a href="/?status=all&q={o.id}">#{o.id}</a></td><td>{escape(o.product_name)}</td><td>{escape(o.status)}</td><td>${_money(o.amount):.2f}</td><td>{o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "—"}</td></tr>' for o in orders)
        body = f'''<section class="panel"><h2>{escape(user.full_name)} {'@'+escape(user.username) if user.username else ''}</h2><div class="grid"><p>Telegram ID<br><code>{user.telegram_id}</code></p><p>Balance<br><strong>${_money(user.balance):.2f}</strong></p><p>Total spent<br><strong>${_money(user.total_spent):.2f}</strong></p><p>Orders<br><strong>{user.total_orders}</strong></p><p>Referrals<br><strong>{user.total_referrals}</strong></p></div><form method="post" action="/users/{user.telegram_id}/ban"><input type="hidden" name="csrf" value="{escape(csrf)}"><button class="{'primary' if user.is_banned else 'danger'}">{'Unban customer' if user.is_banned else 'Ban customer'}</button></form></section><h2>Order history ({len(orders)} recent)</h2><div class="panel"><table class="table"><thead><tr><th>Order</th><th>Product</th><th>Status</th><th>Total</th><th>Created</th></tr></thead><tbody>{order_rows or '<tr><td colspan="5">No orders found.</td></tr>'}</tbody></table></div>'''
    finally:
        db.close()
    return HTMLResponse(_manager_page("Customer details", body, csrf, "users"))


@app.post("/users/{telegram_id}/ban")
async def user_ban_toggle(request: Request, telegram_id: int):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    form = _parse_form(await request.body())
    _verify_csrf(request, form.get("csrf", ""))
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == telegram_id).with_for_update().first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user.is_banned = not user.is_banned
        db.commit()
    finally:
        db.close()
    return RedirectResponse(f"/users/{telegram_id}", status_code=303)


@app.get("/system", response_class=HTMLResponse)
async def system_page(request: Request):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    csrf = _csrf_token(request)
    db = SessionLocal()
    try:
        setting = db.query(MaintenanceSetting).filter(MaintenanceSetting.id == 1).first()
        enabled = bool(setting and setting.enabled)
    finally:
        db.close()
    state = "ON — customers see the maintenance notice" if enabled else "OFF — normal bot activity"
    body = f'''<section class="panel"><h2>Bot maintenance mode</h2><p>Current status: <strong class="{'off' if enabled else 'on'}">{state}</strong></p><p class="sub">Changes the shared maintenance setting read by the Telegram bot; it does not stop the bot process.</p><form method="post" action="/system/maintenance"><input type="hidden" name="csrf" value="{escape(csrf)}"><input type="hidden" name="enabled" value="{0 if enabled else 1}"><button class="{'primary' if enabled else 'danger'}">{'Turn maintenance OFF' if enabled else 'Turn maintenance ON'}</button></form></section><section class="panel"><h2>Manager service</h2><p>Independent web process; Telegram polling is not started here.</p><p>Deposit controls are intentionally excluded.</p></section>'''
    return HTMLResponse(_manager_page("System controls", body, csrf, "system"))


@app.post("/system/maintenance")
async def maintenance_toggle(request: Request):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    form = _parse_form(await request.body())
    _verify_csrf(request, form.get("csrf", ""))
    enabled = form.get("enabled") == "1"
    db = SessionLocal()
    try:
        setting = db.query(MaintenanceSetting).filter(MaintenanceSetting.id == 1).with_for_update().first()
        if setting is None:
            db.add(MaintenanceSetting(id=1, enabled=enabled))
        else:
            setting.enabled = enabled
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Manager maintenance toggle failed")
        raise HTTPException(status_code=500, detail="Could not update maintenance mode")
    finally:
        db.close()
    return RedirectResponse("/system", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, status: str = "pending", page: int = 1, q: str = ""):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    page = max(1, page)
    page_size = 50
    status = status if status in {"pending", "completed", "refunded", "deleted", "all"} else "pending"
    search = q.strip()[:100]
    csrf = _csrf_token(request)
    db = SessionLocal()
    try:
        pending_count = db.query(func.count(Order.id)).filter(Order.status.in_(GENERAL_PENDING_STATUSES)).scalar() or 0
        completed_count = db.query(func.count(Order.id)).filter(Order.status == "completed").scalar() or 0
        query = db.query(Order, User.username, User.full_name).outerjoin(
            User, User.telegram_id == Order.telegram_id
        )
        query = _order_status_filter(query, status)
        if search:
            if search.isdigit():
                numeric = int(search)
                query = query.filter(or_(Order.id == numeric, Order.telegram_id == numeric))
            else:
                query = query.filter(Order.product_name.ilike(f"%{search}%"))
        total = query.count()
        rows = query.order_by(Order.created_at.desc(), Order.id.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
        order_ids = [row[0].id for row in rows]
        api_order_ids = set()
        outbox_by_order = {}
        if order_ids:
            api_order_ids = {
                row[0] for row in db.query(ApiOrder.order_id).filter(ApiOrder.order_id.in_(order_ids)).all()
            }
            outbox_by_order = {
                item.order_id: item for item in db.query(ManagerDeliveryOutbox)
                .filter(ManagerDeliveryOutbox.order_id.in_(order_ids)).all()
            }
        cards = "".join(
            _render_order_card(order, username, full_name, order.id in api_order_ids,
                               outbox_by_order.get(order.id), csrf)
            for order, username, full_name in rows
        )
    finally:
        db.close()

    page_count = max(1, (total + page_size - 1) // page_size)
    prev_link = f"/?status={quote(status)}&page={page - 1}&q={quote(search)}" if page > 1 else "#"
    next_link = f"/?status={quote(status)}&page={page + 1}&q={quote(search)}" if page < page_count else "#"
    notice = request.query_params.get("notice", "")
    notice_html = '<div class="notice success">Delivery saved. Telegram notification is queued.</div>' if notice == "delivered" else ""
    error = request.query_params.get("error", "")
    if error:
        notice_html += f'<div class="notice error">{escape(error)}</div>'
    tabs = "".join(
        f'<a class="{"active" if status == key else ""}" href="/?status={key}">{label}</a>'
        for key, label in (("pending", "Needs action"), ("completed", "Delivered"),
                           ("all", "All orders"), ("refunded", "Refunded"))
    )
    empty = '<div class="empty">No orders match this view.</div>' if not cards else cards
    html = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rain Deals Order Manager</title><style>
:root{{--page:#f5f8f3;--ink:#18231d;--muted:#75847a;--line:#e5ebe3;--panel:#fff;--lime:#c8ff9c;--forest:#183127}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;color:var(--ink);background:radial-gradient(ellipse at 8% 0%,#e7f8da 0,transparent 27%),radial-gradient(ellipse at 100% 60%,#e6f4ec 0,transparent 28%),var(--page);font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}}
a{{color:#32654a;text-decoration:none}}a:hover{{color:#17251c}}.wrap{{width:min(1320px,100% - 40px);margin:auto;padding:26px 0 70px}}header{{position:sticky;top:12px;z-index:5;display:flex;justify-content:space-between;align-items:center;gap:16px;padding:14px 18px;background:#ffffffd9;border:1px solid #e7ece5;border-radius:20px;box-shadow:0 12px 38px #263d2c10;backdrop-filter:blur(18px)}}h1{{font-size:20px;letter-spacing:-.04em;margin:0}}.sub{{color:var(--muted);margin:4px 0 0}}header .sub{{font-size:12px}}.logout button,.secondary{{background:var(--forest);color:#e0ffca;padding:10px 14px;border:0;border-radius:12px;box-shadow:0 4px 0 #0c1a12}}
.stats{{display:grid;grid-template-columns:repeat(2,minmax(180px,1fr));gap:15px;margin:20px 0}}.stat,.order-card{{background:linear-gradient(145deg,#fff,#fbfdf9);border:1px solid #e4ebe2;border-radius:19px;box-shadow:0 10px 28px #253b2b0a,0 2px 5px #253b2b07}}
.stat{{padding:21px;position:relative;overflow:hidden}}.stat:after{{content:"";position:absolute;width:110px;height:110px;border-radius:50%;background:radial-gradient(circle at 30% 25%,#efffde,#c8f2a5 40%,#a8d6bb);right:-30px;top:-37px;box-shadow:inset -10px -12px 25px #54846b22}}.stat strong{{display:block;font-size:34px;letter-spacing:-.05em}}.stat span,small,time{{color:var(--muted)}}.tabs{{display:flex;gap:8px;overflow:auto;padding:5px 0 15px}}.tabs a{{white-space:nowrap;padding:10px 15px;border-radius:12px;background:#ffffffa8;border:1px solid #e7ece5;color:#536158}}.tabs a.active{{background:var(--forest);border-color:var(--forest);color:#d8ffb9;box-shadow:0 5px 0 #0e1c15}}
.search{{display:flex;gap:9px;margin:10px 0 16px}}.search input{{flex:1}}input,textarea{{background:#fbfcfa;border:1px solid #dfe7df;border-radius:12px;color:var(--ink);padding:12px 14px;font:inherit;outline:none}}input:focus,textarea:focus{{border-color:#82b96c;box-shadow:0 0 0 4px #b8eb9438}}.search button,.deliver-button{{border:0;border-radius:12px;background:var(--forest);color:#e0ffca;padding:11px 16px;font-weight:700;box-shadow:0 4px 0 #0c1a12;cursor:pointer}}
.order-card{{padding:19px;margin:13px 0;transition:transform .22s,box-shadow .22s}}.order-card:hover{{transform:translateY(-3px);box-shadow:0 18px 38px #253b2b14}}.card-head{{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:14px}}.order-number{{font-weight:800;font-size:17px;margin-right:10px}}.badge{{padding:5px 10px;border-radius:99px;font-size:12px;background:#fff1d6;color:#886119;font-weight:700}}.badge.done{{background:#e6f7e9;color:#28774e}}.badge.muted{{background:#edf0ec;color:#68736b}}
.order-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:13px}}.order-grid small,.order-grid strong,.order-grid code{{display:block}}.order-grid strong{{margin:4px 0;overflow-wrap:anywhere}}.order-grid code{{font-size:12px;color:var(--muted)}}.deliver{{margin-top:15px;border-top:1px solid var(--line);padding-top:13px}}summary{{cursor:pointer;color:#32654a;font-weight:750}}
.delivery-form label{{display:block;margin:12px 0}}.delivery-form textarea{{display:block;width:100%;min-height:115px;resize:vertical;margin-top:6px}}.delivery-form input{{display:block;width:100%;margin-top:6px}}.delivery-form small{{color:var(--muted)}}.deliver-button{{display:block;margin-top:12px}}.notice{{padding:13px 16px;border-radius:14px;margin:12px 0;background:#edf3ea}}.success{{background:#e8f7df;color:#2e6340}}.error{{background:#fff0ed;color:#963d34}}.empty{{text-align:center;padding:50px 10px;color:var(--muted)}}.pager{{display:flex;justify-content:space-between;padding:18px 0}}.pager .disabled{{opacity:.4;pointer-events:none}}
@media(max-width:650px){{.wrap{{width:calc(100% - 24px);padding:13px 0 42px}}header{{top:6px;padding:12px 13px;border-radius:16px}}h1{{font-size:18px}}.stats{{grid-template-columns:1fr 1fr;gap:9px}}.stat{{padding:15px}}.stat strong{{font-size:27px}}.stat:after{{width:70px;height:70px;right:-22px;top:-25px}}.card-head{{align-items:flex-start;flex-direction:column}}.search{{flex-wrap:wrap}}.search input{{min-width:100%}}.order-card{{padding:15px}}}}
</style></head><body><main class="wrap"><header><div><h1>✳ Rain Deals <span style="font-weight:450;color:#708078">/ Control room</span></h1><p class="sub">Order operations · connected to the shared store database</p></div>
<form class="logout" method="post" action="/logout"><input type="hidden" name="csrf" value="{escape(csrf)}"><button>Sign out</button></form></header>
<section class="stats"><div class="stat"><strong>{pending_count}</strong><span>Orders needing action</span></div><div class="stat"><strong>{completed_count}</strong><span>Delivered orders</span></div></section>
{notice_html}{_management_nav("orders")}<nav class="tabs">{tabs}</nav><form class="search" method="get" action="/"><input type="hidden" name="status" value="{escape(status)}">
<input name="q" value="{escape(search)}" placeholder="Search order ID, Telegram ID, or product"><button>Search</button></form>
<p class="sub">Showing {len(rows)} of {total} · Page {page} of {page_count}</p>{empty}
<nav class="pager"><a class="{'disabled' if page <= 1 else ''}" href="{prev_link}">← Previous</a><a class="{'disabled' if page >= page_count else ''}" href="{next_link}">Next →</a></nav>
</main><script>setTimeout(()=>{{if(!['INPUT','TEXTAREA'].includes(document.activeElement.tagName))location.reload()}},15000)</script></body></html>"""
    return HTMLResponse(html)


def _complete_order(order_id: int, delivery_text: str, customer_telegram_id: int | None) -> None:
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).with_for_update().first()
        if not order:
            raise ValueError("Order not found.")
        deliverable = order.status in ("pending_manual", "preorder") or (
            order.status == "processing" and order.delivery_type in ("manual", "hybrid")
        )
        if order.refunded or not deliverable:
            raise ValueError("This order is no longer waiting for manual delivery.")
        is_api_order = db.query(ApiOrder.id).filter(ApiOrder.order_id == order.id).first() is not None
        was_preorder = bool(order.is_preorder or order.status == "preorder")

        if is_api_order:
            destination_id = order.delivery_telegram_id or customer_telegram_id
            if not destination_id:
                raise ValueError("Enter the customer's Telegram ID for this API order before delivering it.")
            if not config.DELIVERY_BOT_TOKEN:
                raise ValueError("DELIVERY_BOT_TOKEN is required to notify API-order customers.")
            bot_kind = "delivery"
        else:
            destination_id = customer_telegram_id or order.delivery_telegram_id or order.telegram_id
            bot_kind = "main"

        if was_preorder:
            buyer = db.query(User).filter(User.telegram_id == order.telegram_id).with_for_update().first()
            if buyer and buyer.referred_by:
                referrer = db.query(User).filter(
                    User.telegram_id == buyer.referred_by
                ).with_for_update().first()
                if referrer:
                    commission = _money(_money(order.amount) * REFERRAL_COMMISSION_RATE)
                    if commission > 0:
                        referrer.referral_earnings = _money(referrer.referral_earnings) + commission
                        if REFERRAL_CREDIT_TO_BALANCE:
                            referrer.balance = _money(referrer.balance) + commission

        order.delivered_account = delivery_text
        order.status = "completed"
        order.is_preorder = False
        db.add(ManagerDeliveryOutbox(
            order_id=order.id,
            destination_id=destination_id,
            bot_kind=bot_kind,
            status="queued",
            attempts=0,
            available_at=_now_naive_utc(),
        ))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("This order already has a delivery notification queued.") from exc
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.post("/orders/{order_id}/deliver")
async def deliver_order(request: Request, order_id: int):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    form = _parse_form(await request.body())
    _verify_csrf(request, form.get("csrf", ""))
    delivery_text = form.get("delivery_text", "").strip()
    if not delivery_text:
        raise HTTPException(status_code=400, detail="Enter the delivery details.")
    if len(delivery_text) > MAX_DELIVERY_TEXT_LENGTH:
        raise HTTPException(status_code=400, detail=f"Delivery text must be at most {MAX_DELIVERY_TEXT_LENGTH} characters.")
    customer_id_text = form.get("customer_telegram_id", "").strip()
    try:
        customer_id = int(customer_id_text) if customer_id_text else None
        if customer_id is not None and customer_id <= 0:
            raise ValueError
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Customer Telegram ID must be a positive integer.") from exc
    try:
        await asyncio.to_thread(_complete_order, order_id, delivery_text, customer_id)
    except ValueError as exc:
        return RedirectResponse(f"/?status=pending&error={quote(str(exc))}", status_code=303)
    return RedirectResponse("/?status=completed&notice=delivered", status_code=303)


@app.post("/notifications/{outbox_id}/retry")
async def retry_notification(request: Request, outbox_id: int):
    auth_response = _require_manager(request)
    if auth_response:
        return auth_response
    form = _parse_form(await request.body())
    _verify_csrf(request, form.get("csrf", ""))
    db = SessionLocal()
    try:
        item = db.query(ManagerDeliveryOutbox).filter(
            ManagerDeliveryOutbox.id == outbox_id
        ).with_for_update().first()
        if not item or item.status != "failed":
            raise HTTPException(status_code=409, detail="This notification is not in a retryable state.")
        item.status = "queued"
        item.attempts = 0
        item.available_at = _now_naive_utc()
        item.claimed_at = None
        item.last_error = None
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/?status=completed", status_code=303)


def _claim_outbox_item() -> dict | None:
    now = _now_naive_utc()
    expired_claim = now - timedelta(minutes=5)
    db = SessionLocal()
    try:
        item = db.query(ManagerDeliveryOutbox).filter(or_(
            and_(ManagerDeliveryOutbox.status == "queued", ManagerDeliveryOutbox.available_at <= now),
            and_(ManagerDeliveryOutbox.status == "sending", ManagerDeliveryOutbox.claimed_at <= expired_claim),
        )).order_by(ManagerDeliveryOutbox.id.asc()).with_for_update().first()
        if not item:
            return None
        item.status = "sending"
        item.claimed_at = now
        item.attempts += 1
        result = {
            "id": item.id,
            "order_id": item.order_id,
            "destination_id": item.destination_id,
            "bot_kind": item.bot_kind,
            "attempts": item.attempts,
        }
        db.commit()
        return result
    finally:
        db.close()


def _delivery_message(order_id: int) -> str:
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order or order.status != "completed" or not order.delivered_account:
            raise ValueError("Completed order delivery details were not found.")
        return (
            "✅ <b>YOUR ORDER IS DELIVERED</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"🧾 <b>Order:</b> <code>#{order.id}</code>\n"
            f"📦 <b>Product:</b> {escape(str(order.product_name))}\n"
            f"🔢 <b>Quantity:</b> {order.quantity or 1}\n"
            f"💰 <b>Total:</b> ${_money(order.amount):.2f}\n\n"
            "🔑 <b>Your delivery:</b>\n"
            f"<pre>{escape(str(order.delivered_account))}</pre>\n\n"
            "Thank you for your order!"
        )
    finally:
        db.close()


def _finish_outbox_item(item_id: int, error: str | None, attempts: int) -> None:
    db = SessionLocal()
    try:
        item = db.query(ManagerDeliveryOutbox).filter(
            ManagerDeliveryOutbox.id == item_id
        ).with_for_update().first()
        if not item:
            return
        item.claimed_at = None
        if error is None:
            item.status = "sent"
            item.sent_at = _now_naive_utc()
            item.last_error = None
        else:
            item.last_error = error[:1000]
            if attempts >= OUTBOX_MAX_ATTEMPTS:
                item.status = "failed"
            else:
                item.status = "queued"
                item.available_at = _now_naive_utc() + timedelta(seconds=min(300, 5 * (2 ** (attempts - 1))))
        db.commit()
    finally:
        db.close()


async def _notification_worker() -> None:
    while True:
        try:
            item = await asyncio.to_thread(_claim_outbox_item)
            if not item:
                await asyncio.sleep(2)
                continue
            try:
                bot = app.state.delivery_bot if item["bot_kind"] == "delivery" else app.state.main_bot
                await bot.send_message(
                    chat_id=item["destination_id"],
                    text=await asyncio.to_thread(_delivery_message, item["order_id"]),
                    parse_mode="HTML",
                )
                await asyncio.to_thread(_finish_outbox_item, item["id"], None, item["attempts"])
                logger.info("Delivery notification sent for order #%s", item["order_id"])
            except Exception as exc:
                logger.exception("Delivery notification failed for order #%s", item["order_id"])
                await asyncio.to_thread(_finish_outbox_item, item["id"], str(exc), item["attempts"])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Delivery outbox worker error")
            await asyncio.sleep(3)


@app.middleware("http")
async def secure_response_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response
