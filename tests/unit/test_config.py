import base64
import secrets

import pytest
from pydantic import ValidationError

from oria_engine.config import ConfigurationError, Settings, load_settings


def production_env(monkeypatch):
    values = {
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql+psycopg://oria:local-only@localhost:5432/oria",
        "REDIS_URL": "redis://localhost:6379/0",
        "TELEGRAM_BOT_TOKEN": "123:" + secrets.token_urlsafe(32),
        "TELEGRAM_WEBHOOK_BASE_URL": "https://example.invalid/telegram",
        "TELEGRAM_WEBHOOK_SECRET": secrets.token_urlsafe(32),
        "PROFILE_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "SECOND_CONTEXT_BASE_URL": "http://secondcontext:8080",
        "ASTROLOGY_MCP_URL": "http://astrology-mcp:8000/mcp",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


def test_development_defaults_and_dotenv(monkeypatch, tmp_path):
    assert Settings().app_env == "development"
    (tmp_path / ".env").write_text("APP_ENV=test\nLOG_LEVEL=DEBUG\n")
    assert Settings().app_env == "test"
    assert Settings().log_level == "DEBUG"
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    assert Settings().log_level == "WARNING"


def test_valid_production(monkeypatch):
    values = production_env(monkeypatch)
    settings = load_settings()
    assert settings.app_env == "production"
    assert settings.telegram_bot_token.get_secret_value() == values["TELEGRAM_BOT_TOKEN"]
    assert values["TELEGRAM_BOT_TOKEN"] not in repr(settings)
    # SecondContext bearer authentication is optional by design.
    assert settings.second_context_bearer_token.get_secret_value() == ""


@pytest.mark.parametrize(
    "name",
    [
        "DATABASE_URL",
        "REDIS_URL",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_WEBHOOK_BASE_URL",
        "TELEGRAM_WEBHOOK_SECRET",
        "PROFILE_ENCRYPTION_KEY",
        "SECOND_CONTEXT_BASE_URL",
        "ASTROLOGY_MCP_URL",
    ],
)
def test_production_requires_explicit_values(monkeypatch, name):
    production_env(monkeypatch)
    monkeypatch.delenv(name)
    with pytest.raises(ConfigurationError):
        load_settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("APP_ENV", "prod"),
        ("LOG_LEVEL", "verbose"),
        ("DATABASE_URL", "sqlite:///local.db"),
        ("DATABASE_URL", "postgresql+psycopg://localhost"),
        ("REDIS_URL", "redis://localhost:bad/0"),
        ("REDIS_URL", "redis:///0"),
        ("REDIS_URL", "redis://localhost/not-a-database"),
        ("SECOND_CONTEXT_BEARER_TOKEN", "token with spaces"),
        ("SECOND_CONTEXT_BASE_URL", "ftp://localhost"),
        ("ASTROLOGY_MCP_URL", "http://user:password@localhost/mcp"),
        ("TELEGRAM_WEBHOOK_BASE_URL", "http://localhost"),
        ("TELEGRAM_BOT_TOKEN", "malformed"),
        ("TELEGRAM_WEBHOOK_SECRET", "contains spaces"),
        ("PROFILE_ENCRYPTION_KEY", "not-base64"),
        ("PROFILE_ENCRYPTION_KEY", base64.b64encode(b"too short").decode()),
        ("PROFILE_ENCRYPTION_KEY_VERSION", ""),
        ("ORIA_POLICY_VERSION", "bad version"),
    ],
)
def test_malformed_settings_fail_safely(monkeypatch, name, value):
    production_env(monkeypatch)
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError) as error:
        load_settings()
    if value:
        assert value not in str(error.value)


def test_validation_error_repr_hides_inputs(monkeypatch):
    secret = secrets.token_urlsafe(32)
    monkeypatch.setenv("PROFILE_ENCRYPTION_KEY", secret)
    with pytest.raises(ValidationError) as error:
        Settings()
    assert secret not in str(error.value)


@pytest.mark.parametrize(
    "namespace,token",
    [("oria", ""), ("oria:", "secret"), ("other/namespace", "secret"), ("A", "secret")],
)
def test_service_namespace_requires_explicit_token_and_valid_name(namespace, token):
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            second_context_subject_namespace=namespace,
            second_context_bearer_token=token,
        )


def test_service_namespace_is_opt_in():
    assert Settings(_env_file=None).second_context_subject_namespace == ""
    assert (
        Settings(
            _env_file=None,
            second_context_subject_namespace="oria",
            second_context_bearer_token="synthetic",
        ).second_context_subject_namespace
        == "oria"
    )
