from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from .alipay_client import AlipayConfigurationError
from .config import get_settings
from .database import Base, engine, get_db
from .schemas import (
    PaymentCreateRequest,
    PaymentCreateResponse,
    PaymentNotification,
)
from .services import payment as payment_service

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title=settings.app_name)

if origins := settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _ensure_sqlite_directory() -> None:
    db_url = settings.database_url
    if not db_url.startswith("sqlite"):
        return

    if db_url.startswith("sqlite:////"):
        db_path = Path(db_url.replace("sqlite:////", "/"))
    elif db_url.startswith("sqlite:///"):
        db_path = Path(db_url.replace("sqlite:///", ""))
    else:
        db_path = Path(db_url)

    db_path.parent.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
def on_startup() -> None:
    _ensure_sqlite_directory()
    Base.metadata.create_all(bind=engine)
    logger.info("Application started with environment '%s'", settings.app_env)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


@app.post("/pay/create", response_model=PaymentCreateResponse)
def create_payment(
    payload: PaymentCreateRequest,
    db: Session = Depends(get_db),
) -> PaymentCreateResponse:
    try:
        result = payment_service.create_payment_order(db, payload)
    except AlipayConfigurationError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return PaymentCreateResponse(**result)


def _normalize_path(path_value: str) -> str:
    return path_value if path_value.startswith("/") else f"/{path_value}"


@app.get(_normalize_path(settings.alipay_return_path), include_in_schema=False)
async def alipay_return(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    order = payment_service.handle_sync_return(db, dict(request.query_params))
    return JSONResponse(
        {
            "message": "Payment in progress",
            "out_trade_no": order.out_trade_no,
            "status": order.status.value,
        }
    )


@app.post(_normalize_path(settings.alipay_notify_path), include_in_schema=False)
async def alipay_notify(request: Request, db: Session = Depends(get_db)) -> PlainTextResponse:
    form = await request.form()
    raw_payload = {k: v for k, v in form.multi_items()}
    payload = PaymentNotification(**raw_payload)
    payment_service.handle_async_notification(db, payload, raw_payload)
    return PlainTextResponse("success")
