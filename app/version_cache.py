from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import aiohttp
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/version", tags=["version"])

_settings = get_settings()
_cache_file = Path(_settings.windows_version_cache_file)
_max_age_ms = _settings.windows_version_cache_max_age_ms
_fetch_timeout = _settings.windows_version_fetch_timeout_seconds
_sources = [str(url) for url in _settings.windows_version_sources]

_CACHE_HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "public, s-maxage=120, stale-while-revalidate=30",
}


def _load_cache() -> Optional[Dict[str, Any]]:
    if not _cache_file.exists():
        return None
    try:
        with _cache_file.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read cache file '%s': %s", _cache_file, exc)
        return None


def _save_cache(record: Dict[str, Any]) -> None:
    _cache_file.parent.mkdir(parents=True, exist_ok=True)
    with _cache_file.open("w", encoding="utf-8") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)


def _is_fresh(record: Optional[Dict[str, Any]]) -> bool:
    if not record:
        return False
    last_update = record.get("lastUpdate")
    if not isinstance(last_update, str):
        return False
    try:
        parsed = time.strptime(last_update, "%Y-%m-%dT%H:%M:%S")
    except Exception:  # noqa: BLE001
        return False
    last_timestamp = time.mktime(parsed)
    return (time.time() - last_timestamp) * 1000 < _max_age_ms


def _is_valid_payload(payload: Any) -> bool:
    if not isinstance(payload, dict) or "version" not in payload:
        return False
       
    # 检查是否有 downloadurl 字段且为非空数组（新格式）
    if "downloadurl" in payload and isinstance(payload["downloadurl"], list) and len(payload["downloadurl"]) > 0:
        return True
    
    return False


async def _fetch_from_sources() -> Optional[Dict[str, Any]]:
    async with aiohttp.ClientSession() as session:
        for url in _sources:
            try:
                async with session.get(url, timeout=_fetch_timeout) as response:
                    if response.status != 200:
                        logger.warning("Upstream %s responded with %s", url, response.status)
                        continue
                    data = await response.json()
                    if _is_valid_payload(data):
                        # 如果是新格式（有 downloadurl），转换为旧格式
                        if "downloadurl" in data and isinstance(data["downloadurl"], list) and len(data["downloadurl"]) > 0:
                            # 复制数据并添加 url 字段（使用第一个下载链接）
                            converted_data = dict(data)
                            converted_data["url"] = data["downloadurl"][0]
                            # 可选：添加 backupUrls 字段（如果原来没有）
                            if "backupUrls" not in converted_data and len(data["downloadurl"]) > 1:
                                converted_data["backupUrls"] = data["downloadurl"][1:]
                            return converted_data
                        return data
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to fetch %s: %s", url, exc)
    return None


@router.get("/windows")
async def get_latest_windows_version() -> JSONResponse:
    cached = _load_cache()
    if _is_fresh(cached):
        return JSONResponse(content=cached["data"], headers=_CACHE_HEADERS)

    latest = await _fetch_from_sources()
    if latest:
        record = {
            "lastUpdate": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "data": latest,
        }
        try:
            _save_cache(record)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to update cache file '%s': %s", _cache_file, exc)
        return JSONResponse(content=latest, headers=_CACHE_HEADERS)

    if cached and "data" in cached:
        stale = dict(cached["data"])
        stale["stale"] = True
        return JSONResponse(content=stale, headers=_CACHE_HEADERS)

    return JSONResponse(
        status_code=503,
        content={"error": "No version data"},
        headers={"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"},
    )
