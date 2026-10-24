"""Explicit endpoint configuration; preview never needs credentials."""
from argparse import Namespace
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
import ipaddress
import re

from pydantic import SecretStr

from .contracts import EndpointPolicy, PriceTable, Settings


_PATH_SEGMENT = re.compile(r"[A-Za-z0-9._~-]+\Z")


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
    # urlsplit silently strips some ASCII whitespace; reject it before parsing
    # so a spelling cannot be accepted under a different normalized path.
    if any(character.isspace() for character in settings.base_url):
        raise ValueError("Endpoint URL must not contain whitespace")
    try:
        url = urlsplit(settings.base_url)
    except ValueError as exc:
        raise ValueError("Invalid endpoint URL") from exc
    try:
        port = url.port
    except ValueError as exc:
        raise ValueError("Invalid endpoint port") from exc
    if (not url.hostname or "@" in url.netloc or url.query or url.fragment
            or url.scheme not in ("http", "https")):
        raise ValueError("Endpoint must be an HTTP(S) URL without credentials, query or fragment")
    path = _normalized_path(url.path)
    try:
        loopback = ipaddress.ip_address(url.hostname).is_loopback
    except ValueError:
        loopback = url.hostname.lower() == "localhost"
    if url.scheme == "http" and not (loopback and settings.allow_loopback_http):
        raise ValueError("HTTP requires explicit --allow-loopback-http and a loopback host")
    if not loopback and not settings.allow_hosted_upload:
        raise ValueError("Hosted upload requires --allow-hosted-upload")
    # Retain the pre-path origin spelling for legacy bare-origin run keys.  The
    # path is the only portion normalized, after being validated as canonical.
    base_url = settings.base_url.rstrip("/") if not path else f"{url.scheme}://{url.netloc}{path}"
    return EndpointPolicy(base_url=base_url, loopback=loopback,
                          upload_permitted=loopback or settings.allow_hosted_upload)


def _normalized_path(path: str) -> str:
    """Accept only canonical, slash-delimited unreserved path segments."""
    if path in ("", "/"):
        return ""
    if path.endswith("/"):
        path = path[:-1]
    if not path.startswith("/") or not path:
        raise ValueError("Endpoint path must use canonical slash-separated segments")
    segments = path[1:].split("/")
    if any(segment in ("", ".", "..") or not _PATH_SEGMENT.fullmatch(segment)
           for segment in segments):
        raise ValueError("Endpoint path must contain only unreserved, non-dot segments")
    return path
