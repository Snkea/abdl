"""
ABDL Catalog System — scraper.py

Playwright multi-thread fix:
  - playwright sync_api is greenlet-based and CANNOT be shared across threads.
  - Each worker thread creates its own sync_playwright + browser + context + page,
    uses it, then tears it all down. No shared browser globals.
  - MAX_CONCURRENT = 4  (up to 4 browser processes running simultaneously)
"""
import re, time, random, json, logging, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    SCRAPE_AVAILABLE   = True
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    SCRAPE_AVAILABLE = PLAYWRIGHT_AVAILABLE = False

from database import (get_scrape_sites, upsert_product, add_scrape_log,
                      should_scrape_site, next_scrape_time as _next_scrape_time)

log = logging.getLogger("ABDLScraper")

MAX_CONCURRENT = 4   # simultaneous browser processes

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

FX = {"usd":1.00,"$":1.00,"cad":0.74,"c$":0.74,"ca$":0.74,
      "eur":1.09,"€":1.09,"gbp":1.27,"£":1.27,"aud":0.66,"a$":0.66}

_CHROMIUM_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars","--no-sandbox","--disable-dev-shm-usage",
    "--window-size=1366,768","--disable-extensions",
    "--no-first-run","--no-default-browser-check",
]

_STEALTH_JS = """
    Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
    Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});
    Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
    Object.defineProperty(navigator,'platform',{get:()=>'Win32'});
    window.chrome={runtime:{},loadTimes:()=>{},csi:()=>{}};
"""


# ── Per-thread browser session ────────────────────────────────────────────────
# Each worker thread creates its own playwright+browser+context+page.
# Nothing is shared between threads.

class _ThreadBrowser:
    """
    Context manager that owns a complete playwright stack for one thread.
    Usage:
        with _ThreadBrowser() as tb:
            soup = tb.get_page("https://example.com")
    """
    def __init__(self):
        self._pw   = None
        self._brow = None
        self._ctx  = None
        self.page  = None

    def __enter__(self):
        self._pw   = sync_playwright().start()
        self._brow = self._pw.chromium.launch(headless=True, args=_CHROMIUM_ARGS)
        ua = random.choice(_USER_AGENTS)
        self._ctx = self._brow.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=ua, locale="en-US", timezone_id="America/Chicago",
            extra_http_headers={
                "Accept-Language":   "en-US,en;q=0.9",
                "Accept":            "text/html,application/xhtml+xml,*/*;q=0.8",
                "Sec-CH-UA":         '"Chromium";v="124","Google Chrome";v="124","Not-A.Brand";v="99"',
                "Sec-CH-UA-Mobile":  "?0",
                "Sec-CH-UA-Platform": '"Windows"',
                "DNT": "1",
            },
        )
        self._ctx.add_init_script(_STEALTH_JS)
        self.page = self._ctx.new_page()
        return self

    def __exit__(self, *_):
        for obj, method in [(self.page,"close"),(self._ctx,"close"),
                            (self._brow,"close"),(self._pw,"stop")]:
            if obj:
                try:
                    getattr(obj, method)()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass  # EPIPE / broken pipe — Playwright pipe already gone, safe to ignore
                except Exception:
                    pass
        self.page = self._brow = self._ctx = self._pw = None

    def get_page(self, url, wait="domcontentloaded", retries=2):
        for attempt in range(retries + 1):
            try:
                self.page.goto(url, wait_until=wait, timeout=30_000)
                time.sleep(random.uniform(0.2, 0.6))
                return BeautifulSoup(self.page.content(), "html.parser")
            except PWTimeout:
                log.warning(f"Timeout [{attempt+1}] {url}")
                if attempt == retries: return None
                time.sleep(2)
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                log.warning(f"EPIPE/pipe error fetching {url} — browser closed: {e}")
                return None
            except Exception as e:
                log.warning(f"GET {url}: {e}"); return None

    def fetch_json(self, url):
        try:
            return self.page.evaluate(f"""
                async () => {{
                    try {{
                        const r = await fetch({json.dumps(url)}, {{
                            credentials:'include',
                            headers:{{'Accept':'application/json','X-Requested-With':'XMLHttpRequest'}}
                        }});
                        if (!r.ok) return null;
                        return await r.json();
                    }} catch(e) {{ return null; }}
                }}
            """)
        except Exception as e:
            log.warning(f"fetch_json {url}: {e}"); return None


# ── Utilities ─────────────────────────────────────────────────────────────────

def _delay(lo=0.8, hi=2.2):
    time.sleep(random.uniform(lo, hi))


def _usd(text, src="usd"):
    if not text: return None
    t = str(text).strip(); sym = src.lower()
    for s in ["c$","ca$","a$","£","€","$"]:
        if s in t.lower(): sym = s; break
    m = re.search(r"(\d[\d,]*\.?\d*)", t.replace(",",""))
    if not m: return None
    try: v = float(m.group(1))
    except: return None
    r = round(v * FX.get(sym, 1.0), 2)
    return r if r > 0 else None


def _infer_cat_name(name, desc):
    t = (name + " " + desc).lower()
    if any(w in t for w in ["onesie","romper","bodysuit","snap crotch"]): return "Onesies / Rompers"
    if any(w in t for w in ["pacifier","dummy","soother","paci"]):        return "Pacifiers"
    if any(w in t for w in ["bottle","sippy"]):                           return "Bottles"
    if any(w in t for w in ["booster","insert","stuffer","doubler"]):     return "Booster Pads"
    if any(w in t for w in ["underpad","chux","bed pad","chair pad"]):    return "Underpads / Chux"
    if any(w in t for w in ["pull-up","pullup","training pant"]):         return "Pull-Ups / Training"
    if any(w in t for w in ["swim","aqua"]):                              return "Swim Diapers"
    if any(w in t for w in ["mattress","waterproof cover"]):              return "Bedding / Mattress"
    if any(w in t for w in ["wipe","barrier cream","rash cream","powder"]):return "Skincare / Medical"
    if any(w in t for w in ["plastic pant","diaper cover"]):              return "Clothing"
    if any(w in t for w in ["diaper","nappy","brief","pant","incontinence"]):
        if any(w in t for w in ["print","design","cute","crinkle","abdl","baby"]): return "ABDL Diapers"
        return "Diapers"
    return "Accessories"


def _abs_ml(text):
    if not text: return None
    m = re.search(r"(\d[\d,]+)\s*ml", text, re.I)
    if m: return int(m.group(1).replace(",",""))
    m = re.search(r"(\d+\.?\d*)\s*fl\.?\s*oz", text, re.I)
    if m: return int(float(m.group(1)) * 29.574)
    return None


# ── Scraping strategies (all accept tb: _ThreadBrowser) ──────────────────────

def _probe(tb, base):
    roots = [base.rstrip("/")]
    for s in ["/collections/all","/collections/diapers","/shop","/en/shop","/en"]:
        r = roots[0]
        cand = r if not r.endswith(s) else r[:-len(s)]
        if cand not in roots: roots.append(cand)
    for root in roots:
        data = tb.fetch_json(f"{root}/products.json?limit=1")
        if data and isinstance(data.get("products"), list):
            return root
    return None


