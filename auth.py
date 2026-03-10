"""Session management: connect to real Chrome via CDP."""

import asyncio
import logging
import subprocess
import sys
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

import config

logger = logging.getLogger(__name__)

# Default CDP port for remote debugging
CDP_PORT = 9222
CDP_URL = f"http://localhost:{CDP_PORT}"


def get_chrome_path() -> str:
    """Find Chrome executable on the system."""
    if sys.platform == "win32":
        import winreg
        # Try common Windows Chrome locations
        paths = [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
        ]
        for p in paths:
            if p.exists():
                return str(p)
        # Try registry
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe")
            path, _ = winreg.QueryValueEx(key, "")
            winreg.CloseKey(key)
            return path
        except Exception:
            pass
    elif sys.platform == "darwin":
        path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if Path(path).exists():
            return path
    else:
        # Linux
        for name in ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]:
            import shutil
            p = shutil.which(name)
            if p:
                return p

    raise FileNotFoundError(
        "Chrome not found. Please install Google Chrome or set the path manually."
    )


def launch_chrome_with_debugging(port: int = CDP_PORT, user_data_dir: str | None = None) -> subprocess.Popen:
    """Launch Chrome with remote debugging enabled.

    Uses a dedicated user data directory so it doesn't conflict with
    the user's normal Chrome instance.
    """
    chrome_path = get_chrome_path()

    if user_data_dir is None:
        user_data_dir = str(config.SESSION_DIR / "chrome_profile")

    Path(user_data_dir).mkdir(parents=True, exist_ok=True)

    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        config.LOGIN_URL,
    ]

    logger.info("Launching Chrome with remote debugging on port %d", port)
    process = subprocess.Popen(args)
    return process


async def connect_to_chrome(playwright, port: int = CDP_PORT) -> tuple[Browser, BrowserContext]:
    """Connect to a running Chrome instance via CDP."""
    cdp_url = f"http://localhost:{port}"
    logger.info("Connecting to Chrome at %s", cdp_url)

    browser = await playwright.chromium.connect_over_cdp(cdp_url)
    # Use the first (default) browser context — this is the real Chrome context
    # with all cookies, localStorage, and the real fingerprint
    contexts = browser.contexts
    if not contexts:
        raise RuntimeError(
            "No browser context found. Make sure Chrome is open with at least one tab."
        )
    context = contexts[0]
    logger.info("Connected to Chrome (contexts: %d, pages: %d)",
                len(contexts), len(context.pages))
    return browser, context


async def login_and_connect(port: int = CDP_PORT) -> None:
    """Launch Chrome for manual login, wait for user, then verify connection.

    This replaces the old login_and_save_session approach. Instead of saving
    storage_state (which loses the browser fingerprint), we keep Chrome running
    and connect to it via CDP.
    """
    process = launch_chrome_with_debugging(port)

    print("\n" + "=" * 60)
    print("  Chrome has been launched with remote debugging.")
    print("  Please log in to 1688.com in the Chrome window.")
    print("  After logging in, press ENTER here to continue...")
    print("=" * 60 + "\n")

    await asyncio.get_event_loop().run_in_executor(None, input)

    # Verify we can connect
    async with async_playwright() as p:
        try:
            browser, context = await connect_to_chrome(p, port)
            pages = context.pages
            logger.info("Connection verified. %d tabs open.", len(pages))
            # Don't close — keep Chrome running for scraping
            # browser.close() would just disconnect, not kill Chrome
        except Exception as e:
            logger.error("Failed to connect to Chrome: %s", e)
            process.terminate()
            raise

    return process


async def is_session_valid(page: Page) -> bool:
    """Check if the current page indicates a valid session (no CAPTCHA/login redirect)."""
    url = page.url.lower()

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

    try:
        content = await page.content()
        if '"action":"captcha"' in content or "baxia-dialog" in content:
            logger.warning("Session invalid: CAPTCHA detected in page content")
            return False
    except Exception:
        pass

    return True
