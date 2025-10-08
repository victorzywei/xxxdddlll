import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Literal, MutableMapping, Optional

import requests

from ..models import PaymentOrder
from .membership_codec import decode_membership, encode_membership

logger = logging.getLogger(__name__)

HourString = str


@dataclass
class MembershipRecipe:
    type: Literal["STACK", "SET_EXPIRY"]
    duration_days: Optional[int] = None
    target_expiry_utc: Optional[HourString] = None

    @classmethod
    def from_payload(cls, payload: Any) -> Optional["MembershipRecipe"]:
        if not isinstance(payload, MutableMapping):
            return None

        raw_type = payload.get("type")
        if not isinstance(raw_type, str):
            return None
        normalized_type = raw_type.strip().upper()

        if normalized_type == "STACK":
            days = payload.get("durationDays")
            try:
                days_int = int(days)
            except (TypeError, ValueError):
                return None
            if days_int < 0:
                return None
            return cls(type="STACK", duration_days=days_int)

        if normalized_type == "SET_EXPIRY":
            target = payload.get("targetExpiryUtc")
            if not isinstance(target, str):
                return None
            cleaned = target.strip()
            if not _is_valid_hour(cleaned):
                return None
            return cls(type="SET_EXPIRY", target_expiry_utc=cleaned)

        return None

    def compute_new_expiry(self, *, current_expire: Optional[HourString], now_hour: HourString) -> HourString:
        base = current_expire if current_expire and current_expire > now_hour else now_hour

        if self.type == "STACK":
            days = self.duration_days or 0
            return _add_days_from(base, days)

        if self.type == "SET_EXPIRY":
            if not self.target_expiry_utc:
                raise ValueError("target_expiry_utc is required for SET_EXPIRY recipes")
            if current_expire and self.target_expiry_utc <= current_expire:
                raise ValueError("expiry must increase")
            return self.target_expiry_utc

        raise ValueError(f"Unsupported membership recipe type: {self.type}")


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


def update_membership_for_order(order: PaymentOrder) -> Optional[Dict[str, Any]]:
    user_info = order.user_info or {}
    if not isinstance(user_info, MutableMapping):
        logger.warning("Order %s user_info is not a mapping; skip Authing update.", order.out_trade_no)
        return None

    user_id = _read_first(user_info, ("sub", "userId", "id"))
    id_token = _read_first(user_info, ("id_token", "idToken", "token"))
    preferred_username = _read_first(user_info, ("preferred_username", "preferredUsername"))

    if not user_id or not id_token:
        logger.warning("Missing Authing credentials in user_info for order %s; skip.", order.out_trade_no)
        return None

    offset_secret = os.getenv("AUTHING_OFFSET_SECRET")
    hmac_secret = os.getenv("AUTHING_HMAC_SECRET")
    if not offset_secret or not hmac_secret:
        logger.warning("Authing membership secrets not configured; skipping update for order %s.", order.out_trade_no)
        return None

    recipe = _extract_membership_recipe(order)
    if not recipe:
        logger.warning("Unable to locate membership recipe for order %s; skip Authing update.", order.out_trade_no)
        return None

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
        new_expire = recipe.compute_new_expiry(current_expire=current_expire, now_hour=now_hour)
    except Exception as exc:  # noqa: BLE001
        logger.error("Unable to compute new membership expiry for order %s: %s", order.out_trade_no, exc)
        return None

    extra_days = max(getattr(order, "recharge_days", 0) or 0, 0)
    if extra_days:
        try:
            new_expire = _add_days_from(new_expire, extra_days)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to add recharge_days=%s to expiry for order %s: %s",
                extra_days,
                order.out_trade_no,
                exc,
            )
            return None

    try:
        new_token = encode_membership("0", "0", now_hour, new_expire, offset_secret, hmac_secret)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to encode membership token for order %s: %s", order.out_trade_no, exc)
        return None

    response = update_preferred_username(user_id=user_id, preferred_username=new_token, token=id_token)

    if response.get("ok"):
        logger.info("Updated Authing preferred_username for user %s via order %s.", user_id, order.out_trade_no)
    else:
        logger.error("Authing update failed for user %s via order %s: %s", user_id, order.out_trade_no, response)

    return {"new_token": new_token, "response": response}


def _read_first(data: MutableMapping[str, Any], keys: Iterable[str]) -> Optional[Any]:
    for key in keys:
        value = data.get(key)
        if value:
            return value
    return None


def _extract_membership_recipe(order: PaymentOrder) -> Optional[MembershipRecipe]:
    candidates: list[Any] = []

    if order.description:
        try:
            candidates.append(json.loads(order.description))
        except json.JSONDecodeError:
            logger.debug("Order %s description is not JSON; ignoring for membership recipe.", order.out_trade_no)

    user_info = order.user_info or {}
    if isinstance(user_info, MutableMapping):
        for key in ("membership_recipe", "membershipRecipe", "membership", "plan", "rec"):
            value = user_info.get(key)
            if value:
                candidates.append(value)

    for candidate in candidates:
        payload: Any = candidate
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        recipe = MembershipRecipe.from_payload(payload)
        if recipe:
            return recipe

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
