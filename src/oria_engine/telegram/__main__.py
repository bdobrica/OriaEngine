"""Local polling process: python -m oria_engine.telegram / make run."""

import asyncio
import logging
import sys

from aiogram import Bot

from oria_engine.config import ConfigurationError, Settings, load_settings
from oria_engine.db.session import Database
from oria_engine.domain.consent import ConsentFlow
from oria_engine.observability import configure_logging
from oria_engine.telegram.adapter import TelegramChannelClient, create_dispatcher

logger = logging.getLogger(__name__)


async def run_polling(settings: Settings) -> None:
    if settings.app_env == "production":
        raise ConfigurationError("Local polling is disabled in production; use the webhook gateway")
    if not settings.telegram_bot_token.get_secret_value():
        raise ConfigurationError("Local polling requires TELEGRAM_BOT_TOKEN; see docs/telegram.md")
    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    database: Database | None = None
    try:
        webhook = await bot.get_webhook_info()
        if webhook.url:
            raise ConfigurationError(
                "Bot has an active webhook; use a dedicated development bot for polling"
            )
        database = Database(settings)
        dispatcher = create_dispatcher(
            TelegramChannelClient(bot), ConsentFlow(database, settings.oria_policy_version)
        )
        logger.info("application_started")
        await dispatcher.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
            handle_as_tasks=False,
            close_bot_session=False,
        )
    finally:
        try:
            if database is not None:
                await database.close()
        finally:
            await bot.session.close()
        logger.info("application_stopped")


def main() -> None:
    try:
        settings = load_settings()
        configure_logging(settings)
        asyncio.run(run_polling(settings))
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        pass
    except Exception:
        print("Telegram polling failed; check bot credentials and connectivity", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
