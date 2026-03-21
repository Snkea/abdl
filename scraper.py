"""
Catalog Scraper — scraper.py

Playwright multi-thread fix:
  - playwright sync_api is greenlet-based and CANNOT be shared across threads.
  - Each worker thread creates its own sync_playwright + browser + context + page,
    uses it, then tears it all down. No shared browser globals.
  - MAX_CONCURRENT = 4  (up to 4 browser processes running simultaneously)
"""
import re, time, random, json, logging, threading, socket
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

log = logging.getLogger("Scraper")

MAX_CONCURRENT = 4   # simultaneous browser processes

_USER_AGENTS = [
    # Chrome 140 on Windows 10/11 — matches the installed Playwright Chromium version
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    # Edge on Windows (shares Chromium engine)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36 Edg/139.0.0.0",
    # Firefox as occasional variant
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0",
]

# Sec-CH-UA hints aligned with each UA above — picked at context creation time
_SEC_CH_UA = {
    "140": '"Chromium";v="140","Google Chrome";v="140","Not.A/Brand";v="99"',
    "139": '"Chromium";v="139","Google Chrome";v="139","Not.A/Brand";v="99"',
    "138": '"Chromium";v="138","Google Chrome";v="138","Not.A/Brand";v="99"',
    "140e": '"Chromium";v="140","Microsoft Edge";v="140","Not.A/Brand";v="99"',
    "139e": '"Chromium";v="139","Microsoft Edge";v="139","Not.A/Brand";v="99"',
    "ff":   "",   # Firefox doesn't send Sec-CH-UA
}

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
    Includes automatic Chromium crash recovery — if the browser dies mid-scrape
    (ERR_ABORTED / Connection closed / TargetClosed) it relaunches once and retries.

    Usage:
        with _ThreadBrowser() as tb:
            soup = tb.get_page("https://example.com")
    """
    # Exceptions that indicate Chromium itself has died (not just a bad page)
    _CRASH_MSGS = (
        "connection closed while reading from the driver",
        "target page, context or browser has been closed",
        "browser has been closed",
        "connection closed",
        "target closed",
    )

    def __init__(self):
        self._pw   = None
        self._brow = None
        self._ctx  = None
        self.page  = None
        self._dead = False   # set True after unrecoverable crash

    def __enter__(self):
        self._launch()
        return self

    def _launch(self):
        """Start (or restart) the full playwright stack."""
        self._pw   = sync_playwright().start()
        self._brow = self._pw.chromium.launch(headless=True, args=_CHROMIUM_ARGS)
        ua = random.choice(_USER_AGENTS)

        if "Edg/140" in ua:      sec_ch = _SEC_CH_UA["140e"]
        elif "Edg/139" in ua:    sec_ch = _SEC_CH_UA["139e"]
        elif "Chrome/140" in ua: sec_ch = _SEC_CH_UA["140"]
        elif "Chrome/139" in ua: sec_ch = _SEC_CH_UA["139"]
        elif "Chrome/138" in ua: sec_ch = _SEC_CH_UA["138"]
        else:                    sec_ch = ""

        extra_headers = {
            "Accept-Language": "en-US,en;q=0.9",
            "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
            "DNT":             "1",
        }
        if sec_ch:
            extra_headers["Sec-CH-UA"]          = sec_ch
            extra_headers["Sec-CH-UA-Mobile"]   = "?0"
            extra_headers["Sec-CH-UA-Platform"] = '"Windows"'

        self._ctx = self._brow.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=ua, locale="en-US", timezone_id="America/Chicago",
            extra_http_headers=extra_headers,
        )
        self._ctx.add_init_script(_STEALTH_JS)
        self.page = self._ctx.new_page()
        self._dead = False

    def _shutdown(self):
        """Tear down the playwright stack silently."""
        for obj, method in [(self.page,"close"),(self._ctx,"close"),
                            (self._brow,"close"),(self._pw,"stop")]:
            if obj:
                try:   getattr(obj, method)()
                except Exception: pass
        self.page = self._brow = self._ctx = self._pw = None

    def __exit__(self, *_):
        self._shutdown()

    def _is_crash(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(sig in msg for sig in self._CRASH_MSGS)

    def _restart(self):
        """Shut down current browser and launch a fresh one."""
        log.warning("Chromium crashed — restarting browser…")
        self._shutdown()
        try:
            time.sleep(1.5)   # brief pause before relaunch
            self._launch()
            return True
        except Exception as e:
            log.error(f"Browser restart failed: {e}")
            self._dead = True
            return False

    def get_page(self, url, wait="domcontentloaded", retries=2):
        if self._dead:
            return None
        for attempt in range(retries + 1):
            try:
                self.page.goto(url, wait_until=wait, timeout=12_000)
                time.sleep(random.uniform(0.2, 0.6))
                return BeautifulSoup(self.page.content(), "html.parser")
            except PWTimeout:
                log.warning(f"Timeout [{attempt+1}] {url}")
                if attempt == retries: return None
                time.sleep(2)
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                log.warning(f"Pipe error fetching {url}: {e}")
                # Attempt browser restart once
                if attempt == 0 and self._restart():
                    continue   # retry with fresh browser
                return None
            except Exception as e:
                if self._is_crash(e):
                    log.warning(f"Browser crash on {url}: {e}")
                    # One restart attempt
                    if attempt == 0 and self._restart():
                        continue   # retry with fresh browser
                    return None
                log.warning(f"GET {url}: {e}")
                return None
        return None

    def fetch_json(self, url):
        if self._dead:
            return None
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
            if self._is_crash(e):
                log.warning(f"Browser crash on fetch_json {url}: {e}")
                self._restart()
            else:
                log.warning(f"fetch_json {url}: {e}")
            return None


# ── Utilities ─────────────────────────────────────────────────────────────────

def _delay(lo=0.3, hi=0.9):
    time.sleep(random.uniform(lo, hi))

def _dns_ok(url):
    """Return True if the host resolves within 2 s. Skips dead sites instantly."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        socket.setdefaulttimeout(2)
        socket.gethostbyname(host)
        return True
    except Exception:
        return False


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


