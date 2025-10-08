from __future__ import annotations

import logging
from copy import deepcopy
from decimal import Decimal
from typing import Dict, Mapping, Tuple

from alipay.aop.api.domain.AlipayTradePagePayModel import AlipayTradePagePayModel
from alipay.aop.api.request.AlipayTradePagePayRequest import AlipayTradePagePayRequest
from alipay.aop.api.util.SignatureUtils import get_sign_content, verify_with_rsa
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..alipay_client import AlipayConfigurationError, get_alipay_client
from ..config import get_settings
from ..models import PaymentOrder, PaymentStatus
from ..schemas import PaymentCreateRequest, PaymentNotification

logger = logging.getLogger(__name__)
settings = get_settings()

ALIPAY_SUCCESS_STATUSES: Tuple[str, ...] = ("TRADE_SUCCESS", "TRADE_FINISHED")


def _get_product_code(channel: str) -> str:
    return "FAST_INSTANT_TRADE_PAY" if channel == "pc" else "QUICK_WAP_WAY"


def _normalize_signature(signature: str) -> str:
    """Return signature with whitespace trimmed and plus signs restored."""
    normalized = signature.strip()
    normalized = normalized.replace("%2B", "+").replace("%2F", "/")
    normalized = normalized.replace(" ", "+").replace("\n", "").replace("\r", "")
    normalized = normalized.replace("-", "+").replace("_", "/")
    remainder = len(normalized) % 4
    if remainder:
        normalized += "=" * (4 - remainder)
    return normalized


def _verify_signature(payload: Mapping[str, str]) -> bool:
    data = deepcopy(dict(payload))
    raw_signature = data.pop("sign", None)
    signature = _normalize_signature(raw_signature) if raw_signature else None
    sign_type = (data.pop("sign_type", "RSA2") or "RSA2").upper()
    if not signature:
        logger.warning("Missing signature in Alipay payload: %s", data)
        return False
    client = get_alipay_client()
    config = getattr(client, "_DefaultAlipayClient__config", None)
    if not config or not getattr(config, "alipay_public_key", None):
        logger.error("Alipay client misconfigured: missing public key for signature verification.")
        return False
    charset = getattr(config, "charset", "utf-8") or "utf-8"
    filtered_params = {k: v for k, v in data.items() if v is not None}
    try:
        sign_content = get_sign_content(filtered_params)
        message = sign_content.encode(charset)
        verified = verify_with_rsa(config.alipay_public_key, message, signature)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to verify Alipay signature: %s", exc)
        return False
    if not verified:
        logger.warning("Signature verification failed for payload: %s", data)
        return False
    if sign_type not in {"RSA", "RSA2"}:
        logger.debug("Unexpected Alipay sign_type '%s' encountered.", sign_type)
    return True


def create_payment_order(db: Session, payload: PaymentCreateRequest) -> Dict[str, str]:
    try:
        client = get_alipay_client()
    except AlipayConfigurationError as exc:
        logger.error("Alipay configuration error: %s", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    amount = payload.total_amount.quantize(Decimal("0.01"))

    order = PaymentOrder(
        subject=payload.subject,
        total_amount=amount,
        channel=payload.channel,
        description=payload.description,
        payment_method=payload.payment_method,
        user_info=payload.user_info.model_dump(),
        status=PaymentStatus.pending,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    model = AlipayTradePagePayModel()
    model.out_trade_no = order.out_trade_no
    model.total_amount = format(amount, ".2f")
    model.subject = payload.subject
    model.product_code = _get_product_code(payload.channel)

    request = AlipayTradePagePayRequest()
    request.biz_model = model
    request.notify_url = settings.notify_url
    request.return_url = settings.return_url

    try:
        pay_url = client.page_execute(request, http_method="GET")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to create Alipay order: %s", exc)
        order.mark_failed()
        db.add(order)
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Failed to create Alipay order.") from exc

    logger.info("Created Alipay order out_trade_no=%s channel=%s", order.out_trade_no, payload.channel)
    return {"out_trade_no": order.out_trade_no, "pay_url": pay_url}


def get_payment_order(db: Session, out_trade_no: str) -> PaymentOrder:
    stmt = select(PaymentOrder).filter_by(out_trade_no=out_trade_no)
    order = db.execute(stmt).scalar_one_or_none()
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Order not found.")
    return order


def handle_sync_return(db: Session, query_params: Mapping[str, str]) -> PaymentOrder:
    if not _verify_signature(query_params):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid signature.")

    out_trade_no = query_params.get("out_trade_no")
    if not out_trade_no:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Missing out_trade_no.")

    return get_payment_order(db, out_trade_no)


def handle_async_notification(db: Session, payload: PaymentNotification, raw_form: Mapping[str, str]) -> PaymentOrder:
    if not _verify_signature(raw_form):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid signature.")

    order = get_payment_order(db, payload.out_trade_no)

    if payload.trade_status in ALIPAY_SUCCESS_STATUSES:
        order.mark_paid(trade_no=payload.trade_no, buyer_logon_id=payload.buyer_logon_id)
    else:
        order.mark_failed()

    db.add(order)
    db.commit()
    db.refresh(order)
    return order