def _shopify(tb, root, brand_name, site, pcb=None, cur="usd", btype="abdl", disc=0, samp=0):
    products = []; page_n = 1
    while True:
        data = tb.fetch_json(f"{root}/products.json?limit=250&page={page_n}")
        if not data: break
        items = data.get("products", [])
        if not items: break
        for item in items:
            title = item.get("title","")
            desc_raw = item.get("body_html","") or ""
            desc  = BeautifulSoup(desc_raw,"html.parser").get_text(" ",strip=True)
            tags  = ", ".join(item.get("tags",[]))
            purl  = f"{root}/products/{item.get('handle','')}"
            img   = (item.get("images") or [{}])[0].get("src","")
            price = None
            if item.get("variants"):
                price = _usd(str(item["variants"][0].get("price","")), cur)
            products.append({"name":title,"brand_name":brand_name,
                "category_name":_infer_cat_name(title,desc),"description":desc[:1200],
                "url":purl,"image_url":img,"price_usd":price,"price":price,"currency":"USD",
                "absorbency_ml":_abs_ml(desc),"tags":tags,"source_site":site,
                "brand_type":btype,"discreet_shipping":disc,"free_sample":samp,"in_stock":1})
            if pcb: pcb(f"  Found: {title[:55]}")
        page_n += 1; _delay(0.6, 1.5)
    return products


def _html(tb, site_url, brand_name, site, sels, pcb=None, cur="usd", btype="abdl", disc=0, samp=0):
    products = []
    soup = tb.get_page(site_url, wait="networkidle")
    if not soup: return products
    lf = sels.get("link_filter","/product")
    links = []
    for a in soup.select(sels.get("product_link","a")):
        href = a.get("href","")
        if href and lf in href:
            full = urljoin(site_url, href)
            if full not in links: links.append(full)
    for purl in links[:60]:
        _delay()
        ps = tb.get_page(purl)
        if not ps: continue
        title = ""
        for s in [sels.get("title"),"h1.product_title","h1.entry-title","h1"]:
            if s:
                el = ps.select_one(s)
                if el: title = el.get_text(strip=True); break
        desc = ""
        for s in [sels.get("description"),".woocommerce-product-details__short-description",
                  ".product-description",".description"]:
            if s:
                el = ps.select_one(s)
                if el: desc = el.get_text(" ",strip=True)[:1200]; break
        price = None
        for s in [sels.get("price"),"p.price",".price",".woocommerce-Price-amount"]:
            if s:
                el = ps.select_one(s)
                if el:
                    price = _usd(el.get_text(), cur)
                    if price: break
        img = ""
        for s in [sels.get("image"),".woocommerce-product-gallery__image img",
                  ".product-image img","img.wp-post-image"]:
            if s:
                el = ps.select_one(s)
                if el:
                    src = el.get("src") or el.get("data-src","")
                    if src: img = urljoin(purl, src); break
        if title:
            products.append({"name":title,"brand_name":brand_name,
                "category_name":_infer_cat_name(title,desc),"description":desc,
                "url":purl,"image_url":img,"price_usd":price,"price":price,"currency":"USD",
                "source_site":site,"brand_type":btype,"discreet_shipping":disc,
                "free_sample":samp,"in_stock":1})
            if pcb: pcb(f"  Found: {title[:55]}")
    return products


def _crinklz(tb, brand_name, site, pcb=None):
    products = []; base = "https://www.crinklz.com"; seen = set()
    soup = None
    for u in [f"{base}/shop",f"{base}/en/shop",base]:
        soup = tb.get_page(u, "networkidle")
        if soup: break
    if not soup: return products
    for a in soup.select("a[href]"):
        href = a.get("href","")
        if not href: continue
        full = urljoin(base, href)
        if full in seen or "?" in full: continue
        if base in full and any(k in full.lower() for k in ["product","diaper","windel"]):
            seen.add(full); _delay()
            ps = tb.get_page(full)
            if not ps: continue
            h1 = ps.select_one("h1")
            title = h1.get_text(strip=True) if h1 else ""
            if not title or len(title) < 3: continue
            de   = ps.select_one(".product-description,.description,.entry-content,main p")
            desc = de.get_text(" ",strip=True)[:1000] if de else ""
            pe   = ps.select_one(".price,.amount,[class*='price']")
            price = _usd(pe.get_text(),"eur") if pe else None
            ie   = ps.select_one("img.product-image,.product img,main img")
            img  = urljoin(full, ie.get("src","")) if ie else ""
            products.append({"name":title,"brand_name":brand_name,
                "category_name":_infer_cat_name(title,desc),"description":desc,
                "url":full,"image_url":img,"price_usd":price,"price":price,"currency":"USD",
                "source_site":site,"brand_type":"abdl","discreet_shipping":0,
                "free_sample":1,"in_stock":1})
            if pcb: pcb(f"  Found: {title[:55]}")
            if len(products) >= 30: break
    return products



# ── Walmart scraper ───────────────────────────────────────────────────────────
def _walmart(tb, search_url, site, pcb=None):
    """
    Scrape Walmart baby/incontinence category pages.
    Uses Walmart's internal __NEXT_DATA__ JSON blob embedded in the page.
    Falls back to HTML card parsing if JSON not found.
    """
    products = []; seen = set()
    base = "https://www.walmart.com"

    def _extract_page(soup, url):
        found = []
        # Try __NEXT_DATA__ JSON first (most reliable)
        nd = soup.find("script", {"id": "__NEXT_DATA__"})
        if nd:
            try:
                data = json.loads(nd.string or "")
                items = (data.get("props",{}).get("pageProps",{})
                             .get("initialData",{}).get("searchResult",{})
                             .get("itemStacks",[{}])[0].get("items",[]))
                if not items:
                    # category page structure
                    items = (data.get("props",{}).get("pageProps",{})
                                 .get("initialData",{}).get("contentLayout",{})
                                 .get("modules",[{}])[0].get("configs",{})
                                 .get("products",[]))
                for it in items:
                    name  = it.get("name") or it.get("title","")
                    price = None
                    pc = it.get("price") or it.get("priceInfo",{})
                    if isinstance(pc, dict):
                        price = _usd(str(pc.get("currentPrice") or pc.get("minPrice") or ""), "usd")
                    elif pc:
                        price = _usd(str(pc), "usd")
                    pid   = it.get("usItemId") or it.get("id","")
                    purl  = f"{base}/ip/{pid}" if pid else url
                    img   = it.get("image","") or it.get("imageInfo",{}).get("thumbnailUrl","")
                    desc  = it.get("shortDescription","") or it.get("description","")
                    if isinstance(desc, list): desc = " ".join(desc)
                    brand = it.get("brand","") or it.get("sellerName","")
                    if name and name not in seen:
                        seen.add(name)
                        found.append({"name": name, "brand_name": brand,
                            "category_name": _infer_cat_name(name, str(desc)),
                            "description": str(desc)[:800], "url": purl,
                            "image_url": img, "price_usd": price, "price": price,
                            "currency": "USD", "source_site": site,
                            "brand_type": "medical", "discreet_shipping": 1,
                            "free_sample": 0, "in_stock": 1})
                        if pcb and name: pcb(f"  Found: {name[:55]}")
            except Exception as e:
                log.debug(f"Walmart JSON parse: {e}")

        # HTML card fallback
        if not found:
            for card in soup.select('[data-item-id],[data-product-id],[class*="product-title"]')[:60]:
                name_el = card.select_one('[class*="product-title"] span, [class*="name"] span, h2, h3')
                if not name_el: continue
                name = name_el.get_text(strip=True)
                if not name or name in seen: continue
                price_el = card.select_one('[class*="price"] span, [itemprop="price"]')
                price = _usd(price_el.get_text(), "usd") if price_el else None
                a_el = card.select_one('a[href*="/ip/"]')
                purl = urljoin(base, a_el["href"]) if a_el and a_el.get("href") else url
                img_el = card.select_one("img[src]")
                img = img_el.get("src","") if img_el else ""
                seen.add(name)
                found.append({"name": name, "brand_name": "",
                    "category_name": _infer_cat_name(name,""),
                    "description": "", "url": purl, "image_url": img,
                    "price_usd": price, "price": price, "currency": "USD",
                    "source_site": site, "brand_type": "medical",
                    "discreet_shipping": 1, "free_sample": 0, "in_stock": 1})
                if pcb: pcb(f"  Found: {name[:55]}")
        return found

    # Scrape up to 4 pages
    for page in range(1, 5):
        sep = "&" if "?" in search_url else "?"
        url = f"{search_url}{sep}page={page}&affinityOverride=default" if page > 1 else search_url
        soup = tb.get_page(url, "networkidle")
        if not soup: break
        batch = _extract_page(soup, url)
        if not batch: break
        products.extend(batch)
        _delay(1.5, 3.0)
        if len(products) >= 120: break

    return products


