from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "FastAPI Alipay Demo"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    domain: str = "localhost"
    server_name: str = "localhost"
    base_url: AnyHttpUrl = Field(default="https://localhost")
    ssl_cert_path: str = "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
    ssl_key_path: str = "/etc/letsencrypt/live/${DOMAIN}/privkey.pem"

    database_url: str = "sqlite:////data/app.db"

    cors_origins: str = ""

    alipay_app_id: str = ""
    alipay_gateway: AnyHttpUrl = Field(
        default="https://openapi-sandbox.dl.alipaydev.com/gateway.do"
    )
    alipay_debug: bool = True
    alipay_notify_path: str = "/pay/notify"
    alipay_return_path: str = "/pay/return"
    alipay_app_private_key_path: str | None = None
    alipay_public_key_path: str | None = None
    alipay_app_private_key_pem: str | None = None
    alipay_public_key_pem: str | None = None

    @property
    def notify_url(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.alipay_notify_path}"

    @property
    def return_url(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.alipay_return_path}"

    @property
    def cors_origin_list(self) -> List[str]:
        if not self.cors_origins:
            return []
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def _load_key_from_path(self, path_value: Optional[str]) -> Optional[str]:
        if not path_value:
            return None
        path = Path(path_value)
        if not path.exists():
            raise FileNotFoundError(f"Key path not found: {path}")
        return path.read_text(encoding="utf-8").strip()

    def load_alipay_private_key(self) -> str:
        if self.alipay_app_private_key_pem:
            return self.alipay_app_private_key_pem.replace("\\n", "\n").strip()
        key = self._load_key_from_path(self.alipay_app_private_key_path)
        if key:
            return key
        raise ValueError(
            "Alipay private key is not configured. "
            "Set ALIPAY_APP_PRIVATE_KEY_PATH or ALIPAY_APP_PRIVATE_KEY_PEM."
        )

    def load_alipay_public_key(self) -> str:
        if self.alipay_public_key_pem:
            return self.alipay_public_key_pem.replace("\\n", "\n").strip()
        key = self._load_key_from_path(self.alipay_public_key_path)
        if key:
            return key
        raise ValueError(
            "Alipay public key is not configured. "
            "Set ALIPAY_PUBLIC_KEY_PATH or ALIPAY_PUBLIC_KEY_PEM."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
