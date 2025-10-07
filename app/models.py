from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import DateTime, Enum, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    succeeded = "succeeded"
    failed = "failed"


class PaymentOrder(Base):
    __tablename__ = "payment_orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    out_trade_no: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=lambda: uuid4().hex)
    subject: Mapped[str] = mapped_column(String(128))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    channel: Mapped[str] = mapped_column(String(16))
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.pending)
    trade_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    buyer_logon_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def mark_processing(self) -> None:
        self.status = PaymentStatus.processing

    def mark_succeeded(self, trade_no: str, buyer_logon_id: str | None = None) -> None:
        self.status = PaymentStatus.succeeded
        self.trade_no = trade_no
        self.buyer_logon_id = buyer_logon_id

    def mark_failed(self) -> None:
        self.status = PaymentStatus.failed
