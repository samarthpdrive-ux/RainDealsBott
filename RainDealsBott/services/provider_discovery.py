# services/provider_discovery.py

import asyncio
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import aiohttp

logger = logging.getLogger(__name__)


class ProviderDiscoveryError(Exception):
    """Exception raised during provider API discovery operations."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = str(message)
        self.status_code = status_code
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


def _sanitize_text(text: str, api_key: Optional[str] = None) -> str:
    """Utility to scrub sensitive keys/tokens from strings or logs."""
    if not text:
        return ""
    if api_key and len(api_key) > 3:
        return text.replace(api_key, "***REDACTED***")
    return text


class ProviderDiscovery:
    """
    Automated and safe API structure discovery for reseller providers.
    Performs controlled HTTP inspection against explicit administrator-supplied endpoints.
    """

    # Limited set of common API documentation endpoints
    DOC_CANDIDATES = [
        "/openapi.json",
        "/swagger.json",
        "/api-docs",
    ]

    # Limited set of common endpoint patterns for manual fallback inspection
    PRODUCT_ENDPOINTS = [
        "/api/v1/products",
        "/api/products",
        "/api/services",
        "/api/v1/services",
    ]

    BALANCE_ENDPOINTS = [
        "/api/v1/me",
        "/api/v1/balance",
        "/api/balance",
        "/api/me",
    ]

    ORDER_ENDPOINTS = [
        "/api/v1/order",
        "/api/order",
    ]

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout: int = 10,
    ):
        if not base_url:
            raise ProviderDiscoveryError("Base URL is required.")

        parsed = urlparse(base_url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ProviderDiscoveryError("Invalid URL format. Must start with http:// or https://")

        self.base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        self.api_key = api_key.strip() if api_key else None
        self.timeout_sec = timeout
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def _get_auth_headers(self, auth_type: str = "header") -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if not self.api_key:
            return headers

        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif auth_type == "header":
            headers["X-API-Key"] = self.api_key
        return headers

    async def _safe_request(
        self,
        method: str,
        endpoint: str,
        auth_type: str = "header",
        params: Optional[Dict[str, Any]] = None,
    ) -> tuple[Optional[int], Any]:
        """Executes a safe HTTP request, swallowing network errors gracefully."""
        url = f"{self.base_url}{endpoint}"

        req_params = dict(params or {})
        if auth_type == "query" and self.api_key:
            req_params["key"] = self.api_key

        try:
            session = await self._get_session()
            async with session.request(
                method,
                url,
                headers=self._get_auth_headers(auth_type),
                params=req_params if req_params else None,
                allow_redirects=False,
            ) as response:
                status = response.status
                if status == 200:
                    try:
                        json_data = await response.json()
                        return status, json_data
                    except Exception:
                        return status, await response.text()
                return status, None
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.debug("Request to %s failed: %s", endpoint, _sanitize_text(str(e), self.api_key))
            return None, None
        except Exception as e:
            logger.debug("Unexpected error requesting %s: %s", endpoint, _sanitize_text(str(e), self.api_key))
            return None, None

    async def test_connection(self) -> Dict[str, Any]:
        """Tests general connectivity and authentication against base URL or status endpoints."""
        for endpoint in ["/api/v1/me", "/api/me", ""]:
            for auth_style in ["header", "bearer", "query"]:
                status, response = await self._safe_request("GET", endpoint, auth_type=auth_style)
                if status == 200:
                    return {
                        "success": True,
                        "status": status,
                        "message": "Connection successful",
                        "auth_type": auth_style,
                    }
                elif status in (401, 403):
                    return {
                        "success": False,
                        "status": status,
                        "message": "Authentication failed (HTTP 401/403)",
                        "auth_type": auth_style,
                    }

        return {
            "success": False,
            "status": 0,
            "message": "Unable to establish connection or verify authentication.",
        }

    async def _inspect_openapi_docs(self) -> Optional[Dict[str, Any]]:
        """Inspects predictable OpenAPI/Swagger documentation endpoints if available."""
        for doc_path in self.DOC_CANDIDATES:
            status, data = await self._safe_request("GET", doc_path)
            if status == 200 and isinstance(data, dict):
                paths = data.get("paths", {})
                if paths and isinstance(paths, dict):
                    return paths
        return None

    async def discover_products(self) -> Dict[str, Any]:
        """Attempts to discover products catalog endpoint and field mappings."""
        paths = await self._inspect_openapi_docs()
        if paths:
            for path, methods in paths.items():
                if isinstance(methods, dict) and "get" in methods:
                    if any(kw in path.lower() for kw in ["product", "service", "catalog", "item"]):
                        return {
                            "found": True,
                            "endpoint": path,
                            "method": "GET",
                            "mapping": {
                                "service_id": "service_id",
                                "name": "name",
                                "price": "price",
                                "stock": "stock",
                            },
                        }

        # Fallback direct endpoint testing
        for endpoint in self.PRODUCT_ENDPOINTS:
            for auth_type in ["header", "bearer", "query"]:
                status, data = await self._safe_request("GET", endpoint, auth_type=auth_type)
                if status == 200 and data is not None:
                    raw_items = []
                    if isinstance(data, list):
                        raw_items = data
                    elif isinstance(data, dict):
                        for k in ["services", "products", "data", "items"]:
                            if k in data and isinstance(data[k], list):
                                raw_items = data[k]
                                break

                    if raw_items and isinstance(raw_items[0], dict):
                        item = raw_items[0]
                        mapping = {}

                        # Map service_id
                        for k in ["service_id", "id", "service", "code"]:
                            if k in item:
                                mapping["service_id"] = k
                                break

                        # Map name
                        for k in ["name", "title", "product_name"]:
                            if k in item:
                                mapping["name"] = k
                                break

                        # Map price
                        for k in ["price", "rate", "cost"]:
                            if k in item:
                                mapping["price"] = k
                                break

                        # Map stock
                        for k in ["stock", "quantity", "available"]:
                            if k in item:
                                mapping["stock"] = k
                                break

                        return {
                            "found": True,
                            "endpoint": endpoint,
                            "method": "GET",
                            "auth_type": auth_type,
                            "mapping": mapping,
                        }

        return {"found": False, "endpoint": None, "method": None, "mapping": {}}

    async def discover_balance(self) -> Dict[str, Any]:
        """Attempts to discover user/account balance endpoint and key mappings."""
        paths = await self._inspect_openapi_docs()
        if paths:
            for path, methods in paths.items():
                if isinstance(methods, dict) and "get" in methods:
                    if any(kw in path.lower() for kw in ["balance", "me", "user", "funds"]):
                        return {
                            "found": True,
                            "endpoint": path,
                            "method": "GET",
                            "mapping": {"balance": "balance"},
                        }

        # Fallback direct endpoint testing
        for endpoint in self.BALANCE_ENDPOINTS:
            for auth_type in ["header", "bearer", "query"]:
                status, data = await self._safe_request("GET", endpoint, auth_type=auth_type)
                if status == 200 and isinstance(data, dict):
                    balance_key = None
                    for k in ["balance", "funds", "credits", "user_balance"]:
                        if k in data:
                            balance_key = k
                            break

                    if not balance_key and "user" in data and isinstance(data["user"], dict):
                        for k in ["balance", "funds", "credits"]:
                            if k in data["user"]:
                                balance_key = f"user.{k}"
                                break

                    if balance_key:
                        return {
                            "found": True,
                            "endpoint": endpoint,
                            "method": "GET",
                            "auth_type": auth_type,
                            "mapping": {"balance": balance_key},
                        }

        return {"found": False, "endpoint": None, "method": None, "mapping": {}}

    async def discover_order(self) -> Dict[str, Any]:
        """
        Attempts to discover purchase/order API structure by inspecting documentation
        or standard metadata. NEVER executes a POST or places an actual order.
        """
        paths = await self._inspect_openapi_docs()
        if paths:
            for path, methods in paths.items():
                if isinstance(methods, dict) and "post" in methods:
                    if any(kw in path.lower() for kw in ["order", "buy", "purchase"]):
                        params = {"service_id": "service_id", "quantity": "quantity"}
                        post_spec = methods.get("post", {})
                        if isinstance(post_spec, dict):
                            req_body = post_spec.get("requestBody", {})
                            if isinstance(req_body, dict):
                                params["schema_detected"] = True

                        return {
                            "found": True,
                            "endpoint": path,
                            "method": "POST",
                            "parameters": params,
                        }

        # Check standard endpoint conventions without calling POST
        for endpoint in self.ORDER_ENDPOINTS:
            return {
                "found": True,
                "endpoint": endpoint,
                "method": "POST",
                "parameters": {
                    "service_id": "service_id",
                    "quantity": "quantity",
                },
            }

        return {"found": False, "endpoint": None, "method": None, "parameters": {}}

    async def discover(self) -> Dict[str, Any]:
        """
        Main entry point. Executes full discovery workflow across connectivity,
        products, balance, and order APIs.
        """
        try:
            conn_result = await self.test_connection()
            products_result = await self.discover_products()
            balance_result = await self.discover_balance()
            order_result = await self.discover_order()

            success = conn_result.get("success", False) or products_result.get("found", False)
            auth_type = conn_result.get("auth_type") or products_result.get("auth_type") or "header"

            api_type = "generic"
            if "/api/v1/" in (products_result.get("endpoint") or ""):
                api_type = "excalibur"

            return {
                "success": success,
                "base_url": self.base_url,
                "api_type": api_type,
                "auth_type": auth_type,
                "endpoints": {
                    "products": products_result.get("endpoint"),
                    "balance": balance_result.get("endpoint"),
                    "order": order_result.get("endpoint"),
                },
                "mapping": {
                    "products": products_result.get("mapping", {}),
                    "balance": balance_result.get("mapping", {}),
                    "order_params": order_result.get("parameters", {}),
                },
                "message": "Discovery completed successfully." if success else "Discovery failed or incomplete.",
            }
        except Exception as e:
            logger.exception("Provider discovery failed")
            return {
                "success": False,
                "base_url": self.base_url,
                "api_type": "generic",
                "auth_type": "header",
                "endpoints": {"products": None, "balance": None, "order": None},
                "mapping": {},
                "message": f"Discovery error: {_sanitize_text(str(e), self.api_key)}",
            }
        finally:
            await self.close()