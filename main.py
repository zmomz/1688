"""CLI entry point for 1688.com product scraper."""

import argparse
import asyncio
import logging
import sys

from playwright.async_api import async_playwright

import config
from auth import CDP_PORT, connect_to_chrome, is_session_valid, login_and_connect
from models import SessionExpiredError
from scraper_detail import scrape_details_batch
from scraper_search import dump_page_html, scrape_search
from storage import save_products

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        description="1688.com Product Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --login                       # Launch Chrome and log in
  python main.py "手机壳" --login              # Login then search immediately
  python main.py "手机壳" --pages 3            # Search (Chrome must be running)
  python main.py "手机壳" --pages 2 --details  # Search + detail pages
  python main.py "手机壳" --format csv         # CSV output
  python main.py "手机壳" --dump-html          # Dump page HTML for debugging
        """,
    )
    parser.add_argument("keyword", nargs="?", default=None, help="Search keyword (e.g. Chinese product name)")
    parser.add_argument(
        "--pages", type=int, default=config.MAX_PAGES,
        help=f"Max search result pages to scrape (default: {config.MAX_PAGES})"
    )
    parser.add_argument(
        "--details", action="store_true",
        help="Also scrape individual product detail pages"
    )
    parser.add_argument(
        "--format", choices=["json", "csv"], default=config.OUTPUT_FORMAT,
        help=f"Output format (default: {config.OUTPUT_FORMAT})"
    )
    parser.add_argument(
        "--login", action="store_true",
        help="Launch Chrome with remote debugging for manual login"
    )
    parser.add_argument(
        "--dump-html", action="store_true",
        help="Dump search page HTML to file for debugging selectors"
    )
    args = parser.parse_args()

    if not args.keyword and not args.login:
        parser.error("keyword is required (unless using --login alone)")

    return args


async def run_scraper(args):
    """Main scraping workflow."""
    config.SESSION_DIR.mkdir(parents=True, exist_ok=True)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Handle login — launches Chrome with CDP for manual login
    if args.login:
        await login_and_connect()
        print("Chrome is running. You can now scrape without --login.")
        print("Keep Chrome open in the background.\n")

        if not args.keyword:
            return

    # Connect to Chrome via CDP
    async with async_playwright() as p:
        try:
            browser, context = await connect_to_chrome(p)
        except Exception as e:
            logger.error("Cannot connect to Chrome: %s", e)
            print("\nChrome is not running with remote debugging.")
            print(f"Run: python main.py \"{args.keyword}\" --login")
            print(f"\nOr launch Chrome manually with:")
            print(f"  chrome --remote-debugging-port={CDP_PORT} --user-data-dir=\"{config.SESSION_DIR / 'chrome_profile'}\"")
            sys.exit(1)

        try:
            # Debug mode: dump HTML
            if args.dump_html:
                path = await dump_page_html(context, args.keyword)
                print(f"\nPage HTML saved to: {path}")
                print("Inspect the HTML to update CSS selectors in config.py")
                return

            # Search
            print(f"\nSearching for '{args.keyword}' (up to {args.pages} pages)...")
            products = await scrape_search(context, args.keyword, args.pages)
            print(f"Found {len(products)} products from search results.")

            if not products:
                print("No products found. Try:")
                print("  1. Run with --dump-html to inspect the page")
                print("  2. Re-login with --login if session expired")
                return

            # Detail pages
            if args.details:
                print(f"\nScraping detail pages for {len(products)} products...")
                products = await scrape_details_batch(context, products)
                print("Detail scraping complete.")

            # Save
            filepath = save_products(products, args.keyword, args.format)
            print(f"\nSaved {len(products)} products to: {filepath}")

        except SessionExpiredError as e:
            logger.error(str(e))
            print("\nSession expired! Run again with --login to re-authenticate.")

            if "products" in locals() and products:
                filepath = save_products(products, args.keyword, args.format)
                print(f"Partial data saved to: {filepath}")
            sys.exit(1)

        except Exception as e:
            logger.error("Unexpected error: %s", e, exc_info=True)

            if "products" in locals() and products:
                filepath = save_products(products, args.keyword, args.format)
                print(f"Partial data saved to: {filepath}")
            sys.exit(1)


def main():
    args = parse_args()
    asyncio.run(run_scraper(args))


if __name__ == "__main__":
    main()
