"""Guard destructive developer commands, including settings loaded from .env."""

from oria_engine.config import ConfigurationError, load_settings


def require_local() -> None:
    if load_settings().app_env not in {"development", "test"}:
        raise ConfigurationError("This command is only available in development/test")


if __name__ == "__main__":
    try:
        require_local()
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from None
