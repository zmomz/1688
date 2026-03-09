"""Session management: login, save, load, and validation."""

import asyncio
import logging
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright_stealth import Stealth

import config

logger = logging.getLogger(__name__)


async def login_and_save_session(session_path: Path | None = None) -> None:
    """Open a headed browser for manual login, then save the session."""
    session_path = session_path or config.SESSION_FILE
    session_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport=config.VIEWPORT,
            locale=config.LOCALE,
            timezone_id=config.TIMEZONE,
        )
        stealth = Stealth()
        await stealth.apply_stealth_async(context)
        page = await context.new_page()

        await page.goto(config.LOGIN_URL, timeout=config.PAGE_TIMEOUT)
        print("\n" + "=" * 60)
        print("  Please log in to 1688.com in the browser window.")
        print("  After logging in, press ENTER here to continue...")
        print("=" * 60 + "\n")

        await asyncio.get_event_loop().run_in_executor(None, input)

        await context.storage_state(path=str(session_path))
        logger.info("Session saved to %s", session_path)

        await browser.close()


async def load_session(
    playwright, session_path: Path | None = None, headless: bool | None = None
) -> tuple[Browser, BrowserContext]:
    """Load a saved session and return browser + context with stealth."""
    session_path = session_path or config.SESSION_FILE
    if headless is None:
        headless = config.HEADLESS

    if not session_path.exists():
        raise FileNotFoundError(
            f"No session file found at {session_path}. Run with --login first."
        )

    browser = await playwright.chromium.launch(headless=headless)
    context = await browser.new_context(
        storage_state=str(session_path),
        viewport=config.VIEWPORT,
        locale=config.LOCALE,
        timezone_id=config.TIMEZONE,
    )
    stealth = Stealth()
    await stealth.apply_stealth_async(context)
    logger.info("Session loaded from %s", session_path)
    return browser, context


async def is_session_valid(page: Page) -> bool:
    """Check if the current page indicates a valid session (no CAPTCHA/login redirect)."""
    url = page.url.lower()

    # Check for CAPTCHA or security redirect
    captcha_indicators = [
        "captcha",
        "punish",
        "x5secdata",
        "login.1688.com",
        "login.taobao.com",
        "sec.1688.com",
    ]

    for indicator in captcha_indicators:
        if indicator in url:
            logger.warning("Session invalid: detected '%s' in URL", indicator)
            return False

    # Check page content for CAPTCHA markers
    try:
        content = await page.content()
        if '"action":"captcha"' in content or "baxia-dialog" in content:
            logger.warning("Session invalid: CAPTCHA detected in page content")
            return False
    except Exception:
        pass

    return True