def _infer_cat_name(name, desc=""):
    """
    Infer the product category from name + description.
    Covers all ABDL, age regression, and incontinence product types.
    """
    t = (name + " " + (desc or "")).lower()

    # ── Clothing — check before diapers to avoid misclassification ──────────
    if any(w in t for w in ["footed sleeper","footie","footies","footed pajama",
                             "footed pyjama","footed romper","sleepsuit"]):
        return "Footed Sleepers"
    if any(w in t for w in ["onesie","snap crotch","bodysuit","romper","playsuit",
                             "snap bottom","popper crotch","button crotch"]):
        return "Onesies / Rompers"
    if any(w in t for w in ["shortall","shortalls","overall","overalls","dungaree"]):
        return "Overalls / Shortalls"
    if any(w in t for w in ["bib overall","bib shortall"]):
        return "Overalls / Shortalls"
    if any(w in t for w in ["plastic pant","plastic pants","pvc pant","vinyl pant",
                             "rubber pant","waterproof pant","diaper cover",
                             "diaper wrap","pul cover","waterproof cover",
                             "diaper pants","nappy cover","nappy pant"]):
        return "Plastic Pants / Covers"
    if any(w in t for w in ["bib","drool bib","bandana bib"]):
        return "Bibs"
    if any(w in t for w in ["bonnet","baby hat","baby cap","lace cap",
                             "frilly hat","christening hat"]):
        return "Bonnets / Headwear"
    if any(w in t for w in ["mitten","mittens","baby mitt","scratch mitt"]):
        return "Mittens"
    if any(w in t for w in ["baby dress","lolita dress","frilly dress",
                             "pinafore","smock","babydoll dress"]):
        return "Dresses / Skirts"
    if any(w in t for w in ["baby shorts","frilly shorts","rhumba shorts",
                             "diaper shirt","play shorts"]):
        return "Baby Clothing"
    if any(w in t for w in ["onesie set","layette","outfit set","baby set",
                             "clothing set","bundle set"]):
        return "Clothing Sets"

    # ── Feeding / Oral ────────────────────────────────────────────────────────
    if any(w in t for w in ["pacifier","dummy","soother","paci ",
                             "pacifier clip","paci clip","soother clip",
                             "binky","wubbanub"]):
        return "Pacifiers"
    if any(w in t for w in ["baby bottle","infant bottle","sippy cup",
                             "sippy","straw cup","training cup","bottle nipple",
                             "bottle teat","bottle brush"]):
        return "Bottles / Sippy Cups"

    # ── Furniture / Gear ──────────────────────────────────────────────────────
    if any(w in t for w in ["adult crib","adult high chair","adult playpen",
                             "changing table","adult changing table"]):
        return "Furniture"
    if any(w in t for w in ["diaper bag","changing bag","nappy bag",
                             "wet bag","dry bag"]):
        return "Diaper Bags"
    if any(w in t for w in ["changing mat","changing pad","changing station",
                             "portable changing","travel changing"]):
        return "Changing Accessories"

    # ── Bedding ──────────────────────────────────────────────────────────────
    if any(w in t for w in ["mattress protector","mattress cover",
                             "waterproof sheet","waterproof mattress",
                             "incontinence sheet","mattress"]):
        return "Bedding / Mattress"
    if any(w in t for w in ["underpad","chux","chux pad","underpads",
                             "absorbent pad","chair pad","seat pad",
                             "bed pad","bed pad"]):   # bed pad → underpads, not bedding
        return "Underpads / Chux"
    if any(w in t for w in ["blanket","swaddle","comforter","duvet",
                             "muslin blanket","fleece blanket","baby blanket"]):
        return "Blankets"

    # ── Toys / Activities ─────────────────────────────────────────────────────
    if any(w in t for w in ["plush","stuffed animal","stuffed toy","plushie",
                             "stuffy","plushies","teddy bear","teddy","cuddly toy",
                             "stuffie","soft toy","kawaii plush"]):
        return "Plushies / Stuffed Animals"
    if any(w in t for w in ["coloring book","colouring book","activity book",
                             "sticker book","coloring page","paint by",
                             "color by","crayons","colored pencil",
                             "washable marker","art set","craft kit",
                             "activity set","puzzle","jigsaw"]):
        return "Activity / Crafts"
    if any(w in t for w in ["rattle","teether","teething","sensory toy",
                             "baby toy","stacking","building block",
                             "musical toy","bath toy","squeeze toy"]):
        return "Toys"
    if any(w in t for w in ["sticker","stickers","reward sticker",
                             "potty sticker","chart sticker"]):
        return "Stickers"

    # ── Booster / Insert ─────────────────────────────────────────────────────
    if any(w in t for w in ["booster","insert","stuffer","doubler",
                             "soaker","liner","diaper insert",
                             "hemp insert","bamboo insert","prefold"]):
        return "Boosters / Inserts"

    # ── Pull-Ups / Training ──────────────────────────────────────────────────
    if any(w in t for w in ["pull-up","pull up","pullup","training pant",
                             "training underwear","learning pant",
                             "potty training","disposable training"]):
        return "Pull-Ups / Training"

    # ── Swim ─────────────────────────────────────────────────────────────────
    if any(w in t for w in ["swim diaper","swim pant","aqua diaper",
                             "reusable swim","disposable swim",
                             "swimming pant"]):
        return "Swim Diapers"

    # ── Skincare / Medical ────────────────────────────────────────────────────
    if any(w in t for w in ["diaper rash","rash cream","barrier cream",
                             "zinc oxide","lanolin","baby powder",
                             "cornstarch powder","talc","petroleum jelly",
                             "skin protectant","lotion","baby lotion",
                             "wipe","baby wipe","sensitive wipe",
                             "cleansing wipe","flushable wipe"]):
        return "Skincare / Medical"

    # ── Diapers — most specific first ─────────────────────────────────────────
    if any(w in t for w in ["cloth diaper","cloth nappy","flat diaper",
                             "prefold diaper","all-in-one diaper","aio diaper",
                             "pocket diaper","hybrid diaper","fitted diaper"]):
        return "Cloth Diapers"
    if any(w in t for w in ["overnight diaper","night diaper","overnight brief",
                             "overnight nappy","night nappy"]):
        if any(w in t for w in ["print","cute","crinkle","abdl","baby","kawaii"]):
            return "ABDL Diapers"
        return "Overnight Diapers"
    if any(w in t for w in ["diaper","nappy","incontinence brief",
                             "adult brief","tab brief","all-in-one brief",
                             "disposable brief","briefs","adult briefs",
                             "incontinence briefs"]):
        if any(w in t for w in ["print","design","cute","crinkle","abdl","baby",
                                 "kawaii","character","cartoon","printed","pattern",
                                 "space","castle","safari","galaxy","cloud",
                                 "paw","bear","bunny","duck","star","heart",
                                 "tykables","abu ","abuniverse","rearz","bambino",
                                 "fabine","trest","snuggies","cuddlz","jajo",
                                 "dotty","incontrol","crinklez"]):
            return "ABDL Diapers"
        if any(w in t for w in ["incontinence","medical","moderate","light",
                                  "absorbency level","maximum","maximum capacity",
                                  "maximum absorbency","ultra absorbent",
                                  "extra absorbent","heavy duty","heavy-duty",
                                  "northshore","prevail","attends","abena",
                                  "tena","tranquility","unique wellness",
                                  "seni","hartmann","mega max"]):
            return "Medical / Incontinence Diapers"
        return "Diapers"

    # ── Accessories / Misc ────────────────────────────────────────────────────
    if any(w in t for w in ["gift card","gift wrap","gift set"]):
        return "Gift Cards / Sets"
    if any(w in t for w in ["sample pack","trial pack","taster pack",
                             "starter kit","variety pack"]):
        return "Sample Packs"
    if any(w in t for w in ["diaper pail","wet pail","disposal",
                             "disposal bag","odor bag"]):
        return "Disposal / Storage"

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

            # Collect ALL images from the Shopify JSON API
            all_imgs = [img.get("src","") for img in (item.get("images") or []) if img.get("src")]
            # Strip CDN query strings for clean storage
            all_imgs = [u.split("?")[0] for u in all_imgs if u]

            # Also check featured_image (some Shopify themes put it there instead)
            if not all_imgs:
                fi = item.get("featured_image") or {}
                if isinstance(fi, dict) and fi.get("src"):
                    all_imgs = [fi["src"].split("?")[0]]
                elif isinstance(fi, str) and fi:
                    all_imgs = [fi.split("?")[0]]

            # Last resort: fetch the product page and scrape the og:image / main img
            if not all_imgs and purl:
                try:
                    ps = tb.get_page(purl, wait="domcontentloaded")
                    if ps:
                        # Try og:image meta first (most reliable)
                        og = ps.select_one('meta[property="og:image"]')
                        if og and og.get("content"):
                            all_imgs = [og["content"].split("?")[0]]
                        else:
                            # Try product gallery images
                            for sel in [
                                ".product__media img", ".product-single__media img",
                                ".product-featured-media img", ".product-photo-container img",
                                ".woocommerce-product-gallery__image img",
                                'img[class*="product"]', 'img[id*="product"]',
                                ".product img", "main img",
                            ]:
                                el = ps.select_one(sel)
                                if el:
                                    src = (el.get("src") or el.get("data-src") or
                                           el.get("data-srcset","").split()[0])
                                    if src and not src.endswith(".svg"):
                                        full = src if src.startswith("http") else urljoin(purl, src)
                                        all_imgs = [full.split("?")[0]]
                                        break
                except Exception:
                    pass

            img = all_imgs[0] if all_imgs else ""

            price = None
            if item.get("variants"):
                price = _usd(str(item["variants"][0].get("price","")), cur)

            products.append({"name":title,"brand_name":brand_name,
                "category_name":_infer_cat_name(title,desc),"description":desc[:1200],
                "url":purl,"image_url":img,"extra_images":all_imgs[1:],
                "price_usd":price,"price":price,"currency":"USD",
                "absorbency_ml":_abs_ml(desc),"tags":tags,"source_site":site,
                "brand_type":btype,"discreet_shipping":disc,"free_sample":samp,"in_stock":1})
            if pcb: pcb(f"  Found: {title[:55]} ({len(all_imgs)} image{'s' if len(all_imgs)!=1 else ''})")
        page_n += 1; _delay(0.2, 0.6)
    return products


