"""
scraper_extended.py — Extended scraper helpers for CrinkleDen
===============================================================
Integrates with abdl_sites.py (verified ABDL-only store registry)
and image_cache.py (local image dedup).

Call patch_scraper() once at startup — it:
  1. Injects extra Shopify/WC profiles into scraper.SITE_PROFILES
  2. Attaches abdl_logger to capture errors/timeouts to .txt files
  3. Patches scraper.get_page to cache product images via image_cache
"""
import re, time, logging
from urllib.parse import urljoin, urlparse

log = logging.getLogger("CDNScraper.Extended")


# ── Keep legacy list for any sites not in abdl_sites.py ───────────────────
# (abdl_sites.py is now the canonical source; these are addons / regression)
EXTRA_SCRAPE_SITES = [
    # ── ABDL specialty (not yet in main PROFILES list) ────────────────────────
    ("Trest",                   "https://trest.com",                            1, "abdl"),
    ("Wearing Clouds",          "https://wearingclouds.com",                    1, "abdl"),
    ("Babykins",                "https://www.babykins.com",                     1, "abdl"),
    ("Little Northwood",        "https://www.littlenorthwood.com",              1, "abdl"),
    ("ABDL Company",            "https://abdlcompany.com",                      1, "abdl"),
    ("Dotty Diaper UK",         "https://www.dottythediaper.co.uk",             1, "abdl"),
    ("Changing Times",          "https://changingtimesdiaperco.com",            1, "abdl"),
    ("Cushies",                 "https://cushiesbottoms.com",                   1, "abdl"),
    ("JaJo Diapers",            "https://jajodiapers.com",                      1, "abdl"),
    ("Tykables EU",             "https://eu.tykables.com",                      1, "abdl"),
    ("My Plastic Pants",        "https://myplasticpants.com",                   1, "abdl"),
    ("ABDLCloth",               "https://abdlcloth.com",                        1, "abdl"),
    ("Lil Kink Boutique",       "https://lilkinkboutique.com",                  1, "abdl"),
    ("AB Universe Japan",       "https://jp.abuniverse.com",                    1, "abdl"),
    ("Diaper Drawer",           "https://diaperdrawer.com",                     1, "abdl"),
    ("CuddleBug",               "https://cuddlebugdiapers.com",                 1, "abdl"),
    ("Printed Diapers",         "https://printeddiapers.com",                   1, "abdl"),
    ("Omy Diapers",             "https://omydiapers.com",                       1, "abdl"),
    ("Crinklz EU",              "https://www.crinklz.com",                      1, "abdl"),
    ("Diaper Stories",          "https://diaperstories.com",                    1, "abdl"),
    ("Seni USA",                "https://seniusa.com",                          1, "abdl"),
    # ── ABDL clothing focused ──────────────────────────────────────────────
    ("Adult Baby Care",         "https://www.adultbabycare.co.uk",              1, "abdl"),
    ("AB Universe Clothing",    "https://abuniverse.com/collections/clothing",  1, "abdl"),
    ("Tykables Clothing",       "https://tykables.com/collections/clothing",    1, "abdl"),
    ("Rearz Clothing",          "https://rearz.ca/product-category/clothing",   1, "abdl"),
    ("LFB Clothing",            "https://www.littleforbig.com/collections/clothing", 1, "abdl"),
    ("PeekABU Clothing",        "https://peekabu.com/collections/clothing",     1, "abdl"),
    ("ABDLFactory Clothing",    "https://abdlfactory.com/collections/clothing", 1, "abdl"),
    # ── Age Regression / Littlespace ──────────────────────────────────────
    ("DDLG World",              "https://ddlgworld.com",                        1, "regression"),
    ("DDLG Playground",         "https://ddlgplayground.com",                   1, "regression"),
    ("Little Dream Shop",       "https://www.littledreamshop.com",              1, "regression"),
    ("Pastel Carousel",         "https://www.pastelcarousel.com",               1, "regression"),
    ("Kitten's Playpen",        "https://www.kittensplaypen.com",               1, "regression"),
    ("CGL Shop",                "https://cglshop.com",                          1, "regression"),
    ("Little Loves Shop",       "https://www.littleloves.shop",                 1, "regression"),
    ("My Little Lux",           "https://www.mylittlelux.com",                  1, "regression"),
    ("Little ABCs",             "https://littleabcs.com",                       1, "regression"),
    ("Littles Closet",          "https://littlescloset.com",                    1, "regression"),
    ("Funshine Express",        "https://funshineexpress.com",                  1, "regression"),
    ("Little Dreamers",         "https://littledreamers.shop",                  1, "regression"),
    ("Kawaii Pen Shop",         "https://www.kawaiipenshop.com",                1, "regression"),
    ("Sugarbunnies",            "https://www.sugarbunnies.com",                 1, "regression"),
    ("Princess Polly",          "https://us.princesspolly.com",                 1, "regression"),
    ("Little Space Studio",     "https://littlespacestudio.com",                1, "regression"),
    ("Agere Community",         "https://agerecommunity.com",                   1, "regression"),
    # ── Medical / Incontinence ──────────────────────────────────────────────
    ("XPMedical",               "https://www.xpmedical.com",                    1, "medical"),
    ("Personally Delivered",    "https://www.personallydelivered.com",          1, "medical"),
    ("Carewell Incontinence",   "https://www.carewell.com/incontinence",        1, "medical"),
    ("Vitality Medical",        "https://www.vitalitymedical.com/briefs.html",  1, "medical"),
    ("Unique Wellness Briefs",  "https://wellnessbriefs.com",                   1, "medical"),
    ("Hartmann Direct",         "https://hartmanndirect.com",                   1, "medical"),
    ("TENA US",                 "https://www.tena.com/en-us/products",          1, "medical"),
    ("Attends Healthcare",      "https://www.attends.com",                      1, "medical"),
    ("Prevail",                 "https://prevailproducts.com",                  1, "medical"),
]


