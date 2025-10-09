#!/usr/bin/env python
"""Ad-hoc runner for exercising the Authing membership update flow."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest.mock import patch

from sqlalchemy import select

# Ensure project root is importable when executing as a script.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import session_scope
from app.models import PaymentOrder
from app.services import authing_post

DEFAULT_AUTHING_USERPOOL_ID = "68b8b039eba2f6cdd3c6bd06"
DEFAULT_AUTHING_OFFSET_SECRET = "kT9f6P2QmN8xR4vZ1"
DEFAULT_AUTHING_HMAC_SECRET = "9tZVJhbmRvbVNlY3JldEt"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Directly invoke the Authing membership update helper."
    )
    parser.add_argument(
        "out_trade_no",
        nargs="?",
        help="Load order details directly from the database using this out_trade_no.",
    )
    parser.add_argument("--user-id", help="Authing user identifier (sub).")
    parser.add_argument(
        "--id-token",
        help="Authing access token with update permission (include Bearer prefix if needed).",
    )
    parser.add_argument(
        "--recipe",
        help="Membership recipe JSON string or @/path/to/file.json (required if no out_trade_no).",
    )
    parser.add_argument(
        "--preferred-username",
        default=None,
        help="Existing encoded membership token from Authing (optional).",
    )
    parser.add_argument(
        "--authing-userpool-id",
        default=None,
        help="Override Authing userpool id (defaults to hardcoded testing value).",
    )
    parser.add_argument(
        "--authing-offset-secret",
        default=None,
        help="Override Authing offset secret (defaults to hardcoded testing value).",
    )
    parser.add_argument(
        "--authing-hmac-secret",
        default=None,
        help="Override Authing HMAC secret (defaults to hardcoded testing value).",
    )
    parser.add_argument(
        "--recharge-days",
        type=int,
        default=0,
        help="Optional extra recharge days to add on top of the recipe.",
    )
    parser.add_argument(
        "--out-trade-no",
        default=None,
        help="Custom order id to use in logs when not loading from DB.",
    )
    parser.add_argument(
        "--description",
        default=None,
        help="Optional JSON string to store in order.description for recipe lookup.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the Authing API call while still exercising the token logic.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ...).",
    )
    return parser


def parse_args() -> argparse.Namespace:
    parser = _build_parser()
    args = parser.parse_args()
    if not args.out_trade_no:
        missing = [
            flag
            for flag, value in (
                ("--user-id", args.user_id),
                ("--id-token", args.id_token),
                ("--recipe", args.recipe),
            )
            if not value
        ]
        if missing:
            parser.error(
                "When no out_trade_no is provided you must supply --user-id, --id-token, and --recipe."
            )
    return args


def _load_json(value: str) -> Dict[str, Any]:
    text = value
    if value.startswith("@"):
        path = value[1:]
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except OSError as exc:
            raise SystemExit(f"Unable to read recipe file '{path}': {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("Recipe JSON must decode to an object.")
    return payload


def _mask(value: Optional[str], visible: int = 6) -> str:
    if not value:
        return ""
    return value[:visible] + "***" if len(value) > visible else value


def _load_order_from_db(out_trade_no: str) -> SimpleNamespace:
    with session_scope() as session:
        stmt = select(PaymentOrder).filter_by(out_trade_no=out_trade_no)
        order: Optional[PaymentOrder] = session.scalars(stmt).first()
        if not order:
            raise SystemExit(f"Order '{out_trade_no}' not found in the database.")
        payload = SimpleNamespace(
            out_trade_no=order.out_trade_no,
            user_info=dict(order.user_info or {}),
            description=order.description,
            recharge_days=getattr(order, "recharge_days", 0),
        )
    logging.getLogger("authing-test").info(
        "Loaded order %s from database (recharge_days=%s)",
        payload.out_trade_no,
        payload.recharge_days,
    )
    return payload


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )

    offset_secret = args.authing_offset_secret or DEFAULT_AUTHING_OFFSET_SECRET
    hmac_secret = args.authing_hmac_secret or DEFAULT_AUTHING_HMAC_SECRET
    userpool_id = args.authing_userpool_id or DEFAULT_AUTHING_USERPOOL_ID

    missing_values = [
        name
        for name, value in (
            ("AUTHING_OFFSET_SECRET", offset_secret),
            ("AUTHING_HMAC_SECRET", hmac_secret),
            ("AUTHING_USERPOOL_ID", userpool_id),
        )
        if not value
    ]
    if missing_values:
        env_list = ", ".join(missing_values)
        raise SystemExit(f"Missing Authing configuration values: {env_list}.")

    os.environ["AUTHING_OFFSET_SECRET"] = offset_secret
    os.environ["AUTHING_HMAC_SECRET"] = hmac_secret
    os.environ["AUTHING_USERPOOL_ID"] = userpool_id

    if args.out_trade_no:
        order = _load_order_from_db(args.out_trade_no)
        if args.user_id:
            for key in ("sub", "userId", "id"):
                order.user_info[key] = args.user_id
        if args.id_token:
            for key in ("id_token", "idToken", "token"):
                order.user_info[key] = args.id_token
        if args.recipe:
            order.user_info["membership_recipe"] = _load_json(args.recipe)
        if args.preferred_username:
            order.user_info["preferred_username"] = args.preferred_username
            order.user_info["preferredUsername"] = args.preferred_username
    else:
        recipe_payload = _load_json(args.recipe)
        description_payload: Optional[str] = args.description

        if description_payload:
            try:
                json.loads(description_payload)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"--description must be valid JSON: {exc}") from exc

        user_info: Dict[str, Any] = {
            "sub": args.user_id,
            "userId": args.user_id,
            "id_token": args.id_token,
            "idToken": args.id_token,
            "preferred_username": args.preferred_username,
            "preferredUsername": args.preferred_username,
            "membership_recipe": recipe_payload,
        }

        order = SimpleNamespace(
            out_trade_no=args.out_trade_no or "manual-test",
            user_info=user_info,
            description=description_payload,
            recharge_days=args.recharge_days,
        )

    if args.recipe:
        recipe_data = _load_json(args.recipe)
    else:
        recharge_days = getattr(order, "recharge_days", 0) or 0
        try:
            recharge_days = int(recharge_days)
        except (TypeError, ValueError):
            recharge_days = 0
        recipe_data = {"type": "STACK", "durationDays": max(recharge_days, 0)}

    order.user_info["membership_recipe"] = recipe_data

    original_update = authing_post.update_preferred_username

    def instrumented_update(user_id: str, preferred_username: str, token: str) -> Dict[str, Any]:
        logging.getLogger("authing-test").info(
            "Prepared Authing update: user_id=%s token=%s new_preferred_username=%s",
            user_id,
            _mask(token),
            preferred_username,
        )
        if args.dry_run:
            return {"ok": True, "status": "dry-run", "preferredUsername": preferred_username}
        return original_update(user_id=user_id, preferred_username=preferred_username, token=token)

    with patch("app.services.authing_post.update_preferred_username", side_effect=instrumented_update):
        success = authing_post.update_membership_for_order(order)

    outcome = "succeeded" if success else "failed"
    logging.getLogger("authing-test").info("Authing membership update %s for order %s", outcome, order.out_trade_no)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