# ── Target scraper ────────────────────────────────────────────────────────────
def _target(tb, search_url, site, pcb=None):
    """
    Scrape Target category / search pages.
    Target embeds product data in <script type="application/ld+json"> and
    __TGT_DATA__ / window.__PRELOADED_QUERIES__ blobs.
    """
    products = []; seen = set()
    base = "https://www.target.com"

    def _parse_target(soup, url):
        found = []
        # Try ld+json product listings
        for sc in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(sc.string or "")
                if not isinstance(data, list): data = [data]
                for item in data:
                    if item.get("@type") not in ("Product","ItemList"): continue
                    if item.get("@type") == "ItemList":
                        for el in item.get("itemListElement",[]):
                            item2 = el.get("item",{})
                            name = item2.get("name","")
                            if not name or name in seen: continue
                            seen.add(name)
                            offer = (item2.get("offers") or [{}])
                            if isinstance(offer, dict): offer = [offer]
                            price = _usd(str(offer[0].get("price","") if offer else ""), "usd")
                            purl  = item2.get("url", url)
                            img   = (item2.get("image") or [""])[0] if isinstance(item2.get("image"), list) else item2.get("image","")
                            brand = item2.get("brand",{}).get("name","") if isinstance(item2.get("brand"),dict) else ""
                            found.append({"name":name,"brand_name":brand,
                                "category_name":_infer_cat_name(name,""),
                                "description":"","url":purl,"image_url":img,
                                "price_usd":price,"price":price,"currency":"USD",
                                "source_site":site,"brand_type":"medical",
                                "discreet_shipping":1,"free_sample":0,"in_stock":1})
                            if pcb: pcb(f"  Found: {name[:55]}")
            except Exception: pass

        # HTML card fallback
        if not found:
            for card in soup.select('[data-test="product-details"],[class*="ProductCardImage"]')[:60]:
                name_el = card.select_one('[data-test*="product-title"] a, a[href*="/p/"]')
                if not name_el: continue
                name = name_el.get_text(strip=True) or name_el.get("aria-label","")
                if not name or name in seen: continue
                seen.add(name)
                price_el = card.select_one('[data-test*="current-price"] span,[class*="Price"]')
                price = _usd(price_el.get_text(), "usd") if price_el else None
                href  = name_el.get("href","")
                purl  = urljoin(base, href) if href else url
                img_el = card.select_one("img[src]")
                img   = img_el.get("src","") if img_el else ""
                found.append({"name":name,"brand_name":"",
                    "category_name":_infer_cat_name(name,""),
                    "description":"","url":purl,"image_url":img,
                    "price_usd":price,"price":price,"currency":"USD",
                    "source_site":site,"brand_type":"medical",
                    "discreet_shipping":1,"free_sample":0,"in_stock":1})
                if pcb: pcb(f"  Found: {name[:55]}")
        return found

    for page in range(1, 5):
        sep = "&" if "?" in search_url else "?"
        url = f"{search_url}{sep}Nao={24*(page-1)}" if page > 1 else search_url
        soup = tb.get_page(url, "networkidle")
        if not soup: break
        batch = _parse_target(soup, url)
        if not batch: break
        products.extend(batch)
        _delay(1.5, 3.0)
        if len(products) >= 120: break

    return products


# ── Amazon scraper ────────────────────────────────────────────────────────────
def _amazon(tb, search_url, site, pcb=None):
    """
    Scrape Amazon search/category pages.
    Amazon embeds product data in div[data-asin] cards.
    """
    products = []; seen = set()
    base = "https://www.amazon.com"

    for page in range(1, 4):
        sep = "&" if "?" in search_url else "?"
        url = f"{search_url}{sep}page={page}" if page > 1 else search_url
        soup = tb.get_page(url, "networkidle")
        if not soup: break
        found_this = 0
        for card in soup.select("[data-asin][data-asin!='']")[:50]:
            asin  = card.get("data-asin","")
            name_el = card.select_one("h2 a span, h2 span, [class*='title'] span")
            if not name_el: continue
            name = name_el.get_text(strip=True)
            if not name or name in seen: continue
            seen.add(name); found_this += 1
            price_el = card.select_one(".a-price .a-offscreen, .a-color-price")
            price = _usd(price_el.get_text(), "usd") if price_el else None
            a_el = card.select_one("h2 a[href], a.a-link-normal[href*='/dp/']")
            href = a_el.get("href","") if a_el else ""
            purl = urljoin(base, href) if href else f"{base}/dp/{asin}"
            img_el = card.select_one("img.s-image,[class*='product-image'] img")
            img  = img_el.get("src","") if img_el else ""
            products.append({"name":name,"brand_name":"",
                "category_name":_infer_cat_name(name,""),
                "description":"","url":purl,"image_url":img,
                "price_usd":price,"price":price,"currency":"USD",
                "source_site":site,"brand_type":"medical",
                "discreet_shipping":1,"free_sample":0,"in_stock":1})
            if pcb: pcb(f"  Found: {name[:55]}")
        if not found_this: break
        _delay(2.0, 4.0)
        if len(products) >= 100: break

    return products


# ── CVS / Walgreens / Rite Aid scraper ───────────────────────────────────────
def _pharmacy(tb, search_url, site, pcb=None):
    """
    Generic pharmacy chain scraper (CVS, Walgreens, Rite Aid, Dollar General).
    Handles both JSON-LD and HTML card patterns.
    """
    products = []; seen = set()
    base = "/".join(search_url.split("/")[:3])

    def _parse(soup, url):
        found = []
        # JSON-LD
        for sc in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(sc.string or "")
                if not isinstance(data, list): data = [data]
                for item in data:
                    if item.get("@type") != "Product": continue
                    name = item.get("name","")
                    if not name or name in seen: continue
                    seen.add(name)
                    offers = item.get("offers",{})
                    if isinstance(offers, list): offers = offers[0] if offers else {}
                    price = _usd(str(offers.get("price","")), "usd")
                    purl  = item.get("url", url)
                    img   = item.get("image","")
                    if isinstance(img, list): img = img[0] if img else ""
                    brand = item.get("brand",{})
                    brand = brand.get("name","") if isinstance(brand, dict) else str(brand)
                    found.append({"name":name,"brand_name":brand,
                        "category_name":_infer_cat_name(name,""),
                        "description":item.get("description","")[:600],
                        "url":purl,"image_url":img,
                        "price_usd":price,"price":price,"currency":"USD",
                        "source_site":site,"brand_type":"medical",
                        "discreet_shipping":1,"free_sample":0,"in_stock":1})
                    if pcb: pcb(f"  Found: {name[:55]}")
            except Exception: pass

        # HTML cards
        if not found:
            selectors = [
                ("a[class*='product'][href]", "span,h2,h3", ".price,.product-price,[class*='price']"),
                (".product-list-item a, .product-card a", "h2,h3,[class*='name']", "[class*='price']"),
                ("[data-product-name],[data-item-name]", None, "[data-price],[class*='price']"),
            ]
            for link_sel, name_sel, price_sel in selectors:
                cards = soup.select(link_sel)[:60]
                if not cards: continue
                for card in cards:
                    if name_sel:
                        name_el = card.select_one(name_sel) or card
                        name = name_el.get_text(strip=True)
                    else:
                        name = card.get("data-product-name") or card.get("data-item-name","")
                    if not name or name in seen: continue
                    seen.add(name)
                    price_el = card.select_one(price_sel) if price_sel else None
                    price = _usd(price_el.get_text(), "usd") if price_el else None
                    href = card.get("href","") if card.name == "a" else (card.select_one("a") or card).get("href","")
                    purl = urljoin(base, href) if href else url
                    img_el = card.select_one("img[src]")
                    img = img_el.get("src","") if img_el else ""
                    found.append({"name":name,"brand_name":"",
                        "category_name":_infer_cat_name(name,""),
                        "description":"","url":purl,"image_url":img,
                        "price_usd":price,"price":price,"currency":"USD",
                        "source_site":site,"brand_type":"medical",
                        "discreet_shipping":1,"free_sample":0,"in_stock":1})
                    if pcb: pcb(f"  Found: {name[:55]}")
                if found: break
        return found

    for page in range(1, 4):
        sep = "&" if "?" in search_url else "?"
        url = f"{search_url}{sep}page={page}" if page > 1 else search_url
        soup = tb.get_page(url, "networkidle")
        if not soup: break
        batch = _parse(soup, url)
        if not batch: break
        products.extend(batch)
        _delay(1.5, 3.0)
        if len(products) >= 100: break

    return products


# ── Dollar General scraper ────────────────────────────────────────────────────
def _dollar_general(tb, search_url, site, pcb=None):
    """DG embeds products in window.DGM_PRODUCT_DATA or standard JSON-LD."""
    products = []; seen = set()

    for page in range(1, 4):
        sep = "&" if "?" in search_url else "?"
        url = f"{search_url}{sep}start={24*(page-1)}" if page > 1 else search_url
        soup = tb.get_page(url, "networkidle")
        if not soup: break

        # Try DG's embedded JSON
        for sc in soup.find_all("script"):
            txt = sc.string or ""
            if "DGM_PRODUCT_DATA" in txt or '"@type":"Product"' in txt:
                # extract JSON array
                m = re.search(r'\[{"@type".*?"Product".*?\]', txt, re.DOTALL)
                if m:
                    try:
                        items = json.loads(m.group())
                        for it in items:
                            name = it.get("name","")
                            if not name or name in seen: continue
                            seen.add(name)
                            offer = it.get("offers",{})
                            if isinstance(offer,list): offer = offer[0] if offer else {}
                            price = _usd(str(offer.get("price","")), "usd")
                            products.append({"name":name,"brand_name":it.get("brand",{}).get("name","") if isinstance(it.get("brand"),dict) else "",
                                "category_name":_infer_cat_name(name,""),
                                "description":it.get("description","")[:500],
                                "url":it.get("url",url),"image_url":it.get("image",""),
                                "price_usd":price,"price":price,"currency":"USD",
                                "source_site":site,"brand_type":"medical",
                                "discreet_shipping":1,"free_sample":0,"in_stock":1})
                            if pcb: pcb(f"  Found: {name[:55]}")
                    except Exception: pass

        # HTML fallback
        if not [p for p in products if p["source_site"]==site]:
            for card in soup.select("li.product-tile,div.product-tile,[class*='ProductTile']")[:60]:
                name_el = card.select_one("[class*='product-name'],[class*='title'],h2,h3")
                if not name_el: continue
                name = name_el.get_text(strip=True)
                if not name or name in seen: continue
                seen.add(name)
                price_el = card.select_one("[class*='price'],[class*='Price']")
                price = _usd(price_el.get_text(),"usd") if price_el else None
                a_el = card.select_one("a[href]")
                purl = urljoin("https://www.dollargeneral.com", a_el["href"]) if a_el else url
                img_el = card.select_one("img[src]")
                img = img_el.get("src","") if img_el else ""
                products.append({"name":name,"brand_name":"",
                    "category_name":_infer_cat_name(name,""),
                    "description":"","url":purl,"image_url":img,
                    "price_usd":price,"price":price,"currency":"USD",
                    "source_site":site,"brand_type":"medical",
                    "discreet_shipping":1,"free_sample":0,"in_stock":1})
                if pcb: pcb(f"  Found: {name[:55]}")
        _delay(1.5, 3.0)
        if len(products) >= 100: break

    return products


# ── Buy Buy Baby scraper ──────────────────────────────────────────────────────
def _buybuy_baby(tb, search_url, site, pcb=None):
    """BuyBuyBaby (BBBY) uses Bed Bath & Beyond's platform — JSON-LD + HTML cards."""
    products = []; seen = set()
    base = "https://www.buybuybaby.com"

    for page in range(1, 4):
        sep = "&" if "?" in search_url else "?"
        url = f"{search_url}{sep}start={24*(page-1)}" if page > 1 else search_url
        soup = tb.get_page(url, "networkidle")
        if not soup: break

        # JSON-LD
        for sc in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(sc.string or "")
                if not isinstance(data,list): data=[data]
                for it in data:
                    if it.get("@type") != "Product": continue
                    name = it.get("name","")
                    if not name or name in seen: continue
                    seen.add(name)
                    offer = it.get("offers",{})
                    if isinstance(offer,list): offer=offer[0] if offer else {}
                    price = _usd(str(offer.get("price","")), "usd")
                    products.append({"name":name,"brand_name":it.get("brand",{}).get("name","") if isinstance(it.get("brand"),dict) else "",
                        "category_name":_infer_cat_name(name,it.get("description","")),
                        "description":it.get("description","")[:600],
                        "url":it.get("url",url),"image_url":it.get("image",""),
                        "price_usd":price,"price":price,"currency":"USD",
                        "source_site":site,"brand_type":"medical",
                        "discreet_shipping":1,"free_sample":0,"in_stock":1})
                    if pcb: pcb(f"  Found: {name[:55]}")
            except Exception: pass

        # HTML fallback
        if not [p for p in products]:
            for card in soup.select("[class*='productCard'],[class*='product-card'],li[class*='product']")[:60]:
                name_el = card.select_one("[class*='productTitle'],[class*='product-title'],h2,h3")
                if not name_el: continue
                name = name_el.get_text(strip=True)
                if not name or name in seen: continue
                seen.add(name)
                price_el = card.select_one("[class*='price'],[class*='Price']")
                price = _usd(price_el.get_text(),"usd") if price_el else None
                a_el = card.select_one("a[href]")
                purl = urljoin(base, a_el["href"]) if a_el and a_el.get("href") else url
                img_el = card.select_one("img[src]")
                img = img_el.get("src","") if img_el else ""
                products.append({"name":name,"brand_name":"",
                    "category_name":_infer_cat_name(name,""),
                    "description":"","url":purl,"image_url":img,
                    "price_usd":price,"price":price,"currency":"USD",
                    "source_site":site,"brand_type":"medical",
                    "discreet_shipping":1,"free_sample":0,"in_stock":1})
                if pcb: pcb(f"  Found: {name[:55]}")
        _delay(1.5, 3.0)
        if len(products) >= 100: break

    return products


# ── Costco scraper ────────────────────────────────────────────────────────────
def _costco(tb, search_url, site, pcb=None):
    """Costco uses Endeca/ATG platform. JSON-LD + .product-description divs."""
    products = []; seen = set()
    base = "https://www.costco.com"

    for page in range(1, 3):
        sep = "&" if "?" in search_url else "?"
        url = f"{search_url}{sep}currentPage={page}" if page > 1 else search_url
        soup = tb.get_page(url, "networkidle")
        if not soup: break

        for card in soup.select(".product-list-item,.product-detail,li[class*='product']")[:60]:
            name_el = card.select_one(".description a,.product-title a,h3 a,h2 a")
            if not name_el: continue
            name = name_el.get_text(strip=True)
            if not name or name in seen: continue
            seen.add(name)
            price_el = card.select_one(".price,[class*='price'],[class*='Price']")
            price = _usd(price_el.get_text(),"usd") if price_el else None
            href = name_el.get("href","")
            purl = urljoin(base, href) if href else url
            img_el = card.select_one("img[src]")
            img = img_el.get("src","") if img_el else ""
            products.append({"name":name,"brand_name":"",
                "category_name":_infer_cat_name(name,""),
                "description":"","url":purl,"image_url":img,
                "price_usd":price,"price":price,"currency":"USD",
                "source_site":site,"brand_type":"medical",
                "discreet_shipping":0,"free_sample":0,"in_stock":1})
            if pcb: pcb(f"  Found: {name[:55]}")
        _delay(2.0, 4.0)
        if len(products) >= 80: break

    return products


BRAND_FLAGS = {
    "tykables":(0,0),"abu/abuniverse":(1,1),"rearz":(1,0),"bambino":(1,1),
    "betterdry":(0,1),"crinklz":(0,1),"little for big":(1,0),
    "northshore care":(1,1),"prevail":(1,0),"tranquility":(1,1),
    "abena":(0,1),"tena":(1,0),"depend":(1,0),"attends":(1,0),"unique wellness":(1,1),
}

