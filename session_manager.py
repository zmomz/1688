"""Manages a Playwright connection to a real Chrome browser via CDP."""

import asyncio
import logging

from playwright.async_api import BrowserContext, async_playwright

from auth import CDP_PORT, connect_to_chrome, launch_chrome_with_debugging

logger = logging.getLogger(__name__)


class BrowserSessionManager:
    """Manages connection to a real Chrome instance via CDP.

    Instead of launching Playwright's Chromium (which gets fingerprinted),
    we connect to the user's real Chrome browser via Chrome DevTools Protocol.
    """

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context: BrowserContext | None = None
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self, port: int = CDP_PORT):
        """Connect to a running Chrome instance. Call once on app startup."""
        self._playwright = await async_playwright().start()
        try:
            self._browser, self._context = await connect_to_chrome(
                self._playwright, port
            )
            self._initialized = True
            logger.info("Browser session initialized via CDP")
        except Exception as e:
            logger.error("Could not connect to Chrome: %s", e)
            logger.error(
                "Make sure Chrome is running with --remote-debugging-port=%d. "
                "Run 'python main.py --login' first.", port
            )
            raise

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def get_context(self) -> BrowserContext:
        """Return the Chrome browser context."""
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
        """Reconnect to Chrome (e.g. after connection lost)."""
        logger.info("Reconnecting to Chrome...")
        await self.shutdown()
        await self.initialize()

    async def shutdown(self):
        """Disconnect from Chrome. Does NOT close Chrome itself."""
        self._initialized = False
        if self._browser:
            try:
                # disconnect() just drops the CDP connection, doesn't kill Chrome
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
        logger.info("Disconnected from Chrome")
