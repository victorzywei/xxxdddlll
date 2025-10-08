from __future__ import annotations

import base64
import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from secrets import choice

DEC_LEN = 22
MOD_M = 10 ** DEC_LEN
BASE62_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE64URL_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


@dataclass(frozen=True)
class DecodedMembership:
    Flag0: str
    Flag1: str
    rechargeDateTime: str  # YYYYMMDDHH
    expireDateTime: str  # YYYYMMDDHH
    isExpired: bool


def assert_digits(value: str, length: int, name: str) -> None:
    if not isinstance(value, str) or len(value) != length or not value.isdigit():
        raise ValueError(f"{name} must be exactly {length} digits")


def random_base64url(length: int = 1) -> str:
    return "".join(choice(BASE64URL_CHARS) for _ in range(length))


def big_int_to_base62(number: int) -> str:
    if number < 0:
        raise ValueError("number must be non-negative")
    if number == 0:
        return "0"
    base = 62
    digits: list[str] = []
    n = number
    while n > 0:
        n, remainder = divmod(n, base)
        digits.append(BASE62_CHARS[remainder])
    return "".join(reversed(digits))


def base62_to_big_int(value: str) -> int:
    base = 62
    result = 0
    for char in value:
        index = BASE62_CHARS.find(char)
        if index == -1:
            raise ValueError(f"invalid base62 digit: {char}")
        result = result * base + index
    return result


def timing_safe_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def hmac_trunc_base64url(data: str, secret: str, mac_len: int = 6) -> str:
    digest = hmac.new(secret.encode("utf-8"), data.encode("utf-8"), "sha256").digest()
    mac = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return mac[:mac_len]


def derive_offset_int(offset_secret: str, salt: str = "OFFSET-V1") -> int:
    digest = hmac.new(offset_secret.encode("utf-8"), salt.encode("utf-8"), "sha256").digest()
    big = int.from_bytes(digest, "big")
    offset = big % (MOD_M - 1)
    return offset + 1


def mod(value: int, modulus: int) -> int:
    remainder = value % modulus
    return remainder if remainder >= 0 else remainder + modulus


def encode_membership(
    Flag0: str,
    Flag1: str,
    rechargeDateTime: str,
    expireDateTime: str,
    offset_secret: str,
    hmac_secret: str,
    prefix_len: int = 1,
    mac_len: int = 6,
) -> str:
    assert_digits(Flag0, 1, "Flag0")
    assert_digits(Flag1, 1, "Flag1")
    assert_digits(rechargeDateTime, 10, "rechargeDateTime")
    assert_digits(expireDateTime, 10, "expireDateTime")

    raw = f"{Flag0}{Flag1}{rechargeDateTime}{expireDateTime}"
    raw_int = int(raw)

    offset = derive_offset_int(offset_secret)
    shifted = mod(raw_int + offset, MOD_M)

    base62_value = big_int_to_base62(shifted)
    prefix = random_base64url(prefix_len)
    core = prefix + base62_value

    mac = hmac_trunc_base64url(core, hmac_secret, mac_len)
    return core + mac


def decode_membership(
    token: str,
    offset_secret: str,
    hmac_secret: str,
    prefix_len: int = 1,
    mac_len: int = 6,
) -> DecodedMembership:
    if not isinstance(token, str):
        raise TypeError("invalid token")
    if len(token) <= prefix_len + mac_len:
        raise ValueError("token too short")

    core = token[:-mac_len]
    mac = token[-mac_len:]

    expected_mac = hmac_trunc_base64url(core, hmac_secret, mac_len)
    if not timing_safe_eq(mac, expected_mac):
        raise ValueError("HMAC verification failed")

    base62_part = core[prefix_len:]
    if not base62_part or not re.fullmatch(r"[0-9A-Za-z]+", base62_part):
        raise ValueError("invalid base62 segment")

    shifted = base62_to_big_int(base62_part)
    offset = derive_offset_int(offset_secret)
    raw_int = mod(shifted - offset, MOD_M)
    raw_str = f"{raw_int:0{DEC_LEN}d}"

    Flag0 = raw_str[0]
    Flag1 = raw_str[1]
    rechargeDateTime = raw_str[2:12]
    expireDateTime = raw_str[12:22]

    year1 = int(rechargeDateTime[:4])
    if year1 < 2024 or year1 > 2100:
        raise ValueError("信息异常")
    if expireDateTime < rechargeDateTime:
        raise ValueError("信息异常")

    now = datetime.now(timezone.utc)
    now_str = (
        f"{now.year:04d}"
        f"{now.month:02d}"
        f"{now.day:02d}"
        f"{now.hour:02d}"
    )

    is_expired = expireDateTime < now_str

    return DecodedMembership(
        Flag0=Flag0,
        Flag1=Flag1,
        rechargeDateTime=rechargeDateTime,
        expireDateTime=expireDateTime,
        isExpired=is_expired,
    )
