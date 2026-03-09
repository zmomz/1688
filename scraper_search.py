"""Search results page scraper for 1688.com."""

import asyncio
import logging
import random
import re
from urllib.parse import quote

from playwright.async_api import BrowserContext, Page

import config
from auth import is_session_valid
from models import Product, SessionExpiredError

logger = logging.getLogger(__name__)


async def _random_delay():
    """Wait a random amount of time to appear human."""
    delay = random.uniform(config.MIN_DELAY, config.MAX_DELAY)
    await asyncio.sleep(delay)


async def _scroll_page(page: Page):
    """Scroll down incrementally to trigger lazy-loaded content."""
    total_height = await page.evaluate("document.body.scrollHeight")
    current = 0
    while current < total_height:
        current += config.SCROLL_STEP
        await page.evaluate(f"window.scrollTo(0, {current})")
        await asyncio.sleep(config.SCROLL_DELAY)
    # Scroll back to top
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


async def _extract_products_from_page(page: Page) -> list[Product]:
    """Extract product data from the current search results page."""
    products = []

    # Try configured selectors first
    cards = await page.query_selector_all(config.SELECTORS["product_card"])

    # Fallback: find all links to detail pages and work from their parent elements
    if not cards:
        logger.info("Primary selectors found no cards, trying fallback...")
        cards = await page.evaluate("""() => {
            const links = document.querySelectorAll('a[href*="detail.1688.com/offer/"]');
            const parents = new Set();
            links.forEach(link => {
                // Go up a few levels to find the card container
                let el = link.parentElement;
                for (let i = 0; i < 5 && el; i++) {
                    if (el.offsetHeight > 100 && el.offsetWidth > 150) {
                        parents.add(el);
                        break;
                    }
                    el = el.parentElement;
                }
            });
            return Array.from(parents).map(el => el.outerHTML);
        }""")
        if cards and isinstance(cards, list) and isinstance(cards[0], str):
            # We got HTML strings from JS, need to re-query
            # Instead, use a different approach
            cards = []

    if not cards:
        # Last resort: extract data directly via JavaScript
        logger.info("Attempting JavaScript-based extraction...")
        raw_products = await page.evaluate("""() => {
            const results = [];
            const links = document.querySelectorAll('a[href*="detail.1688.com/offer/"]');
            const seen = new Set();

            for (const link of links) {
                const href = link.href || '';
                const match = href.match(/offer\\/(\\d+)/);
                if (!match || seen.has(match[1])) continue;
                seen.add(match[1]);

                // Walk up to find the card container
                let card = link;
                for (let i = 0; i < 8; i++) {
                    if (card.parentElement) card = card.parentElement;
                    if (card.offsetHeight > 100) break;
                }

                // Extract text and images from the card area
                const text = card.innerText || '';
                const imgs = card.querySelectorAll('img');
                let imgSrc = '';
                for (const img of imgs) {
                    const src = img.src || img.dataset.src || '';
                    if (src && !src.includes('avatar') && !src.includes('icon')) {
                        imgSrc = src;
                        break;
                    }
                }

                // Try to find title - usually the link text or nearby heading
                let title = link.innerText || link.title || '';
                if (!title) {
                    const h = card.querySelector('h2, h3, h4, [class*="title"]');
                    if (h) title = h.innerText;
                }

                // Try to find price
                const priceEl = card.querySelector('[class*="price"], [class*="Price"]');
                const priceText = priceEl ? priceEl.innerText : '';

                // Try to find supplier
                const companyLinks = card.querySelectorAll('a[href*="shop"], a[href*="company"], a[class*="company"]');
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
                    title: title.trim().substring(0, 200),
                    url: href,
                    priceText: priceText,
                    imgSrc: imgSrc,
                    supplierName: supplierName,
                    supplierUrl: supplierUrl,
                    fullText: text.substring(0, 500),
                });
            }
            return results;
        }""")

        for raw in (raw_products or []):
            price_min, price_max = _parse_price(raw.get("priceText", ""))
            moq, moq_unit = _parse_moq(raw.get("fullText", ""))
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
            # Get product link and ID
            link_el = await card.query_selector('a[href*="detail.1688.com/offer/"]')
            if not link_el:
                link_el = await card.query_selector("a[href*='offer']")
            if not link_el:
                continue

            href = await link_el.get_attribute("href") or ""
            offer_id = _extract_offer_id(href)
            if not offer_id:
                continue

            # Normalize URL
            if href.startswith("//"):
                href = "https:" + href

            # Title
            title = await _try_select(card, config.SELECTORS["title"])
            if not title:
                title = await link_el.inner_text()
                title = title.strip() if title else ""

            # Price
            price_text = await _try_select(card, config.SELECTORS["price"])
            price_min, price_max = _parse_price(price_text)

            # MOQ
            moq_text = await _try_select(card, config.SELECTORS["moq"])
            moq, moq_unit = _parse_moq(moq_text)

            # Supplier
            supplier_name = await _try_select(card, config.SELECTORS["supplier"])
            supplier_url = await _try_select_href(card, config.SELECTORS["supplier"])

            # Image
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
    """Scrape search results for a keyword across multiple pages."""
    max_pages = max_pages or config.MAX_PAGES
    all_products = []
    page = await context.new_page()

    try:
        for page_num in range(1, max_pages + 1):
            url = f"{config.SEARCH_URL}?keywords={quote(keyword)}&beginPage={page_num}"
            logger.info("Scraping search page %d: %s", page_num, url)

            await page.goto(url, timeout=config.PAGE_TIMEOUT, wait_until="domcontentloaded")
            # Wait for content to render (networkidle is too strict for 1688)
            await asyncio.sleep(3)
            try:
                await page.wait_for_load_state(
                    "networkidle", timeout=config.NETWORK_IDLE_TIMEOUT
                )
            except Exception:
                logger.debug("networkidle timeout, proceeding anyway")

            # Check session validity
            if not await is_session_valid(page):
                raise SessionExpiredError(
                    "Session expired or CAPTCHA detected. Re-run with --login."
                )

            # Scroll to load lazy content
            await _scroll_page(page)

            # Extract products
            products = await _extract_products_from_page(page)
            logger.info("Found %d products on page %d", len(products), page_num)
            all_products.extend(products)

            if len(all_products) >= config.MAX_PRODUCTS:
                logger.info("Reached max products limit (%d)", config.MAX_PRODUCTS)
                break

            # Check for next page
            if page_num < max_pages:
                has_next = await page.query_selector(config.SELECTORS["next_page"])
                if not has_next:
                    logger.info("No more pages available")
                    break
                await _random_delay()

    finally:
        await page.close()

    return all_products[:config.MAX_PRODUCTS]


async def dump_page_html(context: BrowserContext, keyword: str) -> str:
    """Debug helper: dump search page HTML to a file for selector inspection."""
    page = await context.new_page()
    url = f"{config.SEARCH_URL}?keywords={quote(keyword)}&beginPage=1"
    await page.goto(url, timeout=config.PAGE_TIMEOUT, wait_until="domcontentloaded")
    await asyncio.sleep(3)
    try:
        await page.wait_for_load_state("networkidle", timeout=config.NETWORK_IDLE_TIMEOUT)
    except Exception:
        pass
    await _scroll_page(page)

    html = await page.content()
    dump_path = config.DATA_DIR / "debug_search_page.html"
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    dump_path.write_text(html, encoding="utf-8")
    logger.info("Page HTML dumped to %s", dump_path)

    await page.close()
    return str(dump_path)
