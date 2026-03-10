"""Search results page scraper for 1688.com."""

import asyncio
import logging
import random
import re

from playwright.async_api import BrowserContext, Page

import config
from auth import is_session_valid
from models import Product, SessionExpiredError

logger = logging.getLogger(__name__)

# Search box selectors on 1688.com (multiple fallbacks)
SEARCH_INPUT_SELECTORS = [
    'input.search-bar-input',
    'input[name="keywords"]',
    'input#alisearch-input',
    'input.alisearch-input',
    'input[placeholder*="搜索"]',
    'input[placeholder*="找货"]',
    'input[type="text"][class*="search"]',
    '.home-header input[type="text"]',
    '#J_InputSuggest',
]

SEARCH_BUTTON_SELECTORS = [
    'button.search-bar-btn',
    'button.alisearch-submit',
    'button[type="submit"]',
    'input[type="submit"]',
    '.search-bar button',
    '.alisearch-btn',
    '[class*="search"] button',
    '[class*="SearchBtn"]',
]

HOMEPAGE_URL = "https://www.1688.com/"


async def _random_delay(min_s: float | None = None, max_s: float | None = None):
    """Wait a random amount of time to appear human."""
    delay = random.uniform(min_s or config.MIN_DELAY, max_s or config.MAX_DELAY)
    await asyncio.sleep(delay)


async def _human_type(page: Page, selector: str, text: str):
    """Type text character by character with random delays, like a human."""
    # Triple-click to select all existing text, then delete
    await page.click(selector, click_count=3)
    await asyncio.sleep(random.uniform(0.1, 0.3))
    await page.keyboard.press("Backspace")
    await asyncio.sleep(random.uniform(0.2, 0.5))

    # Type each character with a random delay
    for char in text:
        await page.keyboard.type(char, delay=random.uniform(50, 150))
    await asyncio.sleep(random.uniform(0.3, 0.8))


async def _scroll_page(page: Page):
    """Scroll down incrementally to trigger lazy-loaded content."""
    total_height = await page.evaluate("document.body.scrollHeight")
    current = 0
    while current < total_height:
        current += config.SCROLL_STEP
        await page.evaluate(f"window.scrollTo(0, {current})")
        await asyncio.sleep(config.SCROLL_DELAY)
    await page.evaluate("window.scrollTo(0, 0)")


def _parse_price(text: str) -> tuple[float | None, float | None]:
    """Parse price text like '1.50 - 3.20' or '¥5.00' into (min, max)."""
    text = text.replace("¥", "").replace("￥", "").replace(",", "").strip()
    numbers = re.findall(r"[\d.]+", text)
    if not numbers:
        return None, None
    prices = [float(n) for n in numbers if n]
    if len(prices) >= 2:
        return min(prices), max(prices)
    if len(prices) == 1:
        return prices[0], prices[0]
    return None, None


def _parse_moq(text: str) -> tuple[int | None, str]:
    """Parse MOQ text like '2件起批' into (quantity, unit)."""
    text = text.strip()
    match = re.search(r"(\d+)\s*([^\d\s]*)", text)
    if match:
        qty = int(match.group(1))
        unit = match.group(2).replace("起批", "").replace("起订", "").strip()
        return qty, unit
    return None, ""


def _extract_offer_id(url: str) -> str:
    """Extract offer ID from a 1688 product URL."""
    match = re.search(r"offer/(\d+)", url)
    return match.group(1) if match else ""


async def _try_select(element, selectors: str) -> str:
    """Try multiple CSS selectors and return the first match's text content."""
    for selector in selectors.split(","):
        selector = selector.strip()
        try:
            el = await element.query_selector(selector)
            if el:
                text = await el.inner_text()
                if text and text.strip():
                    return text.strip()
        except Exception:
            continue
    return ""


async def _try_select_attr(element, selectors: str, attr: str) -> str:
    """Try multiple CSS selectors and return the first match's attribute."""
    for selector in selectors.split(","):
        selector = selector.strip()
        try:
            el = await element.query_selector(selector)
            if el:
                val = await el.get_attribute(attr)
                if val and val.strip():
                    return val.strip()
        except Exception:
            continue
    return ""