def _html(tb, site_url, brand_name, site, sels, pcb=None, cur="usd", btype="abdl", disc=0, samp=0):
    products = []
    soup = tb.get_page(site_url, wait="domcontentloaded")
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
        # Broad selector list: og:image (most reliable) → gallery → generic
        og = ps.select_one('meta[property="og:image"]')
        if og and og.get("content"):
            img = og["content"].split("?")[0]
        else:
            for s in [
                sels.get("image"),
                # WooCommerce
                ".woocommerce-product-gallery__image img",
                ".woocommerce-product-gallery img",
                "img.wp-post-image",
                # Shopify
                ".product__media img",
                ".product-single__media img",
                ".product-featured-media img",
                ".product-photo-container img",
                # Generic
                ".product-image img",
                ".product__image img",
                'img[class*="product-img"]',
                'img[class*="product_img"]',
                'img[id*="product-img"]',
                ".product img",
                "article img",
                "main img",
            ]:
                if not s:
                    continue
                el = ps.select_one(s)
                if el:
                    src = (el.get("src") or el.get("data-src") or
                           el.get("data-lazy-src") or
                           (el.get("data-srcset","") or "").split()[0])
                    if src and not src.endswith(".svg") and "placeholder" not in src.lower():
                        img = (src if src.startswith("http") else urljoin(purl, src)).split("?")[0]
                        break
        if title:
            products.append({"name":title,"brand_name":brand_name,
                "category_name":_infer_cat_name(title,desc),"description":desc,
                "url":purl,"image_url":img,"extra_images":[],
                "price_usd":price,"price":price,"currency":"USD",
                "source_site":site,"brand_type":btype,"discreet_shipping":disc,
                "free_sample":samp,"in_stock":1})
            if pcb: pcb(f"  Found: {title[:55]}{' 🖼' if img else ''}")
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


