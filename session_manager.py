"""Manages a persistent Playwright browser session for the web server."""

import asyncio
import logging

from playwright.async_api import BrowserContext, async_playwright

from auth import load_session

logger = logging.getLogger(__name__)


class BrowserSessionManager:
    """Manages a single shared Playwright browser instance."""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context: BrowserContext | None = None
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
        """Launch browser and load saved session. Call once on app startup."""
        self._playwright = await async_playwright().start()
        self._browser, self._context = await load_session(
            self._playwright, headless=True
        )
        self._initialized = True
        logger.info("Browser session initialized")

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def get_context(self) -> BrowserContext:
        """Return the shared browser context."""
        if not self._initialized:
            raise RuntimeError("BrowserSessionManager not initialized")
        return self._context

    async def acquire(self):
        """Acquire exclusive access for a scraping operation."""
        await self._lock.acquire()

    def release(self):
        """Release after scraping is done."""
        self._lock.release()

    async def restart(self):
        """Re-launch browser (e.g. after a crash)."""
        logger.info("Restarting browser session...")
        await self.shutdown()
        await self.initialize()

    async def shutdown(self):
        """Close browser and Playwright. Call on app shutdown."""
        self._initialized = False
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        logger.info("Browser session shut down")