async def _try_select_href(element, selectors: str) -> str:
    """Try multiple CSS selectors and return the first match's href."""
    return await _try_select_attr(element, selectors, "href")


async def _find_element(page: Page, selectors: list[str]):
    """Try multiple selectors and return the first matching element."""
    for selector in selectors:
        try:
            el = await page.query_selector(selector)
            if el and await el.is_visible():
                return el, selector
        except Exception:
            continue
    return None, None


async def _get_or_create_page(context: BrowserContext) -> Page:
    """Reuse an existing tab or create one if needed.

    Prefers to reuse a tab that's already on 1688.com.
    """
    pages = context.pages
    # Look for a tab already on 1688.com
    for p in pages:
        if "1688.com" in p.url:
            logger.info("Reusing existing 1688 tab: %s", p.url)
            return p
    # Use the first tab if any
    if pages:
        return pages[0]
    # No tabs — create one (less ideal but fallback)
    return await context.new_page()


async def _navigate_to_homepage(page: Page):
    """Navigate to 1688 homepage if not already there."""
    if "1688.com" in page.url and "login" not in page.url:
        return
    # Use JS navigation instead of page.goto() to avoid CDP detection
    await page.evaluate(f"window.location.href = '{HOMEPAGE_URL}'")
    await page.wait_for_load_state("domcontentloaded", timeout=config.PAGE_TIMEOUT)
    await asyncio.sleep(2)


async def _search_via_searchbox(page: Page, keyword: str) -> bool:
    """Type keyword into the search box and click search. Returns True on success."""
    # Find search input
    input_el, input_selector = await _find_element(page, SEARCH_INPUT_SELECTORS)
    if not input_el:
        logger.warning("Could not find search input on page: %s", page.url)
        return False

    logger.info("Found search input: %s", input_selector)

    # Type keyword like a human
    await _human_type(page, input_selector, keyword)

    # Find and click search button
    btn_el, btn_selector = await _find_element(page, SEARCH_BUTTON_SELECTORS)
    if btn_el:
        logger.info("Clicking search button: %s", btn_selector)
        await btn_el.click()
    else:
        # Fallback: press Enter
        logger.info("No search button found, pressing Enter")
        await page.keyboard.press("Enter")

    # Wait for navigation to search results
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=config.PAGE_TIMEOUT)
    except Exception:
        pass
    await asyncio.sleep(3)
    try:
        await page.wait_for_load_state("networkidle", timeout=config.NETWORK_IDLE_TIMEOUT)
    except Exception:
        logger.debug("networkidle timeout after search, proceeding")

    return True


async def _click_next_page(page: Page) -> bool:
    """Click the next page button. Returns True if clicked successfully."""
    next_el, selector = await _find_element(
        page,
        [s.strip() for s in config.SELECTORS["next_page"].split(",")]
    )
    if not next_el:
        logger.info("No next page button found")
        return False

    logger.info("Clicking next page: %s", selector)
    await next_el.click()

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=config.PAGE_TIMEOUT)
    except Exception:
        pass
    await asyncio.sleep(3)
    try:
        await page.wait_for_load_state("networkidle", timeout=config.NETWORK_IDLE_TIMEOUT)
    except Exception:
        logger.debug("networkidle timeout after pagination, proceeding")

    return True


