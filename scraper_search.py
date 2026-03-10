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

    # ---- Strategy 1: Extract from embedded JSON data ----
    # 1688 often embeds structured data in script tags (__INIT_DATA, __APLUS_DATA, etc.)
    raw_json_products = await page.evaluate(r"""() => {
        // Look for __INIT_DATA or similar embedded data structures
        const scripts = document.querySelectorAll('script');
        for (const script of scripts) {
            const text = script.textContent || '';

            // Try __INIT_DATA (common on 1688 search pages)
            if (text.includes('__INIT_DATA')) {
                try {
                    const match = text.match(/__INIT_DATA\s*=\s*({[\s\S]*?});?\s*(?:<\/script>|$)/);
                    if (match) {
                        const data = JSON.parse(match[1]);
                        // Navigate common data paths for search results
                        const offers = data?.data?.mainInfo?.offerList
                            || data?.data?.offerList
                            || data?.globalData?.tempModel?.offerList
                            || data?.data?.data?.offerList
                            || [];
                        if (offers.length > 0) return { source: '__INIT_DATA', offers };
                    }
                } catch(e) {}
            }

            // Try window.__page_data or window.pageData
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

        // Try accessing window globals directly
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

                # Price - try multiple common field names
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

                # MOQ
                moq_str = (
                    offer.get("quantityBegin", "")
                    or offer.get("moq", "")
                    or ""
                )
                if isinstance(moq_str, (int, float)):
                    moq, moq_unit = int(moq_str), "件"
                else:
                    moq, moq_unit = _parse_moq(str(moq_str))

                # Image
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

                # URL
                url = offer.get("detailUrl", "") or offer.get("offerUrl", "") or ""
                if not url:
                    url = f"https://detail.1688.com/offer/{offer_id}.html"
                elif url.startswith("//"):
                    url = "https:" + url

                # Supplier
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
        # ---- Strategy 3: JavaScript DOM extraction (improved) ----
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

                // Walk up to find the card container, but stop early to avoid
                // reaching a shared parent. Look for an element that contains
                // exactly one offer link and has reasonable dimensions.
                let card = link;
                let bestCard = link;
                for (let i = 0; i < 6; i++) {
                    if (!card.parentElement) break;
                    card = card.parentElement;
                    // Count how many offer links are in this container
                    const offerLinks = card.querySelectorAll('a[href*="offer/"]');
                    const uniqueOffers = new Set();
                    offerLinks.forEach(l => {
                        const m = (l.href || '').match(/offer\/(\d+)/);
                        if (m) uniqueOffers.add(m[1]);
                    });
                    // Good card: contains only this offer, has some size
                    if (uniqueOffers.size === 1 && card.offsetHeight > 50) {
                        bestCard = card;
                    }
                    // Stop if we've reached a container with many offers
                    if (uniqueOffers.size > 1) break;
                }

                // Skip if we've already used this card element
                if (usedCards.has(bestCard)) continue;
                usedCards.add(bestCard);

                // Find the closest image to the link (not from the whole card)
                let imgSrc = '';
                const imgs = bestCard.querySelectorAll('img');
                for (const img of imgs) {
                    const src = img.src || img.dataset.src || img.getAttribute('data-lazyload-src') || '';
                    if (src && !src.includes('avatar') && !src.includes('icon') && src.length > 20) {
                        imgSrc = src;
                        break;
                    }
                }

                // Title: prefer the link's own text, then look for title-like elements
                let title = '';
                const titleEl = bestCard.querySelector('[class*="title"], [class*="Title"], h2, h3, h4');
                if (titleEl) {
                    title = titleEl.innerText || '';
                }
                if (!title) {
                    title = link.innerText || link.title || link.getAttribute('title') || '';
                }
                // Clean title: remove price/sales text that might be mixed in
                title = title.split('\n')[0].trim();

                // Price: look for price-specific elements within the card
                let priceText = '';
                const priceEl = bestCard.querySelector('[class*="price"], [class*="Price"]');
                if (priceEl) {
                    priceText = priceEl.innerText || '';
                }

                // MOQ
                let moqText = '';
                const moqEl = bestCard.querySelector('[class*="moq"], [class*="MOQ"], [class*="起批"], [class*="quantity"]');
                if (moqEl) {
                    moqText = moqEl.innerText || '';
                }

                // Supplier
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
            url = f"{config.SEARCH_URL}?keywords={quote(keyword.encode('gbk'), safe='')}&beginPage={page_num}"
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

            # Log the actual URL after any redirects
            actual_url = page.url
            if actual_url != url:
                logger.warning("Page redirected: %s -> %s", url, actual_url)

            # Check session validity
            if not await is_session_valid(page):
                raise SessionExpiredError(
                    "Session expired or CAPTCHA detected. Re-run with --login."
                )

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
    url = f"{config.SEARCH_URL}?keywords={quote(keyword.encode('gbk'), safe='')}&beginPage=1"
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

    # Save screenshot
    screenshot_path = config.DATA_DIR / "debug_search_screenshot.png"
    await page.screenshot(path=str(screenshot_path), full_page=True)
    logger.info("Debug screenshot saved to %s", screenshot_path)

    # Log actual URL to detect redirects
    logger.info("Actual page URL: %s", page.url)

    await page.close()
    return str(dump_path)
