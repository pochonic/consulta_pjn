from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .bot import TelegramApi, _allowed_chat_ids, _required, format_results
from .client import PjnClient
from .storage import Storage

LOGGER = logging.getLogger("pjn.cron")
ARGENTINA_TZ = timezone(timedelta(hours=-3))


def in_schedule_window(now: datetime) -> bool:
    """Acepta 09:00..14:30 y 15:00 hora argentina."""
    return 9 <= now.hour < 15 or (now.hour == 15 and now.minute == 0)


async def run_once() -> None:
    now = datetime.now(ARGENTINA_TZ)
    if not in_schedule_window(now):
        LOGGER.info("Fuera de ventana PJN; no se ejecuta consulta hora=%s", now.strftime("%H:%M"))
        return

    data_dir = Path(os.environ.get("PJN_DATA_DIR", "/app/data"))
    storage = Storage(data_dir / "pjn.sqlite3")
    telegram = TelegramApi(_required("TELEGRAM_BOT_TOKEN"))
    run_id = storage.start_run("railway-cron")
    try:
        client = PjnClient(
            os.environ.get("PJN_BASE_URL", "https://portalpjn.pjn.gov.ar/"),
            _required("PJN_USER"),
            _required("PJN_PASSWORD"),
            top_n=int(os.environ.get("PJN_TOP_N", "5")),
            headless=os.environ.get("PJN_HEADLESS", "true").lower() == "true",
        )
        results = await client.collect()
        storage.finish_run(run_id, results)
        text = format_results(results)
    except Exception as exc:
        LOGGER.exception("Consulta PJN fallida, run_id=%s", run_id)
        storage.finish_run(run_id, [], type(exc).__name__)
        text = "No se pudo completar la consulta PJN. Revisar los logs de Railway."
    finally:
        storage.close()

    for chat_id in _allowed_chat_ids():
        await telegram.send_message(chat_id, text)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
