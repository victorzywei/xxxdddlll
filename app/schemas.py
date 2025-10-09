from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from pydantic import BaseModel, EmailStr, Field, HttpUrl
from pydantic.config import ConfigDict


class UserInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    preferred_username: str
    email: EmailStr
    sub: str
    username: str
    id_token: str


class PaymentCreateRequest(BaseModel):
    subject: str = Field(..., max_length=128)
    recharge_days: int = Field(..., ge=0, description="Additional membership days purchased")
    total_amount: Decimal = Field(..., gt=Decimal("0.0"))
    channel: Literal["pc", "wap"] = "pc"
    description: Optional[str] = Field(default=None, max_length=256)
    payment_method: Literal["alipay"] = "alipay"
    user_info: UserInfo


class PaymentCreateResponse(BaseModel):
    out_trade_no: str
    subject: str
    payment_method: str
    created_at: datetime
    authingpost: bool
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
    recharge_days: int
    total_amount: Decimal
    channel: str
    description: Optional[str] = None
    payment_method: str
    user_info: Optional[UserInfo] = None
    status: str
    trade_no: Optional[str] = None
    buyer_logon_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    authingpost: bool
