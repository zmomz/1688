"""Product detail page scraper for 1688.com."""

import asyncio
import logging
import random
import re

from playwright.async_api import BrowserContext, Page

import config
from auth import is_session_valid
from models import Product, SessionExpiredError

logger = logging.getLogger(__name__)


async def _random_delay():
    delay = random.uniform(config.MIN_DELAY, config.MAX_DELAY)
    await asyncio.sleep(delay)


async def scrape_detail(page: Page, product: Product) -> Product:
    """Navigate to a product detail page and enrich the Product with full data."""
    logger.info("Scraping detail: %s", product.url)

    await page.goto(product.url, timeout=config.PAGE_TIMEOUT, wait_until="domcontentloaded")
    await asyncio.sleep(3)
    try:
        await page.wait_for_load_state(
            "networkidle", timeout=config.NETWORK_IDLE_TIMEOUT
        )
    except Exception:
        logger.debug("networkidle timeout on detail page, proceeding anyway")

    if not await is_session_valid(page):
        raise SessionExpiredError(
            "Session expired or CAPTCHA detected on detail page."
        )

    # --- Title (update if we get a better one) ---
    try:
        title = await page.evaluate("""() => {
            const selectors = ['h1[class*="title"]', '.title-text', '.d-title', 'h1'];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.innerText.trim()) return el.innerText.trim();
            }
            return '';
        }""")
        if title:
            product.title = title
    except Exception:
        pass

    # --- Images ---
    try:
        images = await page.evaluate("""() => {
            const imgs = new Set();
            const selectors = [
                '.detail-gallery-turn img',
                '#dt-tab img',
                '.tab-trigger img',
                '[class*="gallery"] img',
                '[class*="slider"] img',
                '.vertical-img img',
                '.main-image img',
            ];
            for (const sel of selectors) {
                document.querySelectorAll(sel).forEach(img => {
                    const src = img.src || img.dataset.src || img.dataset.lazySrc || '';
                    if (src && !src.includes('avatar') && !src.includes('icon')
                        && !src.includes('1x1') && src.startsWith('http')) {
                        // Get full-size image by removing size parameters
                        let fullSrc = src.replace(/_\\d+x\\d+\\.\\w+$/, '');
                        imgs.add(fullSrc);
                    }
                });
            }
            return Array.from(imgs);
        }""")
        if images:
            product.image_urls = images
            if not product.image_url and images:
                product.image_url = images[0]
    except Exception as e:
        logger.debug("Error extracting images: %s", e)

    # --- Price tiers ---
    try:
        price_data = await page.evaluate("""() => {
            const prices = [];
            // Look for ladder/tiered pricing
            const priceItems = document.querySelectorAll(
                '.ladder-price-item, [class*="price-item"], [class*="PriceItem"]'
            );
            for (const item of priceItems) {
                const text = item.innerText || '';
                const nums = text.match(/[\\d.]+/g);
                if (nums) prices.push(...nums.map(Number));
            }
            // Fallback: single price
            if (prices.length === 0) {
                const priceEl = document.querySelector(
                    '.price-text, [class*="price"] .value, [class*="Price"] .value'
                );
                if (priceEl) {
                    const nums = priceEl.innerText.match(/[\\d.]+/g);
                    if (nums) prices.push(...nums.map(Number));
                }
            }
            return prices.filter(p => p > 0 && p < 1000000);
        }""")
        if price_data:
            product.price_min = min(price_data)
            product.price_max = max(price_data)
    except Exception as e:
        logger.debug("Error extracting price: %s", e)

    # --- Specifications ---
    try:
        specs = await page.evaluate("""() => {
            const specs = {};
            // Try attribute tables
            const rows = document.querySelectorAll(
                '#mod-detail-attributes tr, .attributes-list tr, ' +
                '[class*="attribute"] tr, .obj-content tr'
            );
            for (const row of rows) {
                const cells = row.querySelectorAll('td, th');
                if (cells.length >= 2) {
                    const key = cells[0].innerText.trim().replace(/[:：]$/, '');
                    const val = cells[1].innerText.trim();
                    if (key && val) specs[key] = val;
                }
            }
            // Try dl/dt/dd format
            if (Object.keys(specs).length === 0) {
                const dts = document.querySelectorAll(
                    '[class*="attribute"] dt, .obj-content dt'
                );
                const dds = document.querySelectorAll(
                    '[class*="attribute"] dd, .obj-content dd'
                );
                for (let i = 0; i < Math.min(dts.length, dds.length); i++) {
                    const key = dts[i].innerText.trim().replace(/[:：]$/, '');
                    const val = dds[i].innerText.trim();
                    if (key && val) specs[key] = val;
                }
            }
            return specs;
        }""")
        if specs:
            product.specs = specs
    except Exception as e:
        logger.debug("Error extracting specs: %s", e)

    # --- Supplier info ---
    try:
        supplier = await page.evaluate("""() => {
            const result = {name: '', url: '', location: '', years: null};
            // Supplier name
            const nameSelectors = [
                '.company-name a', '[class*="companyName"] a',
                '.shop-name a', '[class*="shopName"] a'
            ];
            for (const sel of nameSelectors) {
                const el = document.querySelector(sel);
                if (el && el.innerText.trim()) {
                    result.name = el.innerText.trim();
                    result.url = el.href || '';
                    break;
                }
            }
            // Location
            const locSelectors = [
                '.company-location', '[class*="location"]',
                '.region', '[class*="region"]'
            ];
            for (const sel of locSelectors) {
                const el = document.querySelector(sel);
                if (el && el.innerText.trim()) {
                    result.location = el.innerText.trim();
                    break;
                }
            }
            // Years on platform
            const yearEl = document.querySelector('[class*="year"], [class*="Year"]');
            if (yearEl) {
                const match = yearEl.innerText.match(/(\\d+)/);
                if (match) result.years = parseInt(match[1]);
            }
            return result;
        }""")
        if supplier:
            if supplier.get("name"):
                product.supplier_name = supplier["name"]
            if supplier.get("url"):
                product.supplier_url = supplier["url"]
            if supplier.get("location"):
                product.supplier_location = supplier["location"]
            if supplier.get("years"):
                product.supplier_years = supplier["years"]
    except Exception as e:
        logger.debug("Error extracting supplier: %s", e)

    # --- Sales count ---
    try:
        sales = await page.evaluate("""() => {
            const selectors = [
                '[class*="sale"], [class*="Sale"]',
                '[class*="trade"], [class*="Trade"]',
                '[class*="volume"], [class*="Volume"]',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.innerText.trim()) return el.innerText.trim();
            }
            return '';
        }""")
        if sales:
            product.sales_count = sales
    except Exception as e:
        logger.debug("Error extracting sales: %s", e)

    # --- MOQ (if not already set) ---
    if not product.moq:
        try:
            moq_text = await page.evaluate("""() => {
                const selectors = [
                    '[class*="moq"], [class*="MOQ"]',
                    '[class*="起批"], [class*="起订"]',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.trim()) return el.innerText.trim();
                }
                // Search in all text
                const body = document.body.innerText;
                const match = body.match(/(\\d+)\\s*件?起[批订]/);
                if (match) return match[0];
                return '';
            }""")
            if moq_text:
                match = re.search(r"(\d+)", moq_text)
                if match:
                    product.moq = int(match.group(1))
        except Exception:
            pass

    return product


async def scrape_details_batch(
    context: BrowserContext,
    products: list[Product],
) -> list[Product]:
    """Scrape detail pages for a batch of products sequentially."""
    page = await context.new_page()
    enriched = []

    try:
        for i, product in enumerate(products):
            logger.info(
                "Scraping detail %d/%d: %s",
                i + 1, len(products), product.title[:50]
            )
            try:
                enriched_product = await scrape_detail(page, product)
                enriched.append(enriched_product)
            except SessionExpiredError:
                raise
            except Exception as e:
                logger.warning(
                    "Failed to scrape detail for %s: %s", product.id, e
                )
                enriched.append(product)  # Keep partial data

            if i < len(products) - 1:
                await _random_delay()
    finally:
        await page.close()

    return enriched