def add_extra_sites():
    """
    Seed sites into the DB from two sources:
      1. abdl_sites.VERIFIED_ABDL_SITES  (canonical verified ABDL list)
      2. EXTRA_SCRAPE_SITES              (age-regression / medical addons)
    Skips existing entries (INSERT OR IGNORE). Returns count added.
    """
    try:
        from database import get_connection, DEFAULT_SCRAPE_INTERVAL
    except ImportError:
        print("[scraper_extended] Cannot import database — run from project root.")
        return 0

    conn = get_connection()
    added = 0

    # 1. Verified ABDL sites from abdl_sites.py
    try:
        from abdl_sites import VERIFIED_ABDL_SITES
        for s in VERIFIED_ABDL_SITES:
            cur = conn.execute("""
                INSERT OR IGNORE INTO scrape_sites
                    (name, url, scrape_enabled, site_type, scrape_interval, notes)
                VALUES (?,?,1,?,?,?)
            """, (s["name"], s["url"], s["site_type"],
                  DEFAULT_SCRAPE_INTERVAL, s.get("notes", "")))
            if cur.rowcount:
                added += 1
    except ImportError:
        pass

    # 2. Legacy extras (regression / medical)
    for name, url, enabled, stype in EXTRA_SCRAPE_SITES:
        cur = conn.execute("""
            INSERT OR IGNORE INTO scrape_sites (name, url, scrape_enabled, site_type, scrape_interval)
            VALUES (?,?,?,?,?)
        """, (name, url, enabled, stype, DEFAULT_SCRAPE_INTERVAL))
        if cur.rowcount:
            added += 1

    conn.commit()
    conn.close()
    return added


# ─────────────────────────────────────────────────────────────────────────────
# Extended SITE_PROFILES — merged into scraper.py's SITE_PROFILES dict
# ─────────────────────────────────────────────────────────────────────────────