PROFILES = {
    "Tykables Store":         {"type":"shopify","base":"https://tykables.com","brand":"Tykables","currency":"usd","brand_type":"abdl"},
    "ABUniverse Store":       {"type":"shopify","base":"https://abuniverse.com","brand":"ABU/ABUniverse","currency":"usd","brand_type":"abdl"},
    "Rearz Store":            {"type":"shopify_probe","brand":"Rearz","currency":"cad","brand_type":"abdl","alt_bases":["https://rearz.ca","https://www.rearz.ca"]},
    "Little For Big":         {"type":"shopify_probe","brand":"Little For Big","currency":"usd","brand_type":"abdl","alt_bases":["https://www.littleforbig.com"],"fallback_filter":"/products/"},
    "Bambino Diapers":        {"type":"html","base":"https://bambinodiapers.com/shop","brand":"Bambino","currency":"usd","brand_type":"abdl","selectors":{"product_link":"a.woocommerce-LoopProduct-link","link_filter":"/product/","title":"h1.product_title","description":"div.woocommerce-product-details__short-description","price":"p.price"}},
    "BetterDry":              {"type":"html","base":"https://www.betterdrydiapers.com","brand":"BetterDry","currency":"eur","brand_type":"abdl","selectors":{"product_link":"a.woocommerce-LoopProduct-link","link_filter":"/product/","title":"h1.product_title","description":"div.woocommerce-product-details__short-description","price":"p.price"}},
    "Crinklz":                {"type":"custom","fn":"crinklz","brand":"Crinklz","brand_type":"abdl"},
    "ABDL Factory":           {"type":"shopify_probe","brand":"ABDL Factory","brand_type":"abdl","alt_bases":["https://abdlfactory.com"]},
    "Fabine":                 {"type":"shopify_probe","brand":"Fabine","currency":"eur","brand_type":"abdl","alt_bases":["https://fabine.de"]},
    "MyDiaper":               {"type":"shopify_probe","brand":"MyDiaper","currency":"eur","brand_type":"abdl","alt_bases":["https://mydiaper.eu"]},
    "NorthShore Care Supply": {"type":"shopify_probe","brand":"NorthShore Care","currency":"usd","brand_type":"medical","alt_bases":["https://northshorecare.com","https://www.northshorecare.com"]},
    "Carewell":               {"type":"shopify_probe","brand":"","currency":"usd","brand_type":"medical","alt_bases":["https://www.carewell.com"]},
    "Tranquility Products":   {"type":"shopify_probe","brand":"Tranquility","currency":"usd","brand_type":"medical","alt_bases":["https://www.tranquilityproducts.com"]},
    "Unique Wellness":        {"type":"shopify_probe","brand":"Unique Wellness","currency":"usd","brand_type":"medical","alt_bases":["https://wellnessbriefs.com","https://www.wellnessbriefs.com"]},
    "Abena USA":              {"type":"shopify_probe","brand":"Abena","currency":"usd","brand_type":"both","alt_bases":["https://www.abenausa.com"]},
    "Adult Diaper Superstore":{"type":"shopify_probe","brand":"","currency":"usd","brand_type":"medical","alt_bases":["https://www.adultdiapersuperstore.com"]},
    "DiapersEtc":             {"type":"shopify_probe","brand":"","currency":"usd","brand_type":"medical","alt_bases":["https://www.diapersetc.com"]},
    "Parentgiving":           {"type":"shopify_probe","brand":"","currency":"usd","brand_type":"medical","alt_bases":["https://www.parentgiving.com"]},
    "XP Medical":             {"type":"shopify_probe","brand":"","currency":"usd","brand_type":"medical","alt_bases":["https://www.xpmedical.com","https://xpmedical.com"]},
    "HDIS":                   {"type":"html","base":"https://www.hdis.com/incontinence","brand":"","currency":"usd","brand_type":"medical","selectors":{"product_link":"a[href*='/incontinence/']","link_filter":"/incontinence/","title":"h1","price":".price,.product-price"}},
    "Vitality Medical":       {"type":"html","base":"https://www.vitalitymedical.com/briefs.html","brand":"","currency":"usd","brand_type":"medical","selectors":{"product_link":"a[href*='vitalitymedical.com'][href*='.html']","link_filter":"vitalitymedical.com","title":"h1","price":".price,.our-price"}},
    "Personally Delivered":   {"type":"html","base":"https://www.personallydelivered.com/adult-diapers","brand":"","currency":"usd","brand_type":"medical","selectors":{"product_link":"a.product-item-name","link_filter":"/product","title":"h1.page-title","price":".price"}},
    "Health Products For You":{"type":"html","base":"https://www.healthproductsforyou.com/c-adult-diapers.html","brand":"","currency":"usd","brand_type":"medical","selectors":{"product_link":"a.product-name","link_filter":"/p-","title":"h1","price":".our-price"}},

    # ── Mainstream retail — baby / incontinence sections ──────────────────────
    # Walmart baby products category + incontinence + diapers for adults
    "Walmart Baby":           {"type":"walmart","url":"https://www.walmart.com/cp/baby-products/5427","brand":"","currency":"usd","brand_type":"medical"},
    "Walmart Incontinence":   {"type":"walmart","url":"https://www.walmart.com/cp/incontinence/1101660","brand":"","currency":"usd","brand_type":"medical"},
    "Walmart Adult Diapers":  {"type":"walmart","url":"https://www.walmart.com/search?q=adult+diapers","brand":"","currency":"usd","brand_type":"medical"},

    # Target baby section + adult care
    "Target Baby":            {"type":"target","url":"https://www.target.com/c/baby/-/N-5xsx0","brand":"","currency":"usd","brand_type":"medical"},
    "Target Adult Care":      {"type":"target","url":"https://www.target.com/c/incontinence-care-adult/-/N-5xu1u","brand":"","currency":"usd","brand_type":"medical"},
    "Target Diapers":         {"type":"target","url":"https://www.target.com/s?searchTerm=adult+diapers","brand":"","currency":"usd","brand_type":"medical"},

    # Amazon baby/incontinence
    "Amazon Baby Diapers":    {"type":"amazon","url":"https://www.amazon.com/s?k=adult+diapers+large&rh=n%3A3760901","brand":"","currency":"usd","brand_type":"medical"},
    "Amazon Baby Products":   {"type":"amazon","url":"https://www.amazon.com/s?k=baby+diapers+onesie+accessories&rh=n%3A165796011","brand":"","currency":"usd","brand_type":"medical"},
    "Amazon ABDL":            {"type":"amazon","url":"https://www.amazon.com/s?k=ABDL+diapers+adult+baby","brand":"","currency":"usd","brand_type":"abdl"},

    # Pharmacy chains — incontinence / adult care aisles
    "CVS Baby & Adult Care":  {"type":"pharmacy","url":"https://www.cvs.com/shop/incontinence","brand":"","currency":"usd","brand_type":"medical"},
    "Walgreens Incontinence": {"type":"pharmacy","url":"https://www.walgreens.com/store/c/incontinence/ID=361607-tier2","brand":"","currency":"usd","brand_type":"medical"},
    "Rite Aid Baby & Adult":  {"type":"pharmacy","url":"https://www.riteaid.com/shop/baby-incontinence/incontinence","brand":"","currency":"usd","brand_type":"medical"},

    # Dollar stores & club stores
    "Dollar General Baby":    {"type":"dollar_general","url":"https://www.dollargeneral.com/category/baby-diapers-training-pants.html","brand":"","currency":"usd","brand_type":"medical"},
    "Costco Diapers":         {"type":"costco","url":"https://www.costco.com/adult-incontinence.html","brand":"","currency":"usd","brand_type":"medical"},

    # Specialty baby stores
    "Buy Buy Baby":           {"type":"buybuy_baby","url":"https://www.buybuybaby.com/store/s/diaper","brand":"","currency":"usd","brand_type":"medical"},
}


def _do_scrape(tb, name, profile, pcb=None, lcb=None):
    """Run one site's scrape using the given _ThreadBrowser."""
    if profile.get("disabled"):
        if lcb: lcb(f"  ⊘ {name}: disabled"); return []
    brand_name = profile.get("brand","")
    stype      = profile.get("type","shopify_probe")
    cur        = profile.get("currency","usd")
    btype      = profile.get("brand_type","abdl")
    disc, samp = BRAND_FLAGS.get(brand_name.lower(), (0,0))
    fb_filter  = profile.get("fallback_filter","/product")
    def lg(m):
        log.info(m)
        if lcb: lcb(m)

    if stype == "shopify":
        root = _probe(tb, profile["base"])
        if not root: lg(f"  ⚠ {name}: probe failed"); return []
        return _shopify(tb, root, brand_name, name, pcb, cur, btype, disc, samp)

    elif stype == "shopify_probe":
        for base in profile.get("alt_bases",[]):
            root = _probe(tb, base)
            if root:
                lg(f"  ✓ {name}: Shopify @ {root}")
                return _shopify(tb, root, brand_name, name, pcb, cur, btype, disc, samp)
        lg(f"  ⚠ {name}: no Shopify found — HTML fallback")
        for base in profile.get("alt_bases",[]):
            soup = tb.get_page(base, "networkidle")
            if soup:
                return _html(tb, base, brand_name, name,
                             {"product_link":"a","link_filter":fb_filter},
                             pcb, cur, btype, disc, samp)
        lg(f"  ✗ {name}: unreachable"); return []

    elif stype == "html":
        return _html(tb, profile["base"], brand_name, name,
                     profile.get("selectors",{}), pcb, cur, btype, disc, samp)

    elif stype == "custom":
        if profile.get("fn") == "crinklz":
            return _crinklz(tb, brand_name, name, pcb)
        lg(f"  ⚠ Unknown custom fn"); return []

    elif stype == "walmart":
        return _walmart(tb, profile["url"], name, pcb)

    elif stype == "target":
        return _target(tb, profile["url"], name, pcb)

    elif stype == "amazon":
        return _amazon(tb, profile["url"], name, pcb)

    elif stype == "pharmacy":
        return _pharmacy(tb, profile["url"], name, pcb)

    elif stype == "dollar_general":
        return _dollar_general(tb, profile["url"], name, pcb)

    elif stype == "buybuy_baby":
        return _buybuy_baby(tb, profile["url"], name, pcb)

    elif stype == "costco":
        return _costco(tb, profile["url"], name, pcb)

    return []