async def _extract_products_from_page(page: Page) -> list[Product]:
    """Extract product data from the current search results page."""
    products = []

    # ---- Strategy 1: Extract from embedded JSON data ----
    raw_json_products = await page.evaluate(r"""() => {
        const scripts = document.querySelectorAll('script');
        for (const script of scripts) {
            const text = script.textContent || '';

            if (text.includes('__INIT_DATA')) {
                try {
                    const match = text.match(/__INIT_DATA\s*=\s*({[\s\S]*?});?\s*(?:<\/script>|$)/);
                    if (match) {
                        const data = JSON.parse(match[1]);
                        const offers = data?.data?.mainInfo?.offerList
                            || data?.data?.offerList
                            || data?.globalData?.tempModel?.offerList
                            || data?.data?.data?.offerList
                            || [];
                        if (offers.length > 0) return { source: '__INIT_DATA', offers };
                    }
                } catch(e) {}
            }

            if (text.includes('__page_data') || text.includes('pageData')) {
                try {
                    const match = text.match(/(?:__page_data|pageData)\s*=\s*({[\s\S]*?});?\s*(?:<\/script>|$)/);
                    if (match) {
                        const data = JSON.parse(match[1]);
                        const offers = data?.offerList || data?.data?.offerList || [];
                        if (offers.length > 0) return { source: 'pageData', offers };
                    }
                } catch(e) {}
            }
        }

        try {
            const initData = window.__INIT_DATA || window.__APLUS_DATA;
            if (initData) {
                const offers = initData?.data?.mainInfo?.offerList
                    || initData?.data?.offerList
                    || initData?.globalData?.tempModel?.offerList
                    || [];
                if (offers.length > 0) return { source: 'window_global', offers };
            }
        } catch(e) {}

        return null;
    }""")

    if raw_json_products and raw_json_products.get("offers"):
        logger.info(
            "Extracted %d offers from embedded JSON (%s)",
            len(raw_json_products["offers"]),
            raw_json_products["source"],
        )
        for offer in raw_json_products["offers"]:
            try:
                offer_id = str(
                    offer.get("id", "")
                    or offer.get("offerId", "")
                    or offer.get("offer_id", "")
                )
                if not offer_id:
                    continue

                title = (
                    offer.get("subject", "")
                    or offer.get("title", "")
                    or offer.get("offerTitle", "")
                    or ""
                )

                price_str = (
                    offer.get("priceDisplay", "")
                    or offer.get("price", "")
                    or offer.get("tradePrice", "")
                    or ""
                )
                if isinstance(price_str, (int, float)):
                    price_min = price_max = float(price_str)
                else:
                    price_min, price_max = _parse_price(str(price_str))

                moq_str = (
                    offer.get("quantityBegin", "")
                    or offer.get("moq", "")
                    or ""
                )
                if isinstance(moq_str, (int, float)):
                    moq, moq_unit = int(moq_str), "件"
                else:
                    moq, moq_unit = _parse_moq(str(moq_str))

                image_url = (
                    offer.get("image", {}).get("imgUrl", "")
                    if isinstance(offer.get("image"), dict)
                    else offer.get("imageUrl", "")
                    or offer.get("imgUrl", "")
                    or offer.get("image", "")
                    or ""
                )
                if isinstance(image_url, dict):
                    image_url = ""
                if image_url and image_url.startswith("//"):
                    image_url = "https:" + image_url

                url = offer.get("detailUrl", "") or offer.get("offerUrl", "") or ""
                if not url:
                    url = f"https://detail.1688.com/offer/{offer_id}.html"
                elif url.startswith("//"):
                    url = "https:" + url

                company = offer.get("company", {}) if isinstance(offer.get("company"), dict) else {}
                supplier_name = (
                    company.get("name", "")
                    or offer.get("companyName", "")
                    or ""
                )
                supplier_url = company.get("url", "") or ""
                if supplier_url and supplier_url.startswith("//"):
                    supplier_url = "https:" + supplier_url

                supplier_location = company.get("location", "") or ""

                products.append(Product(
                    id=offer_id,
                    title=title,
                    url=url,
                    price_min=price_min,
                    price_max=price_max,
                    moq=moq,
                    moq_unit=moq_unit,
                    supplier_name=supplier_name,
                    supplier_url=supplier_url,
                    supplier_location=supplier_location,
                    image_url=image_url,
                ))
            except Exception as e:
                logger.debug("Error parsing JSON offer: %s", e)
                continue

        if products:
            return products
        logger.info("JSON extraction found offers but couldn't parse them, falling back to DOM")

    # ---- Strategy 2: CSS selector-based extraction ----
    cards = await page.query_selector_all(config.SELECTORS["product_card"])

    if not cards:
        # ---- Strategy 3: JavaScript DOM extraction ----
        logger.info("CSS selectors found no cards, trying JS DOM extraction...")
        raw_products = await page.evaluate(r"""() => {
            const results = [];
            const links = document.querySelectorAll('a[href*="detail.1688.com/offer/"], a[href*="offer/"]');
            const seen = new Set();
            const usedCards = new Set();

            for (const link of links) {
                const href = link.href || '';
                const match = href.match(/offer\/(\d+)/);
                if (!match || seen.has(match[1])) continue;
                seen.add(match[1]);

                let card = link;
                let bestCard = link;
                for (let i = 0; i < 6; i++) {
                    if (!card.parentElement) break;
                    card = card.parentElement;
                    const offerLinks = card.querySelectorAll('a[href*="offer/"]');
                    const uniqueOffers = new Set();
                    offerLinks.forEach(l => {
                        const m = (l.href || '').match(/offer\/(\d+)/);
                        if (m) uniqueOffers.add(m[1]);
                    });
                    if (uniqueOffers.size === 1 && card.offsetHeight > 50) {
                        bestCard = card;
                    }
                    if (uniqueOffers.size > 1) break;
                }

                if (usedCards.has(bestCard)) continue;
                usedCards.add(bestCard);

                let imgSrc = '';
                const imgs = bestCard.querySelectorAll('img');
                for (const img of imgs) {
                    const src = img.src || img.dataset.src || img.getAttribute('data-lazyload-src') || '';
                    if (src && !src.includes('avatar') && !src.includes('icon') && src.length > 20) {
                        imgSrc = src;
                        break;
                    }
                }

                let title = '';
                const titleEl = bestCard.querySelector('[class*="title"], [class*="Title"], h2, h3, h4');
                if (titleEl) {
                    title = titleEl.innerText || '';
                }
                if (!title) {
                    title = link.innerText || link.title || link.getAttribute('title') || '';
                }
                title = title.split('\n')[0].trim();

                let priceText = '';
                const priceEl = bestCard.querySelector('[class*="price"], [class*="Price"]');
                if (priceEl) {
                    priceText = priceEl.innerText || '';
                }

                let moqText = '';
                const moqEl = bestCard.querySelector('[class*="moq"], [class*="MOQ"], [class*="起批"], [class*="quantity"]');
                if (moqEl) {
                    moqText = moqEl.innerText || '';
                }

                const companyLinks = bestCard.querySelectorAll('a[href*="shop"], a[href*="company"], a[class*="company"]');
                let supplierName = '';
                let supplierUrl = '';
                for (const cl of companyLinks) {
                    if (cl.innerText && cl.href !== href) {
                        supplierName = cl.innerText.trim();
                        supplierUrl = cl.href;
                        break;
                    }
                }

                results.push({
                    id: match[1],
                    title: title.substring(0, 200),
                    url: href.startsWith('//') ? 'https:' + href : href,
                    priceText: priceText,
                    moqText: moqText,
                    imgSrc: imgSrc.startsWith('//') ? 'https:' + imgSrc : imgSrc,
                    supplierName: supplierName,
                    supplierUrl: supplierUrl,
                });
            }
            return results;
        }""")

        for raw in (raw_products or []):
            price_min, price_max = _parse_price(raw.get("priceText", ""))
            moq, moq_unit = _parse_moq(raw.get("moqText", ""))
            products.append(Product(
                id=raw.get("id", ""),
                title=raw.get("title", ""),
                url=raw.get("url", ""),
                price_min=price_min,
                price_max=price_max,
                moq=moq,
                moq_unit=moq_unit,
                supplier_name=raw.get("supplierName", ""),
                supplier_url=raw.get("supplierUrl", ""),
                image_url=raw.get("imgSrc", ""),
            ))
        return products

    # Standard extraction from card elements
    for card in cards:
        try:
            link_el = await card.query_selector('a[href*="detail.1688.com/offer/"]')
            if not link_el:
                link_el = await card.query_selector("a[href*='offer']")
            if not link_el:
                continue

            href = await link_el.get_attribute("href") or ""
            offer_id = _extract_offer_id(href)
            if not offer_id:
                continue

            if href.startswith("//"):
                href = "https:" + href

            title = await _try_select(card, config.SELECTORS["title"])
            if not title:
                title = await link_el.inner_text()
                title = title.strip() if title else ""

            price_text = await _try_select(card, config.SELECTORS["price"])
            price_min, price_max = _parse_price(price_text)

            moq_text = await _try_select(card, config.SELECTORS["moq"])
            moq, moq_unit = _parse_moq(moq_text)

            supplier_name = await _try_select(card, config.SELECTORS["supplier"])
            supplier_url = await _try_select_href(card, config.SELECTORS["supplier"])

            image_url = await _try_select_attr(
                card, config.SELECTORS["image"], "src"
            )
            if not image_url:
                image_url = await _try_select_attr(
                    card, config.SELECTORS["image"], "data-src"
                )

            products.append(Product(
                id=offer_id,
                title=title,
                url=href,
                price_min=price_min,
                price_max=price_max,
                moq=moq,
                moq_unit=moq_unit,
                supplier_name=supplier_name,
                supplier_url=supplier_url,
                image_url=image_url,
            ))

        except Exception as e:
            logger.debug("Error extracting card: %s", e)
            continue

    return products


