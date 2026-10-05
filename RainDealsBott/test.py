# rate_fetcher_production.py
import json
import logging
import re
import time
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

OUTPUT_FILE = "live_rate.json"
FETCH_INTERVAL = 180  # 3 minutes

# Shared headers mimicking a real Chrome browser to avoid basic bot blocks
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}


def fetch_rate_open_er() -> float | None:
    """Fallback Source 0: Open ExchangeRate-API (Fastest open REST endpoint)."""
    try:
        res = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        if res.status_code == 200:
            rate = res.json().get("rates", {}).get("INR")
            if rate and float(rate) > 0:
                logging.info("[SUCCESS] Fetched rate from Open ExchangeRate-API")
                return float(rate)
    except Exception as e:
        logging.warning(f"[FAIL] Open ExchangeRate-API error: {e}")
    return None


def fetch_rate_revolut() -> float | None:
    """Source 1: Revolut Currency Converter Page."""
    url = "https://www.revolut.com/currency-converter/convert-usd-to-inr-exchange-rate/"
    try:
        session = requests.Session()
        res = session.get(url, headers=HTTP_HEADERS, timeout=8)
        if res.status_code == 200:
            match = re.search(r'"rate"\s*:\s*([\d\.]+)', res.text)
            if not match:
                match = re.search(r'1\s*USD\s*=\s*([\d\.]+)\s*INR', res.text, re.IGNORECASE)
            if not match:
                match = re.search(r'([\d\.]+)\s*INR', res.text)

            if match:
                rate = float(match.group(1))
                if 70.0 < rate < 120.0:  # Validation check for realistic USD/INR range
                    logging.info("[SUCCESS] Fetched rate from Revolut")
                    return rate
    except Exception as e:
        logging.warning(f"[FAIL] Revolut fetch error: {e}")
    return None


def fetch_rate_wise() -> float | None:
    """Source 2: Wise Currency Converter Page."""
    url = "https://wise.com/in/currency-converter/usd-to-inr-rate?amount=1"
    try:
        session = requests.Session()
        res = session.get(url, headers=HTTP_HEADERS, timeout=8)
        if res.status_code == 200:
            match = re.search(r'class="[^\"]*text-success[^\"]*">([\d\.]+)<', res.text)
            if not match:
                match = re.search(r'"rate"\s*:\s*([\d\.]+)', res.text)
            if not match:
                match = re.search(r'1\s*USD\s*=\s*([\d\.]+)\s*INR', res.text, re.IGNORECASE)

            if match:
                rate = float(match.group(1))
                if 70.0 < rate < 120.0:
                    logging.info("[SUCCESS] Fetched rate from Wise")
                    return rate
    except Exception as e:
        logging.warning(f"[FAIL] Wise fetch error: {e}")
    return None


def fetch_rate_xe() -> float | None:
    """Source 3: XE.com Currency Converter Page."""
    url = "https://www.xe.com/currencyconverter/convert/?Amount=1&From=USD&To=INR"
    try:
        session = requests.Session()
        res = session.get(url, headers=HTTP_HEADERS, timeout=8)
        if res.status_code == 200:
            match = re.search(r'1\.00\s*USD\s*=\s*([\d\.]+)\s*INR', res.text, re.IGNORECASE)
            if not match:
                match = re.search(r'"INR":\s*([\d\.]+)', res.text)

            if match:
                rate = float(match.group(1))
                if 70.0 < rate < 120.0:
                    logging.info("[SUCCESS] Fetched rate from XE")
                    return rate
    except Exception as e:
        logging.warning(f"[FAIL] XE fetch error: {e}")
    return None


def get_live_rate_multi_source() -> float | None:
    """Checks sources in sequence until a valid rate is found."""
    # 1. Revolut
    rate = fetch_rate_revolut()
    if rate:
        return rate

    # 2. Wise
    rate = fetch_rate_wise()
    if rate:
        return rate

    # 3. XE
    rate = fetch_rate_xe()
    if rate:
        return rate

    # 4. Open ExchangeRate API
    rate = fetch_rate_open_er()
    if rate:
        return rate

    return None


def main():
    logging.info("Starting Multi-Source USD/INR Rate Fetcher...")
    while True:
        rate = get_live_rate_multi_source()

        if rate and rate > 0:
            data = {
                "rate": rate,
                "timestamp": time.time(),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(OUTPUT_FILE, "w") as f:
                json.dump(data, f, indent=4)
            logging.info(f"Updated {OUTPUT_FILE} -> Live Rate: {rate}")
        else:
            logging.error("All rate sources failed! Keeping existing cached value.")

        logging.info(f"Sleeping for {FETCH_INTERVAL} seconds...")
        time.sleep(FETCH_INTERVAL)


if __name__ == "__main__":
    main()