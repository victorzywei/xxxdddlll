from __future__ import annotations

import base64
import binascii
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


def _sanitize_pem_parts(raw_key: str) -> tuple[str | None, str, str | None]:
    """Return header, base64 payload, footer after stripping whitespace."""
    cleaned = raw_key.strip().replace("\r", "")
    header_match = _PEM_HEADER_RE.search(cleaned)
    footer_match = _PEM_FOOTER_RE.search(cleaned)
    header = header_match.group(0) if header_match else None
    footer = footer_match.group(0) if footer_match else None

    body = _PEM_HEADER_RE.sub("", cleaned)
    body = _PEM_FOOTER_RE.sub("", body)
    body = "".join(body.split())
    if not body:
        raise ValueError("PEM key content is empty after normalization.")
    return header, body, footer


def _wrap_pem(body: str, header: str, footer: str) -> str:
    wrapped_body = "\n".join(textwrap.wrap(body, 64)) if len(body) > 64 else body
    return "\n".join((header, wrapped_body, footer))


def _normalize_pem_key(raw_key: str, default_header: str, default_footer: str) -> str:
    """Return a PEM string with consistent header/footer and wrapped body."""
    header, body, footer = _sanitize_pem_parts(raw_key)
    header = header or default_header
    footer = footer or default_footer
    return _wrap_pem(body, header, footer)


def _is_pkcs1_private_key(candidate: bytes) -> bool:
    try:
        from rsa import PrivateKey  # type: ignore
    except ImportError:
        return False

    try:
        PrivateKey.load_pkcs1(candidate, format="DER")
        return True
    except Exception:  # noqa: BLE001
        return False


def _read_asn1_length(data: bytes, offset: int) -> tuple[int, int]:
    initial = data[offset]
    offset += 1
    if initial < 0x80:
        return initial, offset
    length_bytes = initial & 0x7F
    length = int.from_bytes(data[offset : offset + length_bytes], "big")
    offset += length_bytes
    return length, offset


def _extract_pkcs1_from_pkcs8(der_bytes: bytes) -> bytes | None:
    """Return PKCS#1 key bytes if the input is PKCS#8, else None."""
    if len(der_bytes) < 2 or der_bytes[0] != 0x30:
        return None
    _, cursor = _read_asn1_length(der_bytes, 1)
    if cursor >= len(der_bytes) or der_bytes[cursor] != 0x02:
        return None
    version_len, cursor = _read_asn1_length(der_bytes, cursor + 1)
    cursor += version_len
    if cursor >= len(der_bytes) or der_bytes[cursor] != 0x30:
        return None
    algo_len, cursor = _read_asn1_length(der_bytes, cursor + 1)
    cursor += algo_len
    if cursor >= len(der_bytes) or der_bytes[cursor] != 0x04:
        return None
    key_len, cursor = _read_asn1_length(der_bytes, cursor + 1)
    pkcs1 = der_bytes[cursor : cursor + key_len]
    return pkcs1 if pkcs1 else None


def _normalize_private_key(raw_key: str) -> str:
    """Normalize private key and convert PKCS#8 to PKCS#1 if needed."""
    header, body, footer = _sanitize_pem_parts(raw_key)
    try:
        der = base64.b64decode(body)
    except binascii.Error as exc:
        raise ValueError("Private key is not valid base64 data.") from exc

    if not _is_pkcs1_private_key(der):
        pkcs1_der = _extract_pkcs1_from_pkcs8(der)
        if not pkcs1_der or not _is_pkcs1_private_key(pkcs1_der):
            raise ValueError(
                "Unsupported private key format. Please provide an RSA PKCS#1 key."
            )
        body = base64.b64encode(pkcs1_der).decode("ascii")

    header = header or "-----BEGIN RSA PRIVATE KEY-----"
    footer = footer or "-----END RSA PRIVATE KEY-----"
    return _wrap_pem(body, header, footer)


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
        client_config.app_private_key = _normalize_private_key(private_key)
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