async def scrape_search(
    context: BrowserContext,
    keyword: str,
    max_pages: int | None = None,
) -> list[Product]:
    """Scrape search results by using the search box like a human.

    Instead of navigating directly to search URLs (which triggers anti-bot),
    we type the keyword into the search box and click search.
    """
    max_pages = max_pages or config.MAX_PAGES
    all_products = []

    # Reuse an existing tab instead of creating a new one
    page = await _get_or_create_page(context)

    try:
        # Make sure we're on 1688.com
        await _navigate_to_homepage(page)
        await _random_delay(1, 3)

        # Type keyword into search box and search
        logger.info("Searching for '%s' via search box", keyword)
        if not await _search_via_searchbox(page, keyword):
            logger.error("Could not find search box on page")
            return []

        # Check for anti-bot
        if not await is_session_valid(page):
            raise SessionExpiredError(
                "Session expired or CAPTCHA detected. Re-run with --login."
            )

        logger.info("Search results page: %s", page.url)

        for page_num in range(1, max_pages + 1):
            logger.info("Processing search results page %d", page_num)

            # Save debug screenshot for first page
            if page_num == 1:
                try:
                    screenshot_path = config.DATA_DIR / "debug_search_screenshot.png"
                    await page.screenshot(path=str(screenshot_path), full_page=False)
                    logger.info("Debug screenshot saved to %s", screenshot_path)
                except Exception as e:
                    logger.debug("Could not save screenshot: %s", e)

            # Scroll to load lazy content
            await _scroll_page(page)

            # Extract products
            products = await _extract_products_from_page(page)
            logger.info("Found %d products on page %d", len(products), page_num)
            all_products.extend(products)

            if len(all_products) >= config.MAX_PRODUCTS:
                logger.info("Reached max products limit (%d)", config.MAX_PRODUCTS)
                break

            # Navigate to next page by clicking the button
            if page_num < max_pages:
                await _random_delay()
                if not await _click_next_page(page):
                    break

                # Check for anti-bot after pagination
                if not await is_session_valid(page):
                    raise SessionExpiredError(
                        "Session expired or CAPTCHA detected during pagination."
                    )

    except SessionExpiredError:
        raise
    except Exception as e:
        logger.error("Error during search: %s", e, exc_info=True)

    return all_products[:config.MAX_PRODUCTS]


async def dump_page_html(context: BrowserContext, keyword: str) -> str:
    """Debug helper: dump search page HTML to a file for selector inspection."""
    page = await _get_or_create_page(context)
    await _navigate_to_homepage(page)
    await _random_delay(1, 2)

    if not await _search_via_searchbox(page, keyword):
        logger.error("Could not find search box")

    await _scroll_page(page)

    html = await page.content()
    dump_path = config.DATA_DIR / "debug_search_page.html"
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    dump_path.write_text(html, encoding="utf-8")
    logger.info("Page HTML dumped to %s", dump_path)

    screenshot_path = config.DATA_DIR / "debug_search_screenshot.png"
    await page.screenshot(path=str(screenshot_path), full_page=True)
    logger.info("Debug screenshot saved to %s", screenshot_path)
    logger.info("Actual page URL: %s", page.url)

    return str(dump_path)
