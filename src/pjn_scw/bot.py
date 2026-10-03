from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .client import PjnClient, PjnResult
from .storage import Storage

LOGGER = logging.getLogger("pjn.bot")
ARGENTINA_TZ = timezone(timedelta(hours=-3))
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Falta la variable de entorno {name}")
    return value


def _allowed_chat_ids() -> set[int]:
    raw = _required("TELEGRAM_ALLOWED_CHAT_IDS")
    try:
        return {int(value.strip()) for value in raw.split(",") if value.strip()}
    except ValueError as exc:
        raise RuntimeError("TELEGRAM_ALLOWED_CHAT_IDS debe contener IDs numericos separados por coma") from exc


class TelegramApi:
    def __init__(self, token: str) -> None:
        self.token = token

    async def call(self, method: str, **params):
        return await asyncio.to_thread(self._call_sync, method, params)

    def _call_sync(self, method: str, params: dict):
        encoded = urlencode({key: json.dumps(value) if isinstance(value, (list, dict)) else value for key, value in params.items()}).encode()
        request = Request(TELEGRAM_API.format(token=self.token, method=method), data=encoded)
        try:
            with urlopen(request, timeout=65) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"Telegram API error: {type(exc).__name__}") from exc
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram API rechazo la operacion: {payload.get('description', 'error desconocido')}")
        return payload.get("result")

    async def send_message(self, chat_id: int, text: str) -> None:
        await self.call("sendMessage", chat_id=chat_id, text=text)


class PjnBot:
    def __init__(self) -> None:
        self.allowed_chat_ids = _allowed_chat_ids()
        data_dir = Path(os.environ.get("PJN_DATA_DIR", "/app/data"))
        self.storage = Storage(data_dir / "pjn.sqlite3")
        self.telegram = TelegramApi(_required("TELEGRAM_BOT_TOKEN"))
        self.run_lock = asyncio.Lock()
        self.top_n = int(os.environ.get("PJN_TOP_N", "5"))

    def client(self) -> PjnClient:
        return PjnClient(
            os.environ.get("PJN_BASE_URL", "https://portalpjn.pjn.gov.ar/"),
            _required("PJN_USER"),
            _required("PJN_PASSWORD"),
            top_n=self.top_n,
            headless=os.environ.get("PJN_HEADLESS", "true").lower() == "true",
        )

    async def run_consultation(self, source: str, chat_id: int | None = None) -> None:
        if self.run_lock.locked():
            if chat_id is not None:
                await self.telegram.send_message(chat_id, "Ya hay una consulta PJN en ejecución.")
            return
        async with self.run_lock:
            run_id = self.storage.start_run(source)
            try:
                results = await self.client().collect()
                self.storage.finish_run(run_id, results)
                message = format_results(results)
            except Exception as exc:
                LOGGER.exception("Consulta PJN fallida, run_id=%s", run_id)
                self.storage.finish_run(run_id, [], type(exc).__name__)
                message = "No se pudo completar la consulta PJN. Revisar los logs de Railway."
            if chat_id is not None:
                await self.telegram.send_message(chat_id, message)

    async def polling_loop(self) -> None:
        offset: int | None = None
        await self.telegram.call("deleteWebhook", drop_pending_updates=False)
        while True:
            params = {"timeout": 50, "limit": 20}
            if offset is not None:
                params["offset"] = offset
            try:
                updates = await self.telegram.call("getUpdates", **params)
                for update in updates:
                    offset = int(update["update_id"]) + 1
                    message = update.get("message", {})
                    chat = message.get("chat", {})
                    chat_id = chat.get("id")
                    text = (message.get("text") or "").strip().lower()
                    if not isinstance(chat_id, int) or chat_id not in self.allowed_chat_ids:
                        continue
                    if text in {"/start", "/help"}:
                        await self.telegram.send_message(chat_id, "Bot PJN activo. Usá /consultar para buscar los cinco primeros expedientes.")
                    elif text in {"/consultar", "/consulta"}:
                        await self.telegram.send_message(chat_id, "Consulta PJN iniciada.")
                        asyncio.create_task(self.run_consultation("telegram", chat_id))
            except Exception:
                LOGGER.exception("Error en polling de Telegram")
                await asyncio.sleep(10)

    async def scheduler_loop(self) -> None:
        while True:
            now = datetime.now(ARGENTINA_TZ)
            within_window = 9 <= now.hour < 15 or (now.hour == 15 and now.minute == 0)
            if within_window and now.minute in {0, 30}:
                slot_key = now.strftime("%Y-%m-%dT%H:%M")
                if self.storage.claim_slot(slot_key):
                    LOGGER.info("Ejecutando consulta programada slot=%s", slot_key)
                    await self.run_consultation("schedule")
            await asyncio.sleep(20)

    async def run(self) -> None:
        try:
            await asyncio.gather(self.polling_loop(), self.scheduler_loop())
        finally:
            self.storage.close()


def format_results(results: list[PjnResult]) -> str:
    if not results:
        return "Consulta PJN finalizada: no se encontraron resultados."
    lines = [f"Consulta PJN finalizada. Primeros {len(results)} resultados:"]
    for index, result in enumerate(results, 1):
        lines.extend(
            [
                "",
                f"{index}. {result.expediente}",
                f"Dependencia: {result.dependencia}",
                f"Carátula: {result.caratula}",
                f"Situación: {result.situacion}",
                f"Últ. Act.: {result.ultima_actuacion}",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(PjnBot().run())


if __name__ == "__main__":
    main()
