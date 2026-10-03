from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

LOGGER = logging.getLogger("pjn.client")


@dataclass(frozen=True)
class PjnResult:
    expediente: str
    dependencia: str
    caratula: str
    situacion: str
    ultima_actuacion: str

    def as_dict(self) -> dict[str, str]:
        return {
            "expediente": self.expediente,
            "dependencia": self.dependencia,
            "caratula": self.caratula,
            "situacion": self.situacion,
            "ultima_actuacion": self.ultima_actuacion,
        }


DEFAULT_SELECTORS = {
    "username": "#username, input[name='username'], input[name='usuario']",
    "password": "#password, input[name='password']",
    "login_button": "#kc-login, button[type='submit'], input[type='submit']",
    "consultas_link": "a:has-text('Consultas'), button:has-text('Consultas')",
    "order_select": "select[id$=':order_by_form:camara'], select[name$='order_by_form:camara']",
    "order_button": "a:has-text('Ordenar'), button:has-text('Ordenar')",
    "result_table": "table[id$=':dataTable']",
}


class PjnClient:
    """Login, Consultas, ordenar por fecha y extraer cinco columnas."""

    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        *,
        top_n: int = 5,
        selectors: dict[str, str] | None = None,
        timeout_ms: int = 30_000,
        headless: bool = True,
        slow_mo_ms: int = 0,
    ) -> None:
        self.base_url = base_url
        self.user = user
        self.password = password
        self.top_n = top_n
        self.selectors = {**DEFAULT_SELECTORS, **(selectors or {})}
        self.timeout_ms = timeout_ms
        self.headless = headless
        self.slow_mo_ms = slow_mo_ms

    async def collect(self) -> list[PjnResult]:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=self.headless,
                slow_mo=self.slow_mo_ms,
            )
            try:
                context = await browser.new_context()
                context.set_default_timeout(self.timeout_ms)
                page = await context.new_page()
                page.set_default_navigation_timeout(self.timeout_ms)
                await self._login(page)
                consultas = await self._open_consultas(context, page)
                await self._order_by_date(consultas)
                return await self._extract_first_results(consultas)
            finally:
                await browser.close()

    async def _login(self, page: Page) -> None:
        await page.goto(self.base_url, wait_until="domcontentloaded")
        await page.locator(self.selectors["username"]).first.fill(self.user)
        await page.locator(self.selectors["password"]).first.fill(self.password)
        await page.locator(self.selectors["login_button"]).first.click()
        await page.wait_for_load_state("domcontentloaded")

    async def _open_consultas(self, context: BrowserContext, page: Page) -> Page:
        link = page.locator(self.selectors["consultas_link"]).first
        try:
            async with context.expect_page(timeout=self.timeout_ms) as page_info:
                await link.click()
            consultas = await page_info.value
            await consultas.wait_for_load_state("domcontentloaded")
            return consultas
        except PlaywrightTimeoutError:
            await page.wait_for_load_state("domcontentloaded")
            return page

    async def _order_by_date(self, page: Page) -> None:
        try:
            await page.locator(self.selectors["order_select"]).first.select_option(label="FECHA")
            await page.locator(self.selectors["order_button"]).first.click()
            await page.wait_for_load_state("domcontentloaded")
        except PlaywrightTimeoutError:
            select_info = await page.locator("select").evaluate_all(
                "elements => elements.map(e => ({id: e.id, name: e.name, "
                "options: Array.from(e.options).map(o => o.textContent.trim()).slice(0, 30)}))"
            )
            LOGGER.error(
                "No se pudo ordenar por fecha; selects disponibles=%s",
                json.dumps(select_info, ensure_ascii=False),
            )
            raise

    async def _extract_first_results(self, page: Page) -> list[PjnResult]:
        table = page.locator(self.selectors["result_table"]).filter(
            has_text=re.compile(r"Expediente.*Dependencia.*Carátula.*Situación", re.S),
        ).first
        results: list[PjnResult] = []
        for row in await table.locator("tr").all():
            cells = [text.strip() for text in await row.locator("td").all_text_contents()]
            if len(cells) < 5 or cells[0].casefold() == "expediente":
                continue
            results.append(PjnResult(*cells[:5]))
            if len(results) == self.top_n:
                break
        return results


def parse_rows(rows: list[list[str]], top_n: int = 5) -> list[PjnResult]:
    """Parsea filas de la tabla sin abrir el portal, para pruebas."""
    results: list[PjnResult] = []
    for cells in rows:
        values = [value.strip() for value in cells]
        if len(values) < 5 or values[0].casefold() == "expediente":
            continue
        results.append(PjnResult(*values[:5]))
        if len(results) == top_n:
            break
    return results
