from __future__ import annotations

import logging
import re
import textwrap
from functools import lru_cache

from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient

from .config import get_settings

logger = logging.getLogger("alipay")

_PEM_HEADER_RE = re.compile(r"-----BEGIN [^-]+-----")
_PEM_FOOTER_RE = re.compile(r"-----END [^-]+-----")


def _normalize_pem_key(raw_key: str, default_header: str, default_footer: str) -> str:
    """Return a PEM string with consistent header/footer and wrapped body."""
    cleaned = raw_key.strip().replace("\r", "")
    header_match = _PEM_HEADER_RE.search(cleaned)
    footer_match = _PEM_FOOTER_RE.search(cleaned)
    header = header_match.group(0) if header_match else default_header
    footer = footer_match.group(0) if footer_match else default_footer

    body = _PEM_HEADER_RE.sub("", cleaned)
    body = _PEM_FOOTER_RE.sub("", body)
    body = "".join(body.split())
    if not body:
        raise ValueError("PEM key content is empty after normalization.")
    wrapped_body = "\n".join(textwrap.wrap(body, 64)) if len(body) > 64 else body
    return "\n".join((header, wrapped_body, footer))


class AlipayConfigurationError(RuntimeError):
    """Raised when Alipay configuration is incomplete."""


@lru_cache
def get_alipay_client() -> DefaultAlipayClient:
    settings = get_settings()
    if not settings.alipay_app_id:
        raise AlipayConfigurationError("ALIPAY_APP_ID is not configured.")

    client_config = AlipayClientConfig()
    client_config.app_id = settings.alipay_app_id
    client_config.server_url = str(settings.alipay_gateway)
    client_config.sign_type = "RSA2"
    client_config.charset = "utf-8"
    try:
        private_key = settings.load_alipay_private_key()
        public_key = settings.load_alipay_public_key()
        client_config.app_private_key = _normalize_pem_key(
            private_key,
            "-----BEGIN RSA PRIVATE KEY-----",
            "-----END RSA PRIVATE KEY-----",
        )
        client_config.alipay_public_key = _normalize_pem_key(
            public_key,
            "-----BEGIN PUBLIC KEY-----",
            "-----END PUBLIC KEY-----",
        )
    except (ValueError, FileNotFoundError) as exc:
        raise AlipayConfigurationError(str(exc)) from exc

    logger.debug(
        "Initialized Alipay client (gateway=%s, app_id=%s, debug=%s)",
        client_config.server_url,
        client_config.app_id,
        settings.alipay_debug,
    )
    return DefaultAlipayClient(alipay_client_config=client_config, logger=logger)


def is_alipay_configured() -> bool:
    try:
        client = get_alipay_client()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Alipay client not ready: %s", exc)
        return False
    return bool(client)
