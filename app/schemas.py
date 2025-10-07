from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl
from pydantic.config import ConfigDict


class PaymentCreateRequest(BaseModel):
    subject: str = Field(..., max_length=128)
    total_amount: Decimal = Field(..., gt=Decimal("0.0"))
    channel: Literal["pc", "wap"] = "pc"


class PaymentCreateResponse(BaseModel):
    out_trade_no: str
    pay_url: HttpUrl


class PaymentReturnQuery(BaseModel):
    out_trade_no: str
    trade_no: Optional[str] = None
    total_amount: Decimal


class PaymentNotification(BaseModel):
    model_config = ConfigDict(extra="ignore")

    out_trade_no: str
    trade_no: str
    total_amount: Decimal
    trade_status: str
    buyer_logon_id: Optional[str] = None


class PaymentOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    out_trade_no: str
    subject: str
    total_amount: Decimal
    channel: str
    status: str
    trade_no: Optional[str] = None
    buyer_logon_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
