"""Entry point for running the bot WITHOUT the game server (the old way). Prefer `python -m bamboozled`, which runs both
in one process. Kept so the legacy text games and the command snapshot tooling still import from here."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from bamboozled.bot.client import SAFE_MENTIONS, BamboozledBot  # noqa: F401  (re-exported)

load_dotenv()


def _setup_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    # On by default for local runs; the container sets LOG_TO_FILE=0 and logs to stdout only.
    if os.getenv("LOG_TO_FILE", "1").lower() not in ("0", "false", "no", ""):
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / "bamboozled.log", encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", handlers=handlers)


def main():
    _setup_logging()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN not set. Create a .env file with DISCORD_TOKEN=your_token_here")
    BamboozledBot().run(token, log_handler=None)


if __name__ == "__main__":
    main()
