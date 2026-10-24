"""Explicit endpoint configuration; preview never needs credentials."""
from argparse import Namespace
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
import ipaddress

from pydantic import SecretStr

from .contracts import EndpointPolicy, PriceTable, Settings


def load_settings(args: Namespace, env: Mapping[str, str]) -> Settings:
    get = lambda name, default=None: getattr(args, name, default)
    preview = get("command") == "preview"
    base = "" if preview else (get("base_url") or env.get("LLM_BASE_URL", ""))
    model = "" if preview else (get("model") or env.get("LLM_MODEL", ""))
    if not preview and (not base or not model):
        raise ValueError("Live review requires LLM_BASE_URL and LLM_MODEL")
    key = None if preview else env.get("LLM_API_KEY")
    rates = [get("input_per_million"), get("output_per_million"),
             get("price_currency"), get("price_as_of")]
    if any(value is not None for value in rates) and not all(value is not None for value in rates):
        raise ValueError("Prices require both rates, currency and as-of date")
    price = None
    if all(value is not None for value in rates):
        from datetime import date
        date.fromisoformat(rates[3])
        if not rates[2].isalpha() or not 3 <= len(rates[2]) <= 4:
            raise ValueError("Invalid price currency")
        try:
            price = PriceTable(input_per_million=Decimal(rates[0]),
                               output_per_million=Decimal(rates[1]),
                               currency=rates[2].upper(), as_of=rates[3])
        except InvalidOperation as exc:
            raise ValueError("Invalid price rate") from exc
        if (not price.input_per_million.is_finite() or not price.output_per_million.is_finite()
                or price.input_per_million < 0 or price.output_per_million < 0):
            raise ValueError("Rates cannot be negative")
    return Settings(base_url=base, model=model, api_key=SecretStr(key) if key else None,
                    schema_mode=get("schema_mode", "text"),
                    max_output_tokens=get("max_output_tokens", 1500),
                    max_output_parameter=get("max_output_parameter", "max_tokens"),
                    max_tokens_budget=get("max_tokens_budget"),
                    allow_hosted_upload=get("allow_hosted_upload", False),
                    allow_loopback_http=get("allow_loopback_http", False),
                    retry_uncertain=get("retry_uncertain", False),
                    account_label=env.get("REVIEWDESK_ACCOUNT_LABEL", ""),
                    exclude=get("exclude", []), price_table=price)


def validate_endpoint(settings: Settings) -> EndpointPolicy:
    url = urlsplit(settings.base_url)
    try:
        port = url.port
    except ValueError as exc:
        raise ValueError("Invalid endpoint port") from exc
    if (not url.hostname or "@" in url.netloc or url.query or url.fragment
            or url.path not in ("", "/") or url.scheme not in ("http", "https")):
        raise ValueError("Endpoint must be a bare HTTPS origin without credentials, query or fragment")
    try:
        loopback = ipaddress.ip_address(url.hostname).is_loopback
    except ValueError:
        loopback = url.hostname.lower() == "localhost"
    if url.scheme == "http" and not (loopback and settings.allow_loopback_http):
        raise ValueError("HTTP requires explicit --allow-loopback-http and a loopback host")
    if not loopback and not settings.allow_hosted_upload:
        raise ValueError("Hosted upload requires --allow-hosted-upload")
    return EndpointPolicy(base_url=settings.base_url.rstrip("/"), loopback=loopback,
                          upload_permitted=loopback or settings.allow_hosted_upload)