def _scrape_site_worker(site, pcb, lcb, semaphore):
    """
    Worker for ThreadPoolExecutor.
    Acquires semaphore (limits to MAX_CONCURRENT), then creates its own
    complete playwright stack, scrapes, tears down.  Nothing shared.
    """
    name    = site["name"]
    sid     = site["id"]
    started = datetime.now().isoformat()
    profile = PROFILES.get(name)

    with semaphore:
        if lcb: lcb(f"🌐 [{name}] starting…")
        try:
            with _ThreadBrowser() as tb:
                if profile:
                    products = _do_scrape(tb, name, profile, pcb, lcb)
                else:
                    root = _probe(tb, site["url"])
                    if root:
                        products = _shopify(tb, root, "", name, pcb)
                    else:
                        products = _html(tb, site["url"], "", name, {}, pcb)
            found  = len(products)
            for p in products: upsert_product(p)
            status, err = "SUCCESS", ""
        except Exception as e:
            found = 0; status, err = "ERROR", str(e)
            log.exception(f"Worker error [{name}]: {e}")

    finished = datetime.now().isoformat()
    add_scrape_log(sid, started, finished, found, found, status, err)
    if lcb: lcb(f"[{name}] ✓ {found} products [{status}]")
    return {"site": name, "status": status, "found": found, "added": found, "error": err}


def scrape_all(enabled_only=True, pcb=None, lcb=None, force=False):
    """Scrape all due sites with up to MAX_CONCURRENT parallel browser processes."""
    if not SCRAPE_AVAILABLE:
        return [{"status":"ERROR","error":"playwright not installed"}]
    sites = get_scrape_sites()
    if enabled_only: sites = [s for s in sites if s["scrape_enabled"]]
    due  = [s for s in sites if force or should_scrape_site(s)]
    skip = [s for s in sites if not force and not should_scrape_site(s)]

    if lcb:
        lcb(f"ℹ  {len(due)} sites to scrape, {len(skip)} up-to-date "
            f"(max {MAX_CONCURRENT} browsers at once)")
    if not due:
        if lcb: lcb("✅ All sites up-to-date — nothing to scrape")
        return [{"site":s["name"],"status":"SKIPPED","found":0,"added":0,"error":""} for s in sites]

    semaphore = threading.Semaphore(MAX_CONCURRENT)
    results   = []
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT,
                            thread_name_prefix="abdl-scrape") as pool:
        futures = {pool.submit(_scrape_site_worker, s, pcb, lcb, semaphore): s
                   for s in due}
        for fut in as_completed(futures):
            try:    results.append(fut.result())
            except Exception as e:
                site = futures[fut]
                results.append({"site":site["name"],"status":"ERROR",
                                 "error":str(e),"found":0,"added":0})
    results += [{"site":s["name"],"status":"SKIPPED","found":0,"added":0,"error":""}
                for s in skip]
    return results


def scrape_site(site, pcb=None, lcb=None, force=False):
    """Scrape a single site in the current thread (for the UI 'Scrape Selected' button)."""
    if not SCRAPE_AVAILABLE:
        return {"status":"ERROR","error":"playwright not installed"}
    name    = site["name"]
    sid     = site["id"]
    started = datetime.now().isoformat()
    profile = PROFILES.get(name)

    if not force and not should_scrape_site(site):
        msg = f"⏭ {name}: up-to-date (next: {_next_scrape_time(site)})"
        if lcb: lcb(msg)
        return {"site":name,"status":"SKIPPED","found":0,"added":0,"error":""}

    if lcb: lcb(f"🌐 [{name}] Chromium scraping…")
    try:
        with _ThreadBrowser() as tb:
            if profile:
                products = _do_scrape(tb, name, profile, pcb, lcb)
            else:
                root = _probe(tb, site["url"])
                products = _shopify(tb, root, "", name, pcb) if root \
                           else _html(tb, site["url"], "", name, {}, pcb)
        found  = len(products)
        for p in products: upsert_product(p)
        status, err = "SUCCESS", ""
    except Exception as e:
        found = 0; status, err = "ERROR", str(e)
        log.exception(f"Scrape error [{name}]: {e}")

    finished = datetime.now().isoformat()
    add_scrape_log(sid, started, finished, found, found, status, err)
    if lcb: lcb(f"[{name}] ✓ {found} products [{status}]")
    return {"site":name,"status":status,"found":found,"added":found,"error":err}


def scrape_site_by_id(sid, pcb=None, lcb=None, force=False):
    site = next((s for s in get_scrape_sites() if s["id"] == sid), None)
    if not site: return {"status":"ERROR","error":"Site not found"}
    return scrape_site(site, pcb=pcb, lcb=lcb, force=force)


# ── Demo seed ─────────────────────────────────────────────────────────────────

