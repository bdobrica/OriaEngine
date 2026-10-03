"""Typed configuration. Never include settings inputs in startup diagnostics."""

import base64
import binascii
import re
from typing import Literal, Self
from urllib.parse import unquote, urlsplit

from pydantic import SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, SettingsError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr = SecretStr("postgresql+psycopg://oria:oria@localhost:5432/oria")
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_webhook_base_url: str = ""
    telegram_webhook_secret: SecretStr = SecretStr("")
    profile_encryption_key: SecretStr = SecretStr("")
    profile_encryption_key_version: str = "v1"
    second_context_base_url: str = "http://localhost:8080"
    second_context_bearer_token: SecretStr = SecretStr("")
    second_context_subject_namespace: str = ""
    astrology_mcp_url: str = "http://localhost:8000/mcp"
    oria_policy_version: str = "2026-10-03.1"

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        urls = {
            "database_url": (self.database_url.get_secret_value(), {"postgresql+psycopg"}),
            "redis_url": (self.redis_url.get_secret_value(), {"redis", "rediss"}),
            "second_context_base_url": (self.second_context_base_url, {"http", "https"}),
            "astrology_mcp_url": (self.astrology_mcp_url, {"http", "https"}),
        }
        if self.telegram_webhook_base_url:
            urls["telegram_webhook_base_url"] = (self.telegram_webhook_base_url, {"https"})
        for name, (value, schemes) in urls.items():
            try:
                parsed = urlsplit(value)
                valid = parsed.scheme in schemes and bool(parsed.hostname)
                valid = valid and not any(c.isspace() or ord(c) < 32 for c in value)
                valid = valid and not parsed.fragment
                _ = parsed.port
                if "http" in schemes or name == "telegram_webhook_base_url":
                    valid = (
                        valid and not parsed.username and not parsed.password and not parsed.query
                    )
                if name == "database_url":
                    valid = valid and bool(parsed.path.strip("/"))
                if name == "redis_url":
                    valid = valid and bool(re.fullmatch(r"/?[0-9]*", parsed.path))
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(f"{name}: invalid URL")

        token = self.telegram_bot_token.get_secret_value()
        if token and not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
            raise ValueError("telegram_bot_token: invalid format")
        webhook_secret = self.telegram_webhook_secret.get_secret_value()
        if webhook_secret and not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", webhook_secret):
            raise ValueError("telegram_webhook_secret: invalid format")
        bearer = self.second_context_bearer_token.get_secret_value()
        if bearer and any(c.isspace() or ord(c) < 32 for c in bearer):
            raise ValueError("second_context_bearer_token: invalid format")
        namespace = self.second_context_subject_namespace
        if namespace and (not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", namespace) or not bearer):
            raise ValueError(
                "second_context_subject_namespace: requires valid namespace and bearer token"
            )
        key = self.profile_encryption_key.get_secret_value()
        if key:
            try:
                decoded = base64.b64decode(key, altchars=b"-_", validate=True)
            except (ValueError, binascii.Error):
                raise ValueError("profile_encryption_key: expected base64 AES-256 key") from None
            if len(decoded) != 32:
                raise ValueError("profile_encryption_key: expected 32 decoded bytes")
        for version in (self.profile_encryption_key_version, self.oria_policy_version):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", version):
                raise ValueError("configuration version: invalid identifier")
        if self.app_env == "production":
            required = {
                "database_url",
                "redis_url",
                "second_context_base_url",
                "astrology_mcp_url",
                "telegram_bot_token",
                "telegram_webhook_base_url",
                "telegram_webhook_secret",
                "profile_encryption_key",
            }
            if required - self.model_fields_set or not all(
                (token, webhook_secret, key, self.telegram_webhook_base_url)
            ):
                raise ValueError(
                    "production requires explicit service URLs and Telegram/profile secrets"
                )
        return self

    def secret_values(self) -> tuple[str, ...]:
        values = [
            value.get_secret_value()
            for name in type(self).model_fields
            if isinstance(value := getattr(self, name), SecretStr)
        ]
        for url in (self.database_url, self.redis_url):
            password = urlsplit(url.get_secret_value()).password
            if password:
                values.extend((password, unquote(password)))
        return tuple(value for value in values if value)


class ConfigurationError(RuntimeError):
    """Safe diagnostic for the process entrypoint."""


def load_settings() -> Settings:
    try:
        return Settings()
    except (ValidationError, ValueError, SettingsError):
        # Pydantic error dictionaries and chained exceptions may contain raw input.
        raise ConfigurationError(
            "Invalid application configuration; check environment settings"
        ) from None
