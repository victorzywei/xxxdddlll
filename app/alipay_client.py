from __future__ import annotations

import logging
from functools import lru_cache

from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient

from .config import get_settings

logger = logging.getLogger("alipay")


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
        client_config.app_private_key = settings.load_alipay_private_key()
        client_config.alipay_public_key = settings.load_alipay_public_key()
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