EXTRA_SITE_PROFILES = {

    # ── ABDL Shopify stores ──────────────────────────────────────────────────
    "Crinkles UK": {
        "type": "shopify",
        "base": "https://crinkles.co.uk",
        "brand": "Crinkles",
        "brand_type": "abdl",
    },
    "PeekABU Store": {
        "type": "shopify",
        "base": "https://www.peekabu.com",
        "brand": "PeekABU",
        "brand_type": "abdl",
    },
    "InControl Designs": {
        "type": "shopify",
        "base": "https://www.incontroldesigns.com",
        "brand": "InControl",
        "brand_type": "abdl",
    },
    "Wet Set Boutique": {
        "type": "shopify",
        "base": "https://www.wetsetchicago.com",
        "brand": "Wet Set",
        "brand_type": "abdl",
    },
    "ABDL Depot": {
        "type": "shopify",
        "base": "https://www.abdldepot.com",
        "brand": "ABDL Depot",
        "brand_type": "abdl",
    },
    "Diaper Bros Shop": {
        "type": "shopify",
        "base": "https://www.diaperbroshop.com",
        "brand": "Diaper Bros",
        "brand_type": "abdl",
    },

    # ── Age regression / littlespace ─────────────────────────────────────────
    "DDLG World": {
        "type": "shopify",
        "base": "https://ddlgworld.com",
        "brand": "DDLG World",
        "brand_type": "regression",
    },
    "CGL Shop": {
        "type": "shopify",
        "base": "https://cglshop.com",
        "brand": "CGL Shop",
        "brand_type": "regression",
    },
    "Pastel Carousel": {
        "type": "shopify",
        "base": "https://www.pastelcarousel.com",
        "brand": "Pastel Carousel",
        "brand_type": "regression",
    },
    "Kitten's Playpen": {
        "type": "shopify",
        "base": "https://www.kittensplaypen.com",
        "brand": "Kitten's Playpen",
        "brand_type": "regression",
    },
    "Kawaii Goods": {
        "type": "html",
        "base": "https://www.kawaiigoodsn.com",
        "brand": "Kawaii Goods",
        "brand_type": "regression",
        "list_selector":   ".product-item, .grid__item",
        "name_selector":   ".product-item__title, h2.product-card__title",
        "price_selector":  ".price__regular, .price-item--regular",
        "image_selector":  "img.product-featured-img, img.lazyload",
        "url_selector":    "a.product-item__title-link, a.product-card__link",
        "next_selector":   "a[rel='next'], .pagination__next",
    },
    "Blippo Kawaii": {
        "type": "html",
        "base": "https://www.blippo.com",
        "brand": "Blippo",
        "brand_type": "regression",
        "list_path":       "/collections/all",
        "list_selector":   ".product-wrap, .product",
        "name_selector":   ".product-name, h2",
        "price_selector":  ".price, .product-price",
        "image_selector":  "img.product-img, img",
        "url_selector":    "a.product-link, a",
        "next_selector":   "a.next, .pagination-next",
    },

    # ── Medical HTML stores ──────────────────────────────────────────────────
    "XPMedical": {
        "type": "html",
        "base": "https://www.xpmedical.com",
        "brand": "XPMedical",
        "brand_type": "medical",
        "list_path":      "/incontinence/",
        "list_selector":  ".product-item, li.item",
        "name_selector":  ".product-name a, h2.product-name",
        "price_selector": ".price, .special-price .price",
        "image_selector": "img.product-image-photo, img",
        "url_selector":   "a.product-item-link, a",
        "next_selector":  "a.next, li.next a",
    },
    "Carewell Incontinence": {
        "type": "html",
        "base": "https://www.carewell.com",
        "brand_type": "medical",
        "list_path":      "/incontinence/",
        "list_selector":  "[data-testid='product-card'], .product-card",
        "name_selector":  "h3, .product-name",
        "price_selector": "[data-testid='price'], .price",
        "image_selector": "img",
        "url_selector":   "a[href*='/products/']",
        "next_selector":  "a[rel='next'], [data-testid='next-page']",
    },

    # ── Specialty WooCommerce ────────────────────────────────────────────────
    "ABDLand UK": {
        "type": "woocommerce",
        "base": "https://abdland.co.uk",
        "brand": "ABDLand",
        "brand_type": "abdl",
    },
    "Nappies R Us": {
        "type": "woocommerce",
        "base": "https://www.nappiesrus.co.uk",
        "brand": "Nappies R Us",
        "brand_type": "abdl",
    },
    "Cuddlz UK": {
        "type": "woocommerce",
        "base": "https://www.cuddlz.com",
        "brand": "Cuddlz",
        "brand_type": "abdl",
    },
    "My Little Lux": {
        "type": "woocommerce",
        "base": "https://www.mylittlelux.com",
        "brand": "My Little Lux",
        "brand_type": "regression",
    },
    "ABDL Factory EU": {
        "type": "woocommerce",
        "base": "https://abdlfactory.eu",
        "brand": "ABDL Factory",
        "brand_type": "abdl",
    },
    "Vitality Medical": {
        "type": "html",
        "base": "https://www.vitalitymedical.com",
        "brand_type": "medical",
        "list_path":      "/briefs.html",
        "list_selector":  "li.product-item, .product-item",
        "name_selector":  "a.product-item-link, .product-name",
        "price_selector": ".price",
        "image_selector": "img.product-image-photo",
        "url_selector":   "a.product-item-link",
        "next_selector":  "a.next",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Generic HTML scraper for sites that use a non-Shopify / non-WC pattern
# ─────────────────────────────────────────────────────────────────────────────

def scrape_html_extra(site_row, profile, tb, pcb=None, force=False):
    """
    Generic HTML product list scraper driven by CSS selectors in `profile`.
    Called by scraper.py's dispatch when site_type == 'html' and an extra profile exists.

    profile keys:
        base, list_path, list_selector, name_selector, price_selector,
        image_selector, url_selector, next_selector, brand, brand_type
    """
    from database import upsert_product, add_scrape_log, should_scrape_site
    from datetime import datetime
    import re as _re

    try:
        from abdl_logger import log_error, log_timeout
        _LOG = True
    except ImportError:
        _LOG = False
        def log_error(*a, **kw): pass
        def log_timeout(*a, **kw): pass

    if not force and not should_scrape_site(site_row):
        return {"site": site_row["name"], "status": "SKIPPED", "found": 0}

    base        = profile.get("base", "").rstrip("/")
    list_path   = profile.get("list_path", "/collections/all")
    list_sel    = profile.get("list_selector", ".product")
    name_sel    = profile.get("name_selector", "h2")
    price_sel   = profile.get("price_selector", ".price")
    img_sel     = profile.get("image_selector", "img")
    url_sel     = profile.get("url_selector", "a")
    next_sel    = profile.get("next_selector", "a[rel='next']")
    brand_name  = profile.get("brand", site_row["name"])
    brand_type  = profile.get("brand_type", site_row.get("site_type", "abdl"))
    site_name   = site_row["name"]

    started  = datetime.now().isoformat()
    found    = added = errors = 0

    def _price_usd(text):
        if not text: return None
        m = _re.search(r"(\d[\d,]*\.?\d*)", text.replace(",", ""))
        if m:
            v = float(m.group(1))
            t = text.lower()
            if "£" in t: v *= 1.27
            elif "€" in t: v *= 1.09
            elif "c$" in t or "ca$" in t: v *= 0.74
            return round(v, 2) if v > 0 else None
        return None

    current_url = f"{base}{list_path}"
    pages_scraped = 0

    while current_url and pages_scraped < 20:
        soup = tb.get_page(current_url)
        if not soup:
            # get_page already logged the timeout/error via the patched method;
            # but if abdl_logger patch wasn't applied (scraper not imported),
            # log it directly here.
            if _LOG:
                log_error(site_name, current_url, "Page returned None — possible timeout or block")
            if pcb: pcb(f"  ✗ Could not load {current_url}")
            add_scrape_log(site_row["id"], started, datetime.now().isoformat(),
                           found, added, "ERROR", f"Page failed: {current_url}")
            break
        pages_scraped += 1
        items = soup.select(list_sel)
        if pcb: pcb(f"  [{site_name}] page {pages_scraped}: {len(items)} items at {current_url}")

        for item in items:
            try:
                name_el  = item.select_one(name_sel)
                price_el = item.select_one(price_sel)
                img_el   = item.select_one(img_sel)
                url_el   = item.select_one(url_sel)

                name = (name_el.get_text(strip=True) if name_el else "").strip()
                if not name: continue

                price = _price_usd(price_el.get_text(strip=True) if price_el else "")
                img_url = ""
                if img_el:
                    img_url = (img_el.get("src") or img_el.get("data-src")
                               or img_el.get("data-lazy-src") or "")
                    if img_url.startswith("//"):
                        img_url = "https:" + img_url
                    elif img_url.startswith("/"):
                        img_url = base + img_url

                prod_url = ""
                if url_el:
                    href = url_el.get("href", "")
                    prod_url = href if href.startswith("http") else urljoin(base, href)

                # Category inference — try scraper first, fall back to local helper
                try:
                    from scraper import _infer_cat_name as _cat_fn
                except ImportError:
                    _cat_fn = infer_regression_category
                cat_name = _cat_fn(name, "")

                data = {
                    "name":          name,
                    "brand_name":    brand_name,
                    "category_name": cat_name,
                    "url":           prod_url,
                    "image_url":     img_url,
                    "price":         price,
                    "price_usd":     price,
                    "in_stock":      1,
                    "brand_type":    brand_type,
                    "source_site":   site_name,
                }
                upsert_product(data)
                found += 1
                added += 1
            except Exception as e:
                errors += 1
                log.warning(f"  item parse error: {e}")
                log_error(site_name, current_url,
                          f"Item parse error ({errors} so far): {e}", exc=e,
                          context=f"selector={list_sel}")

        # Next page
        next_el = soup.select_one(next_sel)
        if next_el:
            next_href = next_el.get("href", "")
            if next_href:
                current_url = next_href if next_href.startswith("http") else urljoin(base, next_href)
            else:
                break
        else:
            break

        time.sleep(0.5)

    finished = datetime.now().isoformat()
    final_status = "SUCCESS" if errors == 0 else "PARTIAL"
    add_scrape_log(site_row["id"], started, finished, found, added, final_status)
    if pcb: pcb(f"  ✓ {site_name}: {found} products  ({errors} parse errors)")
    return {"site": site_name, "status": final_status, "found": found}


# ─────────────────────────────────────────────────────────────────────────────
# Monkey-patch helper — injects profiles into the running scraper module
# ─────────────────────────────────────────────────────────────────────────────

def patch_scraper():
    """
    Inject all extra site profiles into scraper.SITE_PROFILES at runtime,
    attach the debug logger, and patch upsert_product to cache images.
    """
    # 1. Inject profiles from EXTRA_SITE_PROFILES (legacy) + abdl_sites.EXTRA_PROFILES
    combined = dict(EXTRA_SITE_PROFILES)
    try:
        from abdl_sites import EXTRA_PROFILES as _abdl_profiles
        combined.update(_abdl_profiles)
    except ImportError:
        pass

    try:
        import scraper
        if hasattr(scraper, "SITE_PROFILES"):
            scraper.SITE_PROFILES.update(combined)
            print(f"[scraper_extended] Injected {len(combined)} site profiles.")
        else:
            print("[scraper_extended] scraper.SITE_PROFILES not found — skipping inject.")
    except ImportError:
        print("[scraper_extended] scraper.py not importable — patch skipped.")

    # 2. Attach debug logger (errors.txt / timeouts.txt)
    try:
        from abdl_logger import _patch_scraper_module
        _patch_scraper_module()
    except ImportError:
        print("[scraper_extended] abdl_logger.py not found — file logging disabled.")

    # 3. Patch upsert_product to queue image caching
    _patch_upsert_for_cache()


def _patch_upsert_for_cache():
    """
    Wrap database.upsert_product so that whenever a product with an image_url
    is inserted/updated, the image URL is queued into the local cache.
    Only runs if image_cache.py is present.  Safe to call multiple times.
    """
    try:
        import database as _db
        from image_cache import get_cache as _get_cache
    except ImportError:
        return

    if getattr(_db, "_abdl_cache_patched", False):
        return

    _orig_upsert = _db.upsert_product

    def _patched_upsert(data, *args, **kwargs):
        result = _orig_upsert(data, *args, **kwargs)
        img_url = data.get("image_url") or data.get("image") or ""
        if img_url and img_url.startswith("http"):
            try:
                cache = _get_cache()
                if cache and not cache.is_cached(img_url):
                    # Fire-and-forget background download
                    from concurrent.futures import ThreadPoolExecutor
                    _executor = getattr(_patched_upsert, "_pool", None)
                    if _executor is None:
                        _executor = ThreadPoolExecutor(max_workers=4)
                        _patched_upsert._pool = _executor
                    _executor.submit(cache.fetch, img_url)
            except Exception:
                pass
        return result

    _db.upsert_product = _patched_upsert
    _db._abdl_cache_patched = True
    print("[scraper_extended] upsert_product patched — images will be cached locally.")


# ─────────────────────────────────────────────────────────────────────────────
# Age-regression specific category helpers
# ─────────────────────────────────────────────────────────────────────────────

def infer_regression_category(name, desc=""):
    """Extend _infer_cat_name for age-regression specific items."""
    t = (name + " " + desc).lower()
    # Age regression specifics
    if any(w in t for w in ["sippy cup", "sip cup", "training cup"]): return "Bottles"
    if any(w in t for w in ["pacifier", "paci", "dummy", "soother"]): return "Pacifiers"
    if any(w in t for w in ["stuffed", "plush", "plushie", "stuffy", "teddy", "stuffie"]): return "Plushies / Stuffies"
    if any(w in t for w in ["coloring", "colouring", "crayons", "sticker", "stickers", "activity set"]): return "Activity / Art"
    if any(w in t for w in ["bib", "bibs"]): return "Accessories"
    if any(w in t for w in ["onesie", "romper", "bodysuit", "footed pyjama", "footed pajama"]): return "Onesies / Rompers"
    if any(w in t for w in ["diaper bag", "changing bag", "changing mat"]): return "Accessories"
    if any(w in t for w in ["rattle", "teether", "toy"]): return "Activity / Art"
    if any(w in t for w in ["blanket", "swaddle", "muslin"]): return "Bedding / Mattress"
    if any(w in t for w in ["powder", "lotion", "cream", "wipe", "wipes"]): return "Skincare / Medical"
    # Fall back to main infer
    try:
        from scraper import _infer_cat_name
        return _infer_cat_name(name, desc)
    except ImportError:
        return "Accessories"


# ─────────────────────────────────────────────────────────────────────────────
# CLI quick-add
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    try:
        from database import init_db
        init_db()
    except Exception as e:
        print(f"DB init: {e}")
    n = add_extra_sites()
    print(f"Added {n} extra scrape site(s).")
    patch_scraper()
