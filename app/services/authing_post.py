import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, MutableMapping, Optional

import requests

from ..models import PaymentOrder
from .membership_codec import decode_membership, encode_membership

logger = logging.getLogger(__name__)

HourString = str


def update_preferred_username(user_id: str, preferred_username: str, token: str) -> Dict[str, Any]:
    if not user_id or not preferred_username or not token:
        return {"ok": False, "error": "Missing Authing parameters"}

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Authorization": token,
    }

    userpool_id = os.getenv("AUTHING_USERPOOL_ID")
    if not userpool_id:
        return {"ok": False, "error": "AUTHING_USERPOOL_ID is not configured"}

    headers["x-authing-userpool-id"] = userpool_id

    endpoint = f"https://api.authing.cn/api/v2/users/{user_id}"
    response = requests.post(
        endpoint,
        headers=headers,
        json={"preferredUsername": preferred_username},
        timeout=10,
    )

    if response.status_code == 201:
        return {"ok": True, "status": response.status_code}

    return {
        "ok": False,
        "status": response.status_code,
        "statusText": response.reason,
        "error": response.text,
    }


def update_membership_for_order(order: PaymentOrder) -> bool:
    user_info = order.user_info or {}
    if not isinstance(user_info, MutableMapping):
        logger.warning("Order %s user_info is not a mapping; skip Authing update.", order.out_trade_no)
        return False

    user_id = _read_first(user_info, ("sub", "userId", "id"))
    id_token = _read_first(user_info, ("id_token", "idToken", "token"))
    preferred_username = _read_first(user_info, ("preferred_username", "preferredUsername"))

    if not user_id or not id_token:
        logger.warning("Missing Authing credentials in user_info for order %s; skip.", order.out_trade_no)
        return False

    offset_secret = os.getenv("AUTHING_OFFSET_SECRET")
    hmac_secret = os.getenv("AUTHING_HMAC_SECRET")
    if not offset_secret or not hmac_secret:
        logger.warning("Authing membership secrets not configured; skipping update for order %s.", order.out_trade_no)
        return False

    now_hour = _now_utc_hour()
    current_expire: Optional[HourString] = None

    if preferred_username:
        try:
            decoded = decode_membership(preferred_username, offset_secret, hmac_secret)
            current_expire = decoded.expireDateTime
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to decode membership token for order %s; using current time: %s",
                order.out_trade_no,
                exc,
            )

    try:
        recharge_days = int(getattr(order, "recharge_days", 0) or 0)
    except (TypeError, ValueError):
        logger.warning("Invalid recharge_days for order %s; treating as 0.", order.out_trade_no)
        recharge_days = 0

    if recharge_days < 0:
        logger.warning(
            "Negative recharge_days=%s for order %s; skip Authing update.",
            recharge_days,
            order.out_trade_no,
        )
        return False

    base_hour = current_expire if current_expire and current_expire > now_hour else now_hour

    try:
        new_expire = _add_days_from(base_hour, recharge_days)
    except Exception as exc:  # noqa: BLE001
        logger.error("Unable to compute new membership expiry for order %s: %s", order.out_trade_no, exc)
        return False

    try:
        new_token = encode_membership("0", "0", now_hour, new_expire, offset_secret, hmac_secret)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to encode membership token for order %s: %s", order.out_trade_no, exc)
        return False

    response = update_preferred_username(user_id=user_id, preferred_username=new_token, token=id_token)

    success = bool(response.get("ok"))
    if success:
        logger.info(
            "Updated Authing preferred_username for user %s via order %s with expiry %s.",
            user_id,
            order.out_trade_no,
            new_expire,
        )
        return True

    logger.error("Authing update failed for user %s via order %s: %s", user_id, order.out_trade_no, response)
    return False


def _read_first(data: MutableMapping[str, Any], keys: Iterable[str]) -> Optional[Any]:
    for key in keys:
        value = data.get(key)
        if value:
            return value
    return None


def _now_utc_hour() -> HourString:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H")


def _add_days_from(base: HourString, days: int) -> HourString:
    if not _is_valid_hour(base):
        raise ValueError("base must be YYYYMMDDHH digits")
    dt = datetime.strptime(base, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    shifted = dt + timedelta(days=days)
    return shifted.strftime("%Y%m%d%H")


def _is_valid_hour(value: str) -> bool:
    return isinstance(value, str) and len(value) == 10 and value.isdigit()