DEMO = [
    {"name":"Tykables Camelot","brand_name":"Tykables","category_name":"ABDL Diapers",
     "description":"Castle-themed ABDL diaper, knights & dragons print, plastic-backed crinkle.",
     "url":"https://tykables.com/products/camelot","image_url":"",
     "price_usd":24.99,"absorbency_ml":3000,"absorbency_label":"Ultra",
     "size_range":"M/L/XL","tab_count":2,"colors":"Blue/Gold","patterns":"Castle, Knights",
     "tags":"ABDL, premium, print, crinkle","in_stock":1,
     "source_site":"Tykables Store","brand_type":"abdl","discreet_shipping":0,"free_sample":0},
    {"name":"Tykables Waddler","brand_name":"Tykables","category_name":"ABDL Diapers",
     "description":"Pastel cloud design ultra-thick overnight ABDL diaper.",
     "url":"https://tykables.com/products/waddler","image_url":"",
     "price_usd":22.99,"absorbency_ml":4000,"absorbency_label":"Maximum",
     "size_range":"S/M/L/XL","tab_count":2,"patterns":"Clouds, Stars",
     "tags":"ABDL, overnight, thick","in_stock":1,
     "source_site":"Tykables Store","brand_type":"abdl","discreet_shipping":0,"free_sample":0},
    {"name":"ABU Space","brand_name":"ABU/ABUniverse","category_name":"ABDL Diapers",
     "description":"Astronaut & space-themed ABDL diaper, very high capacity.",
     "url":"https://abuniverse.com/products/space","image_url":"",
     "price_usd":19.99,"absorbency_ml":3800,"absorbency_label":"Maximum",
     "size_range":"S/M/L/XL/XXL","tab_count":2,"patterns":"Space, Rockets",
     "tags":"ABDL, space, astronaut, print","in_stock":1,
     "source_site":"ABUniverse Store","brand_type":"abdl","discreet_shipping":1,"free_sample":1},
    {"name":"ABU SDK","brand_name":"ABU/ABUniverse","category_name":"ABDL Diapers",
     "description":"Simple Dry Kids — classic white crinkly ABDL diaper.",
     "url":"https://abuniverse.com/products/sdk","image_url":"",
     "price_usd":17.99,"absorbency_ml":2800,"absorbency_label":"High",
     "size_range":"S/M/L/XL","tab_count":2,
     "tags":"ABDL, classic, white, crinkle","in_stock":1,
     "source_site":"ABUniverse Store","brand_type":"abdl","discreet_shipping":1,"free_sample":1},
    {"name":"Rearz Safari","brand_name":"Rearz","category_name":"ABDL Diapers",
     "description":"Jungle animals print — one of Rearz's most loved ABDL designs.",
     "url":"https://rearz.ca/safari","image_url":"",
     "price_usd":15.54,"absorbency_ml":3200,"absorbency_label":"Ultra",
     "size_range":"S/M/L/XL","tab_count":2,"patterns":"Safari Animals",
     "tags":"ABDL, safari, animals, print","in_stock":1,
     "source_site":"Rearz Store","brand_type":"abdl","discreet_shipping":1,"free_sample":0},
    {"name":"Bambino Teddy","brand_name":"Bambino","category_name":"ABDL Diapers",
     "description":"Teddy bear print, soft and comfortable ABDL diaper.",
     "url":"https://bambinodiapers.com/teddy","image_url":"",
     "price_usd":19.99,"absorbency_ml":3100,"absorbency_label":"Ultra",
     "size_range":"S/M/L/XL","tab_count":2,"patterns":"Teddy Bears",
     "tags":"ABDL, teddy bear, print, soft","in_stock":1,
     "source_site":"Bambino Diapers","brand_type":"abdl","discreet_shipping":1,"free_sample":1},
    {"name":"Crinklz Aquanaut","brand_name":"Crinklz","category_name":"ABDL Diapers",
     "description":"Underwater ocean adventure print, plastic-backed crinkle ABDL diaper.",
     "url":"https://www.crinklz.com/shop/aquanaut","image_url":"",
     "price_usd":29.24,"absorbency_ml":3000,"absorbency_label":"Ultra",
     "size_range":"M/L/XL","tab_count":2,"patterns":"Ocean, Underwater",
     "tags":"ABDL, ocean, crinkle","in_stock":1,
     "source_site":"Crinklz","brand_type":"abdl","discreet_shipping":0,"free_sample":1},
    {"name":"Little For Big Cotton Candy Onesie","brand_name":"Little For Big","category_name":"Onesies / Rompers",
     "description":"Pastel cotton candy print snap-crotch onesie for adults.",
     "url":"https://littleforbig.com/products/cotton-candy-onesie","image_url":"",
     "price_usd":34.99,"size_range":"XS/S/M/L/XL/XXL","colors":"Pastel Pink/Blue",
     "tags":"onesie, clothing, snap crotch","in_stock":1,
     "source_site":"Little For Big","brand_type":"abdl","discreet_shipping":1,"free_sample":0},
    {"name":"NorthShore Supreme Briefs","brand_name":"NorthShore Care","category_name":"Diapers",
     "description":"Medical-grade overnight tab brief, maximum capacity, latex-free.",
     "url":"https://northshorecare.com/products/northshore-supreme-briefs","image_url":"",
     "price_usd":32.99,"absorbency_ml":5500,"absorbency_label":"Maximum+",
     "size_range":"S/M/L/XL/XXL/XXXL","tab_count":2,
     "tags":"medical, overnight, high capacity","in_stock":1,
     "source_site":"NorthShore Care Supply","brand_type":"medical","discreet_shipping":1,"free_sample":1},
    {"name":"NorthShore MegaMax Tab Brief","brand_name":"NorthShore Care","category_name":"Diapers",
     "description":"Highest capacity brief — 4-tab, extended wear, 8500ml.",
     "url":"https://northshorecare.com/products/northshore-megamax-tab-style-briefs","image_url":"",
     "price_usd":39.99,"absorbency_ml":8500,"absorbency_label":"Maximum+",
     "size_range":"S/M/L/XL/XXL","tab_count":4,
     "tags":"medical, maximum absorbency, 4-tab, overnight","in_stock":1,
     "source_site":"NorthShore Care Supply","brand_type":"medical","discreet_shipping":1,"free_sample":1},
    {"name":"Tranquility ATN Tab Brief","brand_name":"Tranquility","category_name":"Diapers",
     "description":"All-Through-The-Night brief, high capacity.",
     "url":"https://www.tranquilityproducts.com/products/atn","image_url":"",
     "price_usd":17.99,"absorbency_ml":3600,"absorbency_label":"Maximum",
     "size_range":"S/M/L/XL/XXL","tab_count":2,
     "tags":"medical, overnight, ATN","in_stock":1,
     "source_site":"Tranquility Products","brand_type":"medical","discreet_shipping":1,"free_sample":1},
    {"name":"Abena Abri-Form X-Plus","brand_name":"Abena","category_name":"Diapers",
     "description":"Danish medical/ABDL crossover. Very high capacity, 4-tape, cloth-backed.",
     "url":"https://www.abenausa.com/abri-form-x-plus","image_url":"",
     "price_usd":36.99,"absorbency_ml":4700,"absorbency_label":"Maximum+",
     "size_range":"S/M/L/XL","tab_count":4,
     "tags":"medical, ABDL, Danish, high capacity, 4-tape","in_stock":1,
     "source_site":"Abena USA","brand_type":"both","discreet_shipping":0,"free_sample":1},
    {"name":"Prevail Air Tab Brief","brand_name":"Prevail","category_name":"Diapers",
     "description":"Prevail Air — breathable tab brief with OdorGuard technology.",
     "url":"https://prevailproducts.com/products/prevail-air-brief","image_url":"",
     "price_usd":19.99,"absorbency_ml":2800,"absorbency_label":"High",
     "size_range":"S/M/L/XL/XXL","tab_count":2,
     "tags":"medical, breathable, OdorGuard","in_stock":1,
     "source_site":"XP Medical","brand_type":"medical","discreet_shipping":1,"free_sample":0},
    {"name":"Unique Wellness Super-Plus Brief","brand_name":"Unique Wellness","category_name":"Diapers",
     "description":"Ultra-absorbent incontinence brief, extended wear, odour control.",
     "url":"https://uniquewellness.com/products/super-plus","image_url":"",
     "price_usd":27.99,"absorbency_ml":5200,"absorbency_label":"Maximum+",
     "size_range":"S/M/L/XL/XXL","tab_count":2,
     "tags":"medical, super absorbent, extended wear","in_stock":1,
     "source_site":"Unique Wellness","brand_type":"medical","discreet_shipping":1,"free_sample":1},
    {"name":"TENA Ultra Brief","brand_name":"TENA","category_name":"Diapers",
     "description":"TENA Ultra breathable tab brief, ConfioAir technology.",
     "url":"https://www.tena.us/products/briefs/tena-ultra-briefs","image_url":"",
     "price_usd":24.99,"absorbency_ml":2500,"absorbency_label":"Ultra",
     "size_range":"S/M/L/XL/XXL/XXXL","tab_count":2,
     "tags":"medical, TENA, breathable","in_stock":1,
     "source_site":"HDIS","brand_type":"medical","discreet_shipping":1,"free_sample":0},
]


def seed_demo_data(pcb=None, force=False):
    from database import get_connection
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()
    if count > 0 and not force: return 0
    added = 0
    for p in DEMO:
        try:
            upsert_product(p); added += 1
            if pcb: pcb(f"Seeding: {p['name']}")
        except Exception as e:
            log.error(f"Seed [{p['name']}]: {e}")
    return added
