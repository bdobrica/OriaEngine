"""Explicit operator actions: set/reset or delete a bot webhook without logging secrets."""

import argparse
import asyncio
import sys

from aiogram import Bot

from oria_engine.config import ConfigurationError, Settings, load_settings
from oria_engine.observability import configure_logging
from oria_engine.telegram.adapter import ALLOWED_UPDATES
from oria_engine.telegram.webhook import validate_webhook_settings, webhook_url


async def configure_webhook(
    settings: Settings, action: str, *, drop_pending_updates: bool = False
) -> None:
    if not settings.telegram_bot_token.get_secret_value():
        raise ConfigurationError("Webhook management requires TELEGRAM_BOT_TOKEN")
    if action not in {"set", "reset", "delete"}:
        raise ConfigurationError("Unknown webhook management action")
    url = ""
    if action != "delete":
        validate_webhook_settings(settings)
        url = webhook_url(settings)
    bot = Bot(settings.telegram_bot_token.get_secret_value())
    try:
        async with asyncio.timeout(20):
            if action == "delete":
                success = await bot.delete_webhook(drop_pending_updates=drop_pending_updates)
            else:
                success = await bot.set_webhook(
                    url=url,
                    secret_token=settings.telegram_webhook_secret.get_secret_value(),
                    allowed_updates=ALLOWED_UPDATES,
                    drop_pending_updates=drop_pending_updates,
                )
            if success is not True:
                raise ConfigurationError("Telegram did not confirm webhook configuration")
    finally:
        await bot.session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure the Telegram webhook from environment")
    parser.add_argument("action", choices=("set", "reset", "delete"))
    parser.add_argument(
        "--drop-pending-updates",
        action="store_true",
        help="Explicitly discard pending Telegram updates (irreversible)",
    )
    arguments = parser.parse_args()
    try:
        settings = load_settings()
        configure_logging(settings)
        asyncio.run(
            configure_webhook(
                settings, arguments.action, drop_pending_updates=arguments.drop_pending_updates
            )
        )
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception:
        print("Webhook configuration failed; check credentials and connectivity", file=sys.stderr)
        raise SystemExit(1) from None
    print("Webhook configuration confirmed")


if __name__ == "__main__":
    main()
