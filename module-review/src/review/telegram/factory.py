"""Build Fake or Real Telegram bot from bootstrap config."""

from __future__ import annotations

from review.bootstrap import BootstrapConfig, ConfigError
from review.telegram.bot import TelegramBot
from review.telegram.fake import FakeTelegramBot
from review.telegram.real import RealTelegramBot


def build_telegram_bot(config: BootstrapConfig) -> TelegramBot:
    if config.telegram_mode == "real":
        if not config.telegram_bot_token:
            raise ConfigError("REVIEW_TELEGRAM_BOT_TOKEN required for real mode")
        return RealTelegramBot(
            config.telegram_bot_token,
            api_base=config.telegram_api_base,
        )
    return FakeTelegramBot()