BRAND_FLAGS = {
    "tykables":(0,0),"abu/abuniverse":(1,1),"rearz":(1,0),"bambino":(1,1),
    "betterdry":(0,1),"crinklz":(0,1),"little for big":(1,0),
    "northshore care":(1,1),"prevail":(1,0),"tranquility":(1,1),
    "abena":(0,1),"tena":(1,0),"depend":(1,0),"attends":(1,0),"unique wellness":(1,1),
}

PROFILES = {
    # ── ABDL Specialty ────────────────────────────────────────────────
    "Tykables Store":       {"type":"shopify",       "base":"https://tykables.com",             "brand":"Tykables",       "currency":"usd","brand_type":"abdl"},
    "ABUniverse Store":     {"type":"shopify",       "base":"https://abuniverse.com",           "brand":"ABU/ABUniverse", "currency":"usd","brand_type":"abdl"},
    "Rearz Store":          {"type":"shopify_probe", "brand":"Rearz",          "currency":"cad","brand_type":"abdl",
                             "alt_bases":["https://rearz.ca","https://www.rearz.ca"]},
    "Bambino Diapers":      {"type":"html",          "base":"https://bambinodiapers.com/shop",  "brand":"Bambino",        "currency":"usd","brand_type":"abdl",
                             "selectors":{"product_link":"a.woocommerce-LoopProduct-link","link_filter":"/product/",
                                          "title":"h1.product_title","description":"div.woocommerce-product-details__short-description","price":"p.price"}},
    "BetterDry":            {"type":"html",          "base":"https://www.betterdrydiapers.com", "brand":"BetterDry",      "currency":"eur","brand_type":"abdl",
                             "selectors":{"product_link":"a.woocommerce-LoopProduct-link","link_filter":"/product/",
                                          "title":"h1.product_title","description":"div.woocommerce-product-details__short-description","price":"p.price"}},
    "Crinklz":              {"type":"custom",        "fn":"crinklz",           "brand":"Crinklz",        "brand_type":"abdl"},
    "Little For Big":       {"type":"shopify_probe", "brand":"Little For Big", "currency":"usd","brand_type":"abdl",
                             "alt_bases":["https://www.littleforbig.com"],"fallback_filter":"/products/"},
    "ABDL Factory":         {"type":"shopify_probe", "brand":"ABDL Factory",   "currency":"usd","brand_type":"abdl",
                             "alt_bases":["https://abdlfactory.com","https://www.abdlfactory.com"]},
    "Fabine":               {"type":"shopify_probe", "brand":"Fabine",         "currency":"eur","brand_type":"abdl",
                             "alt_bases":["https://fabine.de","https://www.fabine.de"]},
    "MyDiaper":             {"type":"html",          "base":"https://mydiaper.eu",              "brand":"MyDiaper",       "currency":"eur","brand_type":"abdl",
                             "selectors":{"product_link":"a.woocommerce-LoopProduct-link","link_filter":"/product/",
                                          "title":"h1.product_title","price":"p.price"}},
    "InControl Designs":    {"type":"shopify_probe", "brand":"InControl",      "currency":"usd","brand_type":"abdl",
                             "disabled": True,  # ERR_CONNECTION_CLOSED every session since 2026-03-19 — site down
                             "alt_bases":["https://www.incontroldesigns.com","https://incontroldesigns.com"]},
    "Snuggies AU":          {"type":"shopify_probe", "brand":"Snuggies",       "currency":"aud","brand_type":"abdl",
                             "alt_bases":["https://snuggies.com.au","https://www.snuggies.com.au"]},
    "NappiesRus":           {"type":"shopify_probe", "brand":"",               "currency":"gbp","brand_type":"abdl",
                             "alt_bases":["https://www.nappiesrus.co.uk","https://nappiesrus.co.uk"]},
    "Cuddlz":               {"type":"html",          "base":"https://www.cuddlz.com/shop",      "brand":"Cuddlz",         "currency":"gbp","brand_type":"abdl",
                             "selectors":{"product_link":"a.woocommerce-LoopProduct-link","link_filter":"/product/",
                                          "title":"h1.product_title","price":"p.price"}},
    "TNT Diaper Store":     {"type":"shopify_probe", "brand":"",               "currency":"eur","brand_type":"abdl",
                             "alt_bases":["https://www.tntdiaper.com","https://tntdiaper.com"]},
    "ABUniverse EU":        {"type":"shopify",       "base":"https://eu.abuniverse.com",        "brand":"ABU/ABUniverse", "currency":"eur","brand_type":"abdl"},
    "Diaper Bros":          {"type":"shopify_probe", "brand":"",               "currency":"usd","brand_type":"abdl",
                             "alt_bases":["https://www.diaperbroshop.com","https://diaperbroshop.com"]},
    "PeekABU":              {"type":"shopify_probe", "brand":"PeekABU",        "currency":"usd","brand_type":"abdl",
                             "alt_bases":["https://www.peekabu.com","https://peekabu.com"]},
    # Newly added ABDL stores
    "Trest":                {"type":"shopify_probe", "brand":"Trest",          "currency":"usd","brand_type":"abdl",
                             "alt_bases":["https://trest.com","https://www.trest.com"]},
    "Wearing Clouds":       {"type":"shopify_probe", "brand":"Wearing Clouds", "currency":"usd","brand_type":"abdl",
                             "alt_bases":["https://wearingclouds.com","https://www.wearingclouds.com"]},
    "Babykins":             {"type":"shopify_probe", "brand":"Babykins",       "currency":"cad","brand_type":"abdl",
                             "alt_bases":["https://www.babykins.com","https://babykins.com"]},
    "Little Northwood":     {"type":"shopify_probe", "brand":"Little Northwood","currency":"usd","brand_type":"abdl",
                             "alt_bases":["https://www.littlenorthwood.com","https://littlenorthwood.com"]},
    "ABDL Company":         {"type":"shopify_probe", "brand":"ABDL Company",   "currency":"usd","brand_type":"abdl",
                             "alt_bases":["https://abdlcompany.com","https://www.abdlcompany.com"]},
    "Dotty Diaper UK":      {"type":"shopify_probe", "brand":"Dotty Diaper",   "currency":"gbp","brand_type":"abdl",
                             "alt_bases":["https://www.dottythediaper.co.uk","https://dottythediaper.co.uk"]},
    "Changing Times":       {"type":"shopify_probe", "brand":"Changing Times", "currency":"usd","brand_type":"abdl",
                             "alt_bases":["https://changingtimes.org","https://www.changingtimes.org",
                                          "https://changingtimesdiaperco.com"]},
    "Cushies":              {"type":"shopify_probe", "brand":"Cushies",        "currency":"usd","brand_type":"abdl",
                             "alt_bases":["https://cushiesbottoms.com","https://www.cushiesbottoms.com"]},
    "JaJo Diapers":         {"type":"shopify_probe", "brand":"JaJo",           "currency":"usd","brand_type":"abdl",
                             "alt_bases":["https://jajodiapers.com","https://www.jajodiapers.com"]},
    "Tykables EU":          {"type":"shopify",       "base":"https://eu.tykables.com","brand":"Tykables","currency":"eur","brand_type":"abdl"},
    "My Plastic Pants":     {"type":"shopify_probe", "brand":"",               "currency":"usd","brand_type":"abdl",
                             "alt_bases":["https://myplasticpants.com","https://www.myplasticpants.com"]},
    "ABDLCloth":            {"type":"shopify_probe", "brand":"ABDLCloth",      "currency":"usd","brand_type":"abdl",
                             "alt_bases":["https://abdlcloth.com","https://www.abdlcloth.com"]},
    "Lil Kink Boutique":    {"type":"shopify_probe", "brand":"",               "currency":"usd","brand_type":"abdl",
                             "alt_bases":["https://lilkinkboutique.com","https://www.lilkinkboutique.com"]},
    "AB Universe Japan":    {"type":"shopify_probe", "brand":"ABU",            "currency":"jpy","brand_type":"abdl",
                             "alt_bases":["https://jp.abuniverse.com"]},
    # ── Age Regression / Little Space ─────────────────────────────────
    "DDLG World":           {"type":"shopify_probe", "brand":"",               "currency":"usd","brand_type":"regression",
                             "alt_bases":["https://ddlgworld.com","https://www.ddlgworld.com"]},
    "Kawaii Goodsn":        {"type":"shopify_probe", "brand":"",               "currency":"usd","brand_type":"regression",
                             "alt_bases":["https://www.kawaiigoodsn.com","https://kawaiigoodsn.com"]},
    "Blippo Kawaii":        {"type":"shopify_probe", "brand":"",               "currency":"usd","brand_type":"regression",
                             "alt_bases":["https://www.blippo.com","https://blippo.com"]},
    "Sanrio Shop":          {"type":"html",          "base":"https://www.sanrio.com/collections/all","brand":"Sanrio","currency":"usd","brand_type":"regression",
                             "selectors":{"product_link":"a[href*='/products/']","link_filter":"/products/","title":"h1","price":".price"}},
    "Littleforbig Bottles": {"type":"shopify_probe", "brand":"Little For Big", "currency":"usd","brand_type":"regression",
                             "alt_bases":["https://www.littleforbig.com"]},
    # Newly added regression / little space stores
    "DDLG Playground":      {"type":"shopify_probe", "brand":"",               "currency":"usd","brand_type":"regression",
                             "alt_bases":["https://ddlgplayground.com","https://www.ddlgplayground.com"]},
    "Little ABCs":          {"type":"shopify_probe", "brand":"",               "currency":"usd","brand_type":"regression",
                             "alt_bases":["https://littleabcs.com","https://www.littleabcs.com"]},
    "Littles Closet":       {"type":"shopify_probe", "brand":"",               "currency":"usd","brand_type":"regression",
                             "alt_bases":["https://littlescloset.com","https://www.littlescloset.com"]},
    "Funshine Express":     {"type":"shopify_probe", "brand":"",               "currency":"usd","brand_type":"regression",
                             "alt_bases":["https://funshineexpress.com","https://www.funshineexpress.com"]},
    "CuddleBug":            {"type":"shopify_probe", "brand":"",               "currency":"usd","brand_type":"regression",
                             "alt_bases":["https://cuddlebugdiapers.com","https://www.cuddlebugdiapers.com"]},
    "Little Dreamers":      {"type":"shopify_probe", "brand":"",               "currency":"usd","brand_type":"regression",
                             "alt_bases":["https://littledreamers.shop","https://www.littledreamers.shop"]},
    # ── Medical / Incontinence ─────────────────────────────────────────
    "NorthShore Care Supply":{"type":"shopify_probe","brand":"NorthShore Care","currency":"usd","brand_type":"medical",
                              "alt_bases":["https://northshorecare.com","https://www.northshorecare.com"]},
    "Carewell":             {"type":"shopify_probe", "brand":"",               "currency":"usd","brand_type":"medical",
                             "alt_bases":["https://www.carewell.com"]},
    "Tranquility Products": {"type":"shopify_probe", "brand":"Tranquility",    "currency":"usd","brand_type":"medical",
                             "alt_bases":["https://www.tranquilityproducts.com"]},
    "Unique Wellness":      {"type":"shopify_probe", "brand":"Unique Wellness","currency":"usd","brand_type":"medical",
                             "alt_bases":["https://wellnessbriefs.com","https://www.wellnessbriefs.com"]},
    "Abena Global":         {"type":"shopify_probe", "brand":"Abena",          "currency":"usd","brand_type":"both",
                             "alt_bases":["https://www.abena.com","https://abena.com"]},
    "DiapersEtc":           {"type":"shopify_probe", "brand":"",               "currency":"usd","brand_type":"medical",
                             "alt_bases":["https://www.diapersetc.com"]},
    "Parentgiving":         {"type":"shopify_probe", "brand":"",               "currency":"usd","brand_type":"medical",
                             "alt_bases":["https://www.parentgiving.com"]},
    "XP Medical":           {"type":"shopify_probe", "brand":"",               "currency":"usd","brand_type":"medical",
                             "alt_bases":["https://www.xpmedical.com","https://xpmedical.com"]},
    "Attends Shop":         {"type":"shopify_probe", "brand":"Attends",        "currency":"usd","brand_type":"medical",
                             "alt_bases":["https://shop.attends.com"]},
    "Prevail Products":     {"type":"shopify_probe", "brand":"Prevail",        "currency":"usd","brand_type":"medical",
                             "alt_bases":["https://prevailproducts.com","https://www.prevailproducts.com"]},
    "HDIS":                 {"type":"html",          "base":"https://www.hdis.com/incontinence","brand":"","currency":"usd","brand_type":"medical",
                             "selectors":{"product_link":"a[href*='/incontinence/']","link_filter":"/incontinence/",
                                          "title":"h1","price":".price,.product-price"}},
    "Vitality Medical":     {"type":"html",          "base":"https://www.vitalitymedical.com/briefs.html","brand":"","currency":"usd","brand_type":"medical",
                             "selectors":{"product_link":"a[href*='vitalitymedical.com'][href*='.html']","link_filter":"vitalitymedical.com",
                                          "title":"h1","price":".price,.our-price"}},
    "Personally Delivered": {"type":"html",          "base":"https://www.personallydelivered.com/adult-diapers","brand":"","currency":"usd","brand_type":"medical",
                             "selectors":{"product_link":"a.product-item-name","link_filter":"/product",
                                          "title":"h1.page-title","price":".price"}},
    "Health Products For You":{"type":"html",        "base":"https://www.healthproductsforyou.com/c-adult-diapers.html","brand":"","currency":"usd","brand_type":"medical",
                               "selectors":{"product_link":"a.product-name","link_filter":"/p-","title":"h1","price":".our-price"}},
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
        # DNS pre-check: skip dead domains without launching Chromium
        _check = (profile.get("alt_bases") or [site.get("url","")])[0] if profile else site.get("url","")
        if _check and not _dns_ok(_check):
            msg = f"⊘ [{name}] skipped — host unreachable"
            if lcb: lcb(msg)
            add_scrape_log(site["id"], started, datetime.now().isoformat(), 0, 0, "SKIP", "DNS unreachable")
            return {"site":name,"status":"SKIP","found":0,"added":0,"error":"DNS unreachable"}
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

                # If browser died during scrape, report as crash not empty result
                if tb._dead and not products:
                    raise RuntimeError("Browser crashed mid-scrape — no products collected")

            found  = len(products)
            for p in products: upsert_product(p)
            status, err = "SUCCESS", ""

        except Exception as e:
            found = 0; status = "ERROR"; err = str(e)
            # Distinguish crash vs network error in the log
            crash_sigs = ("connection closed", "target closed", "browser has been closed",
                          "crashed", "browser crashed")
            if any(sig in err.lower() for sig in crash_sigs):
                status = "CRASH"
                if lcb: lcb(f"  💥 [{name}] browser crashed — other sites unaffected (each has own browser)")
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
                            thread_name_prefix="scrape-worker") as pool:
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
