"""Настройки приложения: читаются из окружения и .env при старте."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    mc_host: str
    mc_port: int
    check_interval: int
    fail_threshold: int
    db_file: str
    log_level: str = "INFO"


def load_config() -> Config:
    return Config(
        bot_token=os.environ["BOT_TOKEN"],
        mc_host=os.getenv("MC_HOST", "localhost"),
        mc_port=int(os.getenv("MC_PORT", "25565")),
        check_interval=int(os.getenv("CHECK_INTERVAL", "30")),
        fail_threshold=int(os.getenv("FAIL_THRESHOLD", "2")),
        db_file=os.getenv("DB_FILE", "data/bot.db"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
