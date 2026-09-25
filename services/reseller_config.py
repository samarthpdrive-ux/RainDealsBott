"""
services/reseller_config.py

Multi-provider reseller configuration for the bot.

Reseller credentials and settings are loaded from environment variables.

IMPORTANT:
- Do not put API keys into Product models.
- Product stores only provider/reseller ID and service ID references.
- API keys stay securely in environment variables or provider configurations.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# ============================================================
# RESELLER CONFIGURATION DATACLASS
# ============================================================

@dataclass(frozen=True)
class ResellerConfig:
    name: str
    base_url: str
    api_key: str
    id: str = "excalibur"
    api_type: str = "excalibur"
    auth_type: str = "header"
    auth_header_name: str = "X-API-Key"
    auth_query_param: str = "key"
    endpoints: dict[str, str] = field(default_factory=dict)
    response_mappings: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True

    def __repr__(self) -> str:
        """Safe representation hiding sensitive API key."""
        redacted_key = "***REDACTED***" if self.api_key else "Not Set"
        return (
            f"ResellerConfig(id={self.id!r}, name={self.name!r}, "
            f"base_url={self.base_url!r}, api_key={redacted_key!r}, "
            f"api_type={self.api_type!r}, is_active={self.is_active})"
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Allow dict-like .get() attribute access for backwards compatibility."""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """Allow dict-like subscript indexing for backwards compatibility."""
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary representation with redacted credentials."""
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "api_key": "***REDACTED***",
            "api_type": self.api_type,
            "auth_type": self.auth_type,
            "auth_header_name": self.auth_header_name,
            "auth_query_param": self.auth_query_param,
            "endpoints": self.endpoints,
            "response_mappings": self.response_mappings,
            "is_active": self.is_active,
        }


# ============================================================
# DYNAMIC ENVIRONMENT LOADER
# ============================================================

def _load_resellers_from_env() -> dict[str, ResellerConfig]:
    """
    Load default Excalibur provider and any dynamically configured
    reseller providers from environment variables.
    """
    resellers: dict[str, ResellerConfig] = {}

    # 1. Primary Default Provider: Excalibur
    excalibur_base_url = (
        os.getenv("EXCALIBUR_RESELLER_BASE_URL")
        or os.getenv("EXCALIBUR_BASE_URL")
        or os.getenv("RESELLER_BASE_URL")
        or "https://arrsnetworkzone.in"
    ).rstrip("/")

    excalibur_api_key = (
        os.getenv("EXCALIBUR_RESELLER_API_KEY")
        or os.getenv("EXCALIBUR_API_KEY")
        or os.getenv("RESELLER_API_KEY")
        or ""
    ).strip()

    excalibur_name = os.getenv("EXCALIBUR_RESELLER_NAME", "Excalibur Shop Bot")

    is_excalibur_canboso = "canboso.com" in excalibur_base_url.lower()
    excalibur_auth_type = "query" if is_excalibur_canboso else "header"
    excalibur_auth_query_param = "key" if is_excalibur_canboso else "key"

    excalibur_endpoints = {}
    if is_excalibur_canboso:
        excalibur_endpoints = {
            "products": "/api/v2/telegram-buyer/products",
            "balance": "/api/v2/telegram-buyer/balance",
            "order": "/api/v2/telegram-buyer/purchase",
        }

    resellers["excalibur"] = ResellerConfig(
        name=excalibur_name,
        base_url=excalibur_base_url,
        api_key=excalibur_api_key,
        id="excalibur",
        api_type="excalibur",
        auth_type=excalibur_auth_type,
        auth_header_name="X-API-Key",
        auth_query_param=excalibur_auth_query_param,
        endpoints=excalibur_endpoints,
        is_active=True,
    )

    # 2. Dynamic Provider Discovery from Environment Variables
    # Format: PROVIDER_<ID>_API_KEY, PROVIDER_<ID>_BASE_URL, etc.
    # or RESELLER_<ID>_API_KEY, RESELLER_<ID>_BASE_URL, etc.
    for env_key, env_value in os.environ.items():
        if not env_value or not env_value.strip():
            continue

        provider_id = None
        if env_key.startswith("PROVIDER_") and env_key.endswith("_API_KEY"):
            provider_id = env_key[len("PROVIDER_"):-len("_API_KEY")].lower()
        elif env_key.startswith("RESELLER_") and env_key.endswith("_API_KEY"):
            candidate = env_key[len("RESELLER_"):-len("_API_KEY")].lower()
            if candidate not in ("excalibur", ""):
                provider_id = candidate

        if provider_id and provider_id not in resellers:
            prefix = f"PROVIDER_{provider_id.upper()}_"
            if f"{prefix}API_KEY" not in os.environ:
                prefix = f"RESELLER_{provider_id.upper()}_"

            base_url = os.getenv(f"{prefix}BASE_URL", "").rstrip("/")
            api_key = os.getenv(f"{prefix}API_KEY", "").strip()
            name = os.getenv(f"{prefix}NAME", f"Provider {provider_id.title()}")
            api_type = os.getenv(f"{prefix}TYPE", "reseller").lower()

            is_canboso = "canboso.com" in base_url.lower()

            # Explicit auth_type wins; fallback to query if canboso, else header
            default_auth = "query" if is_canboso else "header"
            auth_type = os.getenv(f"{prefix}AUTH_TYPE", "").lower() or default_auth
            auth_header = os.getenv(f"{prefix}AUTH_HEADER", "") or os.getenv(f"{prefix}AUTH_HEADER_NAME", "X-API-Key")
            auth_query = os.getenv(f"{prefix}AUTH_QUERY_PARAM", "key")

            endpoints = {}
            if is_canboso:
                endpoints = {
                    "products": os.getenv(f"{prefix}PRODUCTS_ENDPOINT", "/api/v2/telegram-buyer/products"),
                    "balance": os.getenv(f"{prefix}BALANCE_ENDPOINT", "/api/v2/telegram-buyer/balance"),
                    "order": os.getenv(f"{prefix}ORDER_ENDPOINT", "/api/v2/telegram-buyer/purchase"),
                }
            else:
                p_prod = os.getenv(f"{prefix}PRODUCTS_ENDPOINT")
                p_bal = os.getenv(f"{prefix}BALANCE_ENDPOINT")
                p_ord = os.getenv(f"{prefix}ORDER_ENDPOINT")
                if p_prod or p_bal or p_ord:
                    if p_prod:
                        endpoints["products"] = p_prod
                    if p_bal:
                        endpoints["balance"] = p_bal
                    if p_ord:
                        endpoints["order"] = p_ord

            if base_url and api_key:
                resellers[provider_id] = ResellerConfig(
                    name=name,
                    base_url=base_url,
                    api_key=api_key,
                    id=provider_id,
                    api_type=api_type,
                    auth_type=auth_type,
                    auth_header_name=auth_header,
                    auth_query_param=auth_query,
                    endpoints=endpoints,
                    is_active=os.getenv(f"{prefix}ACTIVE", "true").lower() in ("true", "1", "yes"),
                )

    return resellers


# ============================================================
# REGISTERED RESELLERS REGISTRY
# ============================================================

RESELLERS: dict[str, ResellerConfig] = _load_resellers_from_env()


# ============================================================
# REGISTRY FUNCTIONS
# ============================================================

def register_reseller(config: ResellerConfig) -> None:
    """
    Register or update a provider configuration in the dynamic registry.
    Used for runtime/manual provider additions.
    """
    if not isinstance(config, ResellerConfig):
        raise TypeError("config must be an instance of ResellerConfig")
    RESELLERS[config.id.lower()] = config


def get_reseller(reseller_id: str) -> ResellerConfig:
    """
    Return a reseller configuration by ID.
    Raises ValueError if unknown or if API key is not set.
    """
    if not reseller_id or not isinstance(reseller_id, str):
        raise ValueError("Reseller ID must be a valid non-empty string.")

    target_id = reseller_id.strip().lower()
    reseller = RESELLERS.get(target_id)

    if reseller is None:
        raise ValueError(f"Unknown reseller: {reseller_id}")

    if not reseller.api_key:
        raise ValueError(f"API key is not configured for reseller: {reseller_id}")

    return reseller


def get_all_resellers() -> dict[str, ResellerConfig]:
    """
    Return all configured resellers as a dictionary mapping string IDs to ResellerConfig objects.
    """
    return RESELLERS.copy()
