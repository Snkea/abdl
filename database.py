"""
ABDL Catalog System — database.py
Schema mirrors uploaded abdl_catalog.db exactly.
Added: shopping_list table with full CRUD + export helpers.
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "abdl_catalog.db"
DEFAULT_SCRAPE_INTERVAL = 259_200   # 3 days


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)  # 10s busy timeout prevents lock errors during scrape
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")   # belt-and-suspenders: 10s in ms
    return conn


def _col(conn, table, column):
    return any(r["name"] == column
               for r in conn.execute(f"PRAGMA table_info({table})").fetchall())


def _migrate(conn):
    c = conn.cursor()
    for col, td in [("brand_type","TEXT DEFAULT 'abdl'"),
                    ("discreet_shipping","INTEGER DEFAULT 0"),
                    ("free_sample","INTEGER DEFAULT 0")]:
        if not _col(conn, "brands", col):
            c.execute(f"ALTER TABLE brands ADD COLUMN {col} {td}")
    if not _col(conn, "scrape_sites", "site_type"):
        c.execute("ALTER TABLE scrape_sites ADD COLUMN site_type TEXT DEFAULT 'abdl'")
    if not _col(conn, "scrape_sites", "scrape_interval"):
        c.execute(f"ALTER TABLE scrape_sites ADD COLUMN scrape_interval INTEGER DEFAULT {DEFAULT_SCRAPE_INTERVAL}")
    for col, td in [("price","REAL"),("price_usd","REAL"),("currency","TEXT DEFAULT 'USD'"),
                    ("brand_type","TEXT DEFAULT 'abdl'"),("discreet_shipping","INTEGER DEFAULT 0"),
                    ("free_sample","INTEGER DEFAULT 0"),("size_xs","INTEGER DEFAULT 0"),
                    ("size_s","INTEGER DEFAULT 0"),("size_m","INTEGER DEFAULT 0"),
                    ("size_l","INTEGER DEFAULT 0"),("size_xl","INTEGER DEFAULT 0"),
                    ("size_xxl","INTEGER DEFAULT 0"),("size_xxxl","INTEGER DEFAULT 0")]:
        if not _col(conn, "products", col):
            c.execute(f"ALTER TABLE products ADD COLUMN {col} {td}")
    c.execute("UPDATE products SET price_usd=price WHERE price_usd IS NULL AND price IS NOT NULL")
    c.execute("UPDATE products SET price=price_usd WHERE price IS NULL AND price_usd IS NOT NULL")
    c.execute(f"UPDATE scrape_sites SET scrape_interval={DEFAULT_SCRAPE_INTERVAL} "
              f"WHERE scrape_interval IS NULL OR scrape_interval=86400")
    conn.commit()


def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS brands (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            name              TEXT UNIQUE NOT NULL,
            country           TEXT,
            website           TEXT,
            description       TEXT,
            logo_url          TEXT,
            brand_type        TEXT DEFAULT 'abdl',
            discreet_shipping INTEGER DEFAULT 0,
            free_sample       INTEGER DEFAULT 0,
            active            INTEGER DEFAULT 1,
            created_at        TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
            description TEXT, icon TEXT
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            brand_id INTEGER REFERENCES brands(id),
            category_id INTEGER REFERENCES categories(id),
            sku TEXT, description TEXT, url TEXT, image_url TEXT,
            price REAL, price_usd REAL, currency TEXT DEFAULT 'USD',
            size_range TEXT, size_xs INTEGER DEFAULT 0, size_s INTEGER DEFAULT 0,
            size_m INTEGER DEFAULT 0, size_l INTEGER DEFAULT 0,
            size_xl INTEGER DEFAULT 0, size_xxl INTEGER DEFAULT 0,
            size_xxxl INTEGER DEFAULT 0, absorbency_ml INTEGER,
            absorbency_label TEXT, tab_count INTEGER, features TEXT,
            materials TEXT, colors TEXT, patterns TEXT,
            in_stock INTEGER DEFAULT 1, rating REAL, review_count INTEGER DEFAULT 0,
            tags TEXT, source_site TEXT, brand_type TEXT DEFAULT 'abdl',
            discreet_shipping INTEGER DEFAULT 0, free_sample INTEGER DEFAULT 0,
            date_added TEXT DEFAULT (datetime('now')),
            last_updated TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS scrape_sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
            url TEXT NOT NULL, scrape_enabled INTEGER DEFAULT 1,
            site_type TEXT DEFAULT 'abdl', last_scraped TEXT,
            products_found INTEGER DEFAULT 0, scrape_interval INTEGER DEFAULT 259200,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS scrape_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER REFERENCES scrape_sites(id),
            started_at TEXT, finished_at TEXT, products_found INTEGER DEFAULT 0,
            products_added INTEGER DEFAULT 0, status TEXT, error_msg TEXT
        );
        CREATE TABLE IF NOT EXISTS wishlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER REFERENCES products(id),
            added_at TEXT DEFAULT (datetime('now')), notes TEXT
        );
        CREATE TABLE IF NOT EXISTS shopping_list (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
            quantity   INTEGER DEFAULT 1,
            notes      TEXT,
            added_at   TEXT DEFAULT (datetime('now'))
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(
            name, description, brand, tags, patterns,
            content='products', content_rowid='id'
        );
    """)
    _migrate(conn)
    c.executescript("""
        CREATE INDEX IF NOT EXISTS idx_products_brand   ON products(brand_id);
        CREATE INDEX IF NOT EXISTS idx_products_cat     ON products(category_id);
        CREATE INDEX IF NOT EXISTS idx_products_price   ON products(price_usd);
        CREATE INDEX IF NOT EXISTS idx_products_type    ON products(brand_type);
        CREATE INDEX IF NOT EXISTS idx_products_updated ON products(last_updated);
        CREATE INDEX IF NOT EXISTS idx_products_source  ON products(source_site);
        CREATE INDEX IF NOT EXISTS idx_shopping_prod    ON shopping_list(product_id);
    """)
    for name, desc, icon in [
        ("Diapers","Adult incontinence briefs / diapers","🩲"),
        ("ABDL Diapers","ABDL-themed diapers with decorative prints","🌟"),
        ("Pull-Ups / Training","Pull-up / training pant style briefs","⬆️"),
        ("Booster Pads","Diaper booster inserts and doublers","➕"),
        ("Onesies / Rompers","Snap-crotch onesies and rompers","👕"),
        ("Pacifiers","Adult-sized pacifiers / soothers","🍭"),
        ("Bottles","Adult baby bottles and sippy cups","🍼"),
        ("Bedding / Mattress","Waterproof pads, underpads, mattress covers","🛏️"),
        ("Accessories","Wipes, powder, rash cream, bags, misc","🎀"),
        ("Clothing","ABDL clothing, plastic pants, covers","👗"),
        ("Swim Diapers","Waterproof swim briefs for incontinence","🏊"),
        ("Underpads / Chux","Disposable and reusable bed/chair pads","📋"),
        ("Skincare / Medical","Barrier creams, wipes, powder, medical skincare","💊"),
    ]:
        c.execute("INSERT OR IGNORE INTO categories (name,description,icon) VALUES (?,?,?)", (name,desc,icon))
    for row in [
        ("Tykables","US","https://tykables.com","Premium ABDL diapers","abdl",0,0),
        ("ABU/ABUniverse","US","https://abuniverse.com","Adult Baby Universe pioneer ABDL brand","abdl",1,1),
        ("Rearz","CA","https://rearz.ca","Canadian ABDL brand, wide variety","abdl",1,0),
        ("Bambino","US","https://bambinodiapers.com","Classic ABDL diaper brand","abdl",1,1),
        ("BetterDry","DE","https://betterdrydiapers.com","High-absorbency European diapers","abdl",0,1),
        ("Crinklz","DE","https://www.crinklz.com","Colourful ABDL prints, plastic-backed","abdl",0,1),
        ("Fabine","DE","https://fabine.de","German ABDL diaper brand","abdl",0,0),
        ("Little For Big","US","https://littleforbig.com","ABDL clothing, onesies, accessories","abdl",1,0),
        ("MyDiaper","EU","https://mydiaper.eu","European ABDL brand","abdl",0,1),
        ("Snuggies","AU","https://snuggies.com.au","Australian ABDL brand","abdl",0,0),
        ("LittlePawz","US","","ABDL themed diapers","abdl",0,0),
        ("Cushies","US","https://abuniverse.com","Cushies ABDL diapers by ABU","abdl",1,1),
        ("ABDL Factory","US","https://abdlfactory.com","ABDL diaper and accessory retailer","abdl",1,0),
        ("NorthShore Care","US","https://northshorecare.com","Premium medical-grade incontinence","medical",1,1),
        ("Prevail","US","https://prevailproducts.com","First Quality medical incontinence","medical",1,0),
        ("Tranquility","US","https://tranquilityproducts.com","High-performance incontinence briefs","medical",1,1),
        ("Abena","DK","https://abenausa.com","Danish medical/ABDL crossover","both",0,1),
        ("TENA","SE","https://tena.us","Global incontinence care by Essity","medical",1,0),
        ("Depend","US","https://depend.com","Kimberly-Clark consumer incontinence","medical",1,0),
        ("Attends","US","https://attends.com","Medical-grade incontinence","medical",1,0),
        ("Seni","PL","https://seni.com","Polish medical incontinence brand","medical",0,1),
        ("Dry 24/7","DE","https://dry247.eu","German high-capacity incontinence","both",0,1),
        ("Unique Wellness","US","https://uniquewellness.com","Ultra-absorbent incontinence briefs","medical",1,1),
        ("Gary Active","US","https://garyactivewear.com","Reusable washable incontinence wear","medical",1,0),
        ("Medline","US","https://medline.com","Medical supply incontinence line","medical",1,0),
        ("MoliCare","DE","https://molicare.com","Hartmann MoliCare premium incontinence","medical",0,1),
        ("Cardinal Health","US","https://cardinalhealth.com","Medical incontinence supplies","medical",1,0),
        # Mainstream retail brands (baby/incontinence)
        ("Huggies","US","https://huggies.com","Kimberly-Clark baby & adult care","both",1,0),
        ("Pampers","US","https://pampers.com","P&G premium baby care","both",1,0),
        ("Luvs","US","https://luvs.com","P&G value baby diapers","medical",1,0),
        ("Cuties","US","https://cutiesproducts.com","Quality youth and adult briefs","medical",1,0),
        ("Assurance","US","https://walmart.com","Walmart store brand incontinence","medical",1,0),
        ("Equate","US","https://walmart.com","Walmart store brand health care","medical",1,0),
        ("Up & Up","US","https://target.com","Target store brand baby/adult care","medical",1,0),
        ("Always Discreet","US","https://always.com","P&G incontinence range","medical",1,0),
        ("Poise","US","https://poise.com","Kimberly-Clark light incontinence","medical",1,0),
        ("GoodNites","US","https://goodnites.com","Kimberly-Clark youth nighttime","both",1,0),
        ("Pampers Easy Ups","US","https://pampers.com","P&G training pants","both",1,0),
        ("Seventh Generation","US","https://seventhgeneration.com","Eco-friendly diapers","medical",1,0),
        ("Honest Company","US","https://honest.com","Plant-based baby care","medical",1,0),
        ("Kirkland","US","https://costco.com","Costco store brand diapers","medical",0,0),
    ]:
        c.execute("INSERT OR IGNORE INTO brands "
                  "(name,country,website,description,brand_type,discreet_shipping,free_sample) "
                  "VALUES (?,?,?,?,?,?,?)", row)
    for name, url, enabled, stype in [
        ("Tykables Store","https://tykables.com",1,"abdl"),
        ("ABUniverse Store","https://abuniverse.com",1,"abdl"),
        ("Rearz Store","https://rearz.ca",1,"abdl"),
        ("Bambino Diapers","https://bambinodiapers.com/shop",1,"abdl"),
        ("BetterDry","https://www.betterdrydiapers.com",1,"abdl"),
        ("Crinklz","https://www.crinklz.com/shop",1,"abdl"),
        ("Little For Big","https://www.littleforbig.com",1,"abdl"),
        ("ABDL Factory","https://abdlfactory.com",1,"abdl"),
        ("Fabine","https://fabine.de",1,"abdl"),
        ("MyDiaper","https://mydiaper.eu",1,"abdl"),
        ("NorthShore Care Supply","https://northshorecare.com",1,"medical"),
        ("XP Medical","https://www.xpmedical.com",1,"medical"),
        ("HDIS","https://www.hdis.com/incontinence",1,"medical"),
        ("Personally Delivered","https://www.personallydelivered.com",1,"medical"),
        ("Parentgiving","https://www.parentgiving.com",1,"medical"),
        ("Vitality Medical","https://www.vitalitymedical.com/briefs.html",1,"medical"),
        ("Health Products For You","https://www.healthproductsforyou.com",1,"medical"),
        ("Adult Diaper Superstore","https://www.adultdiapersuperstore.com",1,"medical"),
        ("Carewell","https://www.carewell.com",1,"medical"),
        ("Tranquility Products","https://www.tranquilityproducts.com",1,"medical"),
        ("Unique Wellness","https://wellnessbriefs.com",1,"medical"),
        ("DiapersEtc","https://www.diapersetc.com",1,"medical"),
        ("Abena USA","https://www.abenausa.com",1,"both"),
        # Mainstream retail — baby / incontinence sections
        ("Walmart Baby",         "https://www.walmart.com/cp/baby-products/5427",  1,"medical"),
        ("Walmart Incontinence", "https://www.walmart.com/cp/incontinence/1101660",1,"medical"),
        ("Walmart Adult Diapers","https://www.walmart.com/search?q=adult+diapers",  1,"medical"),
        ("Target Baby",          "https://www.target.com/c/baby/-/N-5xsx0",         1,"medical"),
        ("Target Adult Care",    "https://www.target.com/c/incontinence-care-adult/-/N-5xu1u",1,"medical"),
        ("Target Diapers",       "https://www.target.com/s?searchTerm=adult+diapers",1,"medical"),
        ("Amazon Baby Diapers",  "https://www.amazon.com/s?k=adult+diapers+large",   1,"medical"),
        ("Amazon Baby Products", "https://www.amazon.com/s?k=baby+diapers+onesie",   1,"medical"),
        ("Amazon ABDL",          "https://www.amazon.com/s?k=ABDL+diapers+adult+baby",1,"abdl"),
        ("CVS Baby & Adult Care","https://www.cvs.com/shop/incontinence",             1,"medical"),
        ("Walgreens Incontinence","https://www.walgreens.com/store/c/incontinence/ID=361607-tier2",1,"medical"),
        ("Rite Aid Baby & Adult","https://www.riteaid.com/shop/baby-incontinence/incontinence",1,"medical"),
        ("Dollar General Baby",  "https://www.dollargeneral.com/category/baby-diapers-training-pants.html",1,"medical"),
        ("Costco Diapers",       "https://www.costco.com/adult-incontinence.html",    1,"medical"),
        ("Buy Buy Baby",         "https://www.buybuybaby.com/store/s/diaper",         1,"medical"),
    ]:
        c.execute("""INSERT INTO scrape_sites (name,url,scrape_enabled,site_type,scrape_interval)
                     VALUES (?,?,?,?,?)
                     ON CONFLICT(name) DO UPDATE SET
                         url=excluded.url, scrape_enabled=excluded.scrape_enabled,
                         site_type=excluded.site_type""",
                  (name, url, enabled, stype, DEFAULT_SCRAPE_INTERVAL))
    conn.commit()
    conn.close()


# ── Smart refresh ─────────────────────────────────────────────────────────────

def should_scrape_site(site):
    if not site.get("scrape_enabled"): return False
    last = site.get("last_scraped")
    if not last: return True
    try:
        interval = site.get("scrape_interval") or DEFAULT_SCRAPE_INTERVAL
        return datetime.now() >= datetime.fromisoformat(last) + timedelta(seconds=interval)
    except Exception: return True


def next_scrape_time(site):
    if not site.get("scrape_enabled"): return "disabled"
    last = site.get("last_scraped")
    if not last: return "now (never scraped)"
    try:
        interval = site.get("scrape_interval") or DEFAULT_SCRAPE_INTERVAL
        nxt  = datetime.fromisoformat(last) + timedelta(seconds=interval)
        diff = nxt - datetime.now()
        if diff.total_seconds() <= 0: return "due now"
        h = int(diff.total_seconds() // 3600)
        return f"< 1 hour" if h < 1 else (f"in {h}h" if h < 24 else f"in {h//24}d {h%24}h")
    except Exception: return "unknown"


# ── Products CRUD ─────────────────────────────────────────────────────────────

def _resolve_brand_id(conn, brand_name):
    if not brand_name: return None
    row = conn.execute("SELECT id FROM brands WHERE name=? COLLATE NOCASE LIMIT 1", (brand_name,)).fetchone()
    if row: return row["id"]
    key = brand_name.lower()
    for r in conn.execute("SELECT id, name FROM brands").fetchall():
        n = r["name"].lower()
        if key in n or n in key: return r["id"]
    return None


def _resolve_category_id(conn, cat_name):
    if not cat_name: return None
    row = conn.execute("SELECT id FROM categories WHERE name=? COLLATE NOCASE LIMIT 1", (cat_name,)).fetchone()
    if row: return row["id"]
    key = cat_name.lower()
    for r in conn.execute("SELECT id, name FROM categories").fetchall():
        if key in r["name"].lower() or r["name"].lower() in key: return r["id"]
    return None


def _parse_size_flags(size_range):
    flags = dict(size_xs=0,size_s=0,size_m=0,size_l=0,size_xl=0,size_xxl=0,size_xxxl=0)
    if not size_range: return flags
    u = size_range.upper()
    if "XS"   in u: flags["size_xs"]   = 1
    if "XXXL" in u: flags["size_xxxl"] = 1
    if "XXL"  in u: flags["size_xxl"]  = 1
    if "XL"   in u: flags["size_xl"]   = 1
    for t in u.replace("/"," ").replace(","," ").split():
        if t.strip() == "L": flags["size_l"] = 1
        if t.strip() == "M": flags["size_m"] = 1
        if t.strip() == "S": flags["size_s"] = 1
    return flags


def upsert_product(data):
    data = dict(data)
    conn = get_connection()
    if "brand_name" in data and "brand_id" not in data:
        data["brand_id"] = _resolve_brand_id(conn, data.pop("brand_name"))
    else:
        data.pop("brand_name", None)
        if data.get("brand_id"):
            if not conn.execute("SELECT 1 FROM brands WHERE id=?", (data["brand_id"],)).fetchone():
                data["brand_id"] = None
    if "category_name" in data and "category_id" not in data:
        data["category_id"] = _resolve_category_id(conn, data.pop("category_name"))
    else:
        data.pop("category_name", None)
        if data.get("category_id"):
            if not conn.execute("SELECT 1 FROM categories WHERE id=?", (data["category_id"],)).fetchone():
                data["category_id"] = None
    if "price_usd" in data and "price" not in data: data["price"] = data["price_usd"]
    elif "price" in data and "price_usd" not in data: data["price_usd"] = data["price"]
    data.setdefault("currency", "USD")
    if data.get("size_range"):
        for k, v in _parse_size_flags(data["size_range"]).items():
            data.setdefault(k, v)
    valid = {r["name"] for r in conn.execute("PRAGMA table_info(products)").fetchall()}
    data = {k: v for k, v in data.items() if k in valid}
    url = data.get("url", "")
    existing = conn.execute("SELECT id FROM products WHERE url=?", (url,)).fetchone() if url else None
    now = datetime.now().isoformat()
    try:
        if existing:
            pid = existing["id"]; data["last_updated"] = now
            sets = ", ".join(f"{k}=?" for k in data if k != "id")
            conn.execute(f"UPDATE products SET {sets} WHERE id=?",
                         [v for k,v in data.items() if k!="id"] + [pid])
        else:
            data.setdefault("date_added", now); data["last_updated"] = now
            cols = ", ".join(data.keys()); ph = ", ".join("?"*len(data))
            cur = conn.execute(f"INSERT INTO products ({cols}) VALUES ({ph})", list(data.values()))
            pid = cur.lastrowid
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally: conn.close()
    return pid


def get_all_products(search="", brand_id=None, category_id=None, in_stock_only=False,
                     sort="name", brand_type=None, size_filter=None,
                     discreet_only=False, free_sample_only=False, max_price=None):
    conn = get_connection()
    params, where = [], []
    if search:
        where.append("(p.name LIKE ? OR p.description LIKE ? OR p.tags LIKE ?)")
        params += [f"%{search}%"]*3
    if brand_id:   where.append("p.brand_id=?");    params.append(brand_id)
    if category_id:where.append("p.category_id=?"); params.append(category_id)
    if in_stock_only: where.append("p.in_stock=1")
    if brand_type and brand_type != "all":
        where.append("(p.brand_type=? OR p.brand_type='both')"); params.append(brand_type)
    if size_filter and size_filter != "all":
        col = "size_" + size_filter.lower().replace("-","").replace("/","")
        if col in ("size_xs","size_s","size_m","size_l","size_xl","size_xxl","size_xxxl"):
            where.append(f"p.{col}=1")
    if discreet_only:    where.append("(p.discreet_shipping=1 OR b.discreet_shipping=1)")
    if free_sample_only: where.append("(p.free_sample=1 OR b.free_sample=1)")
    if max_price and max_price > 0:
        where.append("(COALESCE(p.price_usd,p.price)<=?)"); params.append(max_price)
    order = {"name":"p.name ASC","price":"COALESCE(p.price_usd,p.price) ASC",
             "newest":"p.date_added DESC","rating":"p.rating DESC"}.get(sort,"p.name ASC")
    sql = f"""SELECT p.*, COALESCE(p.price_usd,p.price) AS display_price,
               b.name AS brand_name, b.brand_type AS b_btype,
               b.discreet_shipping AS b_discreet, b.free_sample AS b_free_sample,
               b.website AS b_website,
               c.name AS category_name, c.icon AS category_icon
        FROM products p
        LEFT JOIN brands b ON p.brand_id=b.id
        LEFT JOIN categories c ON p.category_id=c.id
        {"WHERE "+" AND ".join(where) if where else ""}
        ORDER BY {order}"""
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_product_by_id(pid):
    conn = get_connection()
    row = conn.execute("""SELECT p.*, COALESCE(p.price_usd,p.price) AS display_price,
               b.name AS brand_name, b.brand_type AS b_btype,
               b.discreet_shipping AS b_discreet, b.free_sample AS b_free_sample,
               b.website AS b_website, c.name AS category_name, c.icon AS category_icon
        FROM products p LEFT JOIN brands b ON p.brand_id=b.id
        LEFT JOIN categories c ON p.category_id=c.id WHERE p.id=?""", (pid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_brands(brand_type=None):
    conn = get_connection()
    if brand_type and brand_type != "all":
        rows = conn.execute("SELECT * FROM brands WHERE brand_type=? OR brand_type='both' ORDER BY name", (brand_type,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM brands ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_categories():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_scrape_sites(site_type=None):
    conn = get_connection()
    if site_type and site_type != "all":
        rows = conn.execute("SELECT * FROM scrape_sites WHERE site_type=? ORDER BY name", (site_type,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM scrape_sites ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_scrape_log(site_id, started, finished, found, added, status, error=""):
    conn = get_connection()
    conn.execute("INSERT INTO scrape_log (site_id,started_at,finished_at,products_found,products_added,status,error_msg) "
                 "VALUES (?,?,?,?,?,?,?)", (site_id,started,finished,found,added,status,error))
    conn.execute("UPDATE scrape_sites SET last_scraped=?, products_found=? WHERE id=?", (finished,found,site_id))
    conn.commit(); conn.close()


def get_stats():
    conn = get_connection()
    s = {}
    s["total_products"]    = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    s["abdl_products"]     = conn.execute("SELECT COUNT(*) FROM products WHERE brand_type='abdl'").fetchone()[0]
    s["medical_products"]  = conn.execute("SELECT COUNT(*) FROM products WHERE brand_type IN ('medical','both')").fetchone()[0]
    s["total_brands"]      = conn.execute("SELECT COUNT(*) FROM brands").fetchone()[0]
    s["in_stock"]          = conn.execute("SELECT COUNT(*) FROM products WHERE in_stock=1").fetchone()[0]
    s["discreet_count"]    = conn.execute("SELECT COUNT(*) FROM products WHERE discreet_shipping=1").fetchone()[0]
    s["free_sample_count"] = conn.execute("SELECT COUNT(*) FROM products WHERE free_sample=1").fetchone()[0]
    s["categories"]        = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    s["last_scrape"]       = conn.execute("SELECT MAX(last_scraped) FROM scrape_sites").fetchone()[0] or "Never"
    s["shopping_list_count"] = conn.execute("SELECT COALESCE(SUM(quantity),0) FROM shopping_list").fetchone()[0]
    sites = get_scrape_sites()
    s["sites_due"] = sum(1 for st in sites if should_scrape_site(st))
    rows = conn.execute("""SELECT b.name, COUNT(p.id) AS cnt FROM products p
           JOIN brands b ON p.brand_id=b.id GROUP BY b.id ORDER BY cnt DESC LIMIT 10""").fetchall()
    s["top_brands"] = [dict(r) for r in rows]
    log_rows = conn.execute("""SELECT sl.*, ss.name AS site_name, ss.site_type
           FROM scrape_log sl JOIN scrape_sites ss ON sl.site_id=ss.id
           ORDER BY sl.started_at DESC LIMIT 5""").fetchall()
    s["recent_scrapes"] = [dict(r) for r in log_rows]
    conn.close()
    return s


def delete_product(pid):
    conn = get_connection()
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit(); conn.close()


def get_scrape_log(limit=50):
    conn = get_connection()
    rows = conn.execute("""SELECT sl.*, ss.name AS site_name, ss.site_type,
               ss.last_scraped, ss.scrape_interval
        FROM scrape_log sl JOIN scrape_sites ss ON sl.site_id=ss.id
        ORDER BY sl.started_at DESC LIMIT ?""", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Shopping list CRUD ────────────────────────────────────────────────────────

def get_shopping_list():
    """Return all shopping list items joined with product + brand details."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT sl.id AS list_id, sl.quantity, sl.notes, sl.added_at,
               p.id AS product_id, p.name, p.url, p.source_site, p.brand_type,
               p.discreet_shipping, p.free_sample, p.size_range,
               COALESCE(p.price_usd, p.price) AS unit_price,
               b.name AS brand_name, b.website AS brand_website,
               c.name AS category_name, c.icon AS category_icon
        FROM shopping_list sl
        JOIN products p ON sl.product_id = p.id
        LEFT JOIN brands b ON p.brand_id = b.id
        LEFT JOIN categories c ON p.category_id = c.id
        ORDER BY sl.added_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_to_shopping_list(product_id, quantity=1, notes=""):
    """Add product to list or increment qty if already present."""
    conn = get_connection()
    existing = conn.execute(
        "SELECT id, quantity FROM shopping_list WHERE product_id=?", (product_id,)).fetchone()
    if existing:
        conn.execute("UPDATE shopping_list SET quantity=? WHERE id=?",
                     (existing["quantity"] + quantity, existing["id"]))
        lid = existing["id"]
    else:
        cur = conn.execute(
            "INSERT INTO shopping_list (product_id,quantity,notes) VALUES (?,?,?)",
            (product_id, quantity, notes))
        lid = cur.lastrowid
    conn.commit(); conn.close()
    return lid


def update_shopping_list_qty(list_id, quantity):
    conn = get_connection()
    if quantity <= 0:
        conn.execute("DELETE FROM shopping_list WHERE id=?", (list_id,))
    else:
        conn.execute("UPDATE shopping_list SET quantity=? WHERE id=?", (quantity, list_id))
    conn.commit(); conn.close()


def remove_from_shopping_list(list_id):
    conn = get_connection()
    conn.execute("DELETE FROM shopping_list WHERE id=?", (list_id,))
    conn.commit(); conn.close()


def clear_shopping_list():
    conn = get_connection()
    conn.execute("DELETE FROM shopping_list")
    conn.commit(); conn.close()


def shopping_list_has(product_id):
    """Return qty in list for given product_id, or 0."""
    conn = get_connection()
    row = conn.execute("SELECT quantity FROM shopping_list WHERE product_id=?", (product_id,)).fetchone()
    conn.close()
    return row["quantity"] if row else 0


def get_quick_status():
    """Lightweight 3-query status for the main window status bar (no full stats calculation)."""
    conn = get_connection()
    total    = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    abdl     = conn.execute("SELECT COUNT(*) FROM products WHERE brand_type='abdl'").fetchone()[0]
    medical  = conn.execute("SELECT COUNT(*) FROM products WHERE brand_type IN ('medical','both')").fetchone()[0]
    cart     = conn.execute("SELECT COALESCE(SUM(quantity),0) FROM shopping_list").fetchone()[0]
    due_row  = conn.execute(
        "SELECT COUNT(*) FROM scrape_sites WHERE scrape_enabled=1 AND "
        "(last_scraped IS NULL OR "
        " datetime(last_scraped, '+' || scrape_interval || ' seconds') < datetime('now'))"
    ).fetchone()[0]
    conn.close()
    return {"total": total, "abdl": abdl, "medical": medical, "cart": int(cart), "due": due_row}


# ── Database management helpers ───────────────────────────────────────────────

BROWSABLE_TABLES = {
    "products":     "Products",
    "brands":       "Brands",
    "categories":   "Categories",
    "scrape_sites": "Scrape Sites",
    "scrape_log":   "Scrape Log",
    "shopping_list":"Shopping List",
    "wishlist":     "Wishlist",
}


def get_table_info(table):
    if table not in BROWSABLE_TABLES:
        return []
    conn = get_connection()
    cols = [dict(r) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    conn.close()
    return cols


def get_table_rows(table, search="", limit=200, offset=0):
    if table not in BROWSABLE_TABLES:
        return [], 0
    conn = get_connection()
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    where = ""; params_count = []; params_rows = []
    if search:
        text_cols = [c for c in cols if c not in ("id","brand_id","category_id","site_id",
                                                    "product_id","scrape_enabled","in_stock")]
        if text_cols:
            clauses = " OR ".join(f"{c} LIKE ?" for c in text_cols[:6])
            where = f"WHERE {clauses}"
            term = [f"%{search}%"] * len(text_cols[:6])
            params_count = term; params_rows = term
    total = conn.execute(f"SELECT COUNT(*) FROM {table} {where}", params_count).fetchone()[0]
    rows  = conn.execute(
        f"SELECT * FROM {table} {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params_rows + [limit, offset]).fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def delete_rows(table, row_ids):
    if table not in BROWSABLE_TABLES or not row_ids:
        return 0
    conn = get_connection()
    ph = ",".join("?" * len(row_ids))
    cur = conn.execute(f"DELETE FROM {table} WHERE id IN ({ph})", row_ids)
    conn.commit(); deleted = cur.rowcount; conn.close()
    return deleted


def toggle_site_enabled(site_id):
    conn = get_connection()
    cur_val = conn.execute("SELECT scrape_enabled FROM scrape_sites WHERE id=?", (site_id,)).fetchone()
    if not cur_val:
        conn.close(); return None
    new_val = 0 if cur_val[0] else 1
    conn.execute("UPDATE scrape_sites SET scrape_enabled=? WHERE id=?", (new_val, site_id))
    conn.commit(); conn.close()
    return new_val


def update_site_url(site_id, new_url):
    conn = get_connection()
    conn.execute("UPDATE scrape_sites SET url=? WHERE id=?", (new_url, site_id))
    conn.commit(); conn.close()


def add_scrape_site(name, url, site_type="abdl", enabled=1):
    conn = get_connection()
    cur = conn.execute(
        "INSERT OR IGNORE INTO scrape_sites (name,url,scrape_enabled,site_type,scrape_interval) "
        "VALUES (?,?,?,?,?)", (name, url, enabled, site_type, DEFAULT_SCRAPE_INTERVAL))
    conn.commit(); lid = cur.lastrowid; conn.close()
    return lid


def get_db_health():
    conn = get_connection()
    h = {}
    h["integrity"]      = conn.execute("PRAGMA integrity_check").fetchone()[0]
    h["fk_violations"]  = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    h["wal_mode"]       = conn.execute("PRAGMA journal_mode").fetchone()[0]
    h["page_size"]      = conn.execute("PRAGMA page_size").fetchone()[0]
    h["page_count"]     = conn.execute("PRAGMA page_count").fetchone()[0]
    h["db_size_kb"]     = round(h["page_size"] * h["page_count"] / 1024, 1)
    h["freelist_count"] = conn.execute("PRAGMA freelist_count").fetchone()[0]
    h["tables"] = {}
    for tbl in BROWSABLE_TABLES:
        try: h["tables"][tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        except Exception: h["tables"][tbl] = "error"
    h["indexes"] = [dict(r) for r in conn.execute(
        "SELECT name, tbl_name FROM sqlite_master WHERE type='index' ORDER BY tbl_name").fetchall()]
    h["products_no_brand"]    = conn.execute("SELECT COUNT(*) FROM products WHERE brand_id IS NULL").fetchone()[0]
    h["products_no_price"]    = conn.execute(
        "SELECT COUNT(*) FROM products WHERE price_usd IS NULL AND price IS NULL").fetchone()[0]
    h["products_no_category"] = conn.execute("SELECT COUNT(*) FROM products WHERE category_id IS NULL").fetchone()[0]
    conn.close()
    return h


def vacuum_db():
    import sqlite3 as _sq3
    conn = _sq3.connect(DB_PATH, isolation_level=None)
    conn.execute("VACUUM"); conn.close()




def fix_missing_prices():
    conn = get_connection()
    conn.execute("UPDATE products SET price_usd=price WHERE price_usd IS NULL AND price IS NOT NULL")
    conn.execute("UPDATE products SET price=price_usd WHERE price IS NULL AND price_usd IS NOT NULL")
    conn.commit(); conn.close()


def fix_missing_brands():
    conn = get_connection()
    sites = conn.execute("SELECT * FROM scrape_sites").fetchall()
    fixed = 0
    for site in sites:
        nm = site["name"].replace(" Store","").replace(" Supply","").strip()
        brand = conn.execute(
            "SELECT id FROM brands WHERE name LIKE ? OR name LIKE ? LIMIT 1",
            (f"%{nm.split()[0]}%", f"%{nm}%")).fetchone()
        if brand:
            cur = conn.execute(
                "UPDATE products SET brand_id=? WHERE brand_id IS NULL AND source_site=?",
                (brand["id"], site["name"]))
            fixed += cur.rowcount
    conn.commit(); conn.close()
    return fixed


def get_source_sites_list():
    """Return list of dicts {source_site, cnt} for the products browser filter."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT source_site, COUNT(*) AS cnt FROM products "
        "WHERE source_site IS NOT NULL GROUP BY source_site ORDER BY source_site"
    ).fetchall()
    conn.close()
    return [{"source_site": r["source_site"], "cnt": r["cnt"]} for r in rows]


def get_products_paginated(page=0, per_page=200, search="", source_site=None, brand_type=None):
    """Return (total, rows) for the DB management Products browser."""
    conn = get_connection()
    wheres = []; params = []
    if search:
        try:
            fts = conn.execute(
                "SELECT rowid FROM products_fts WHERE products_fts MATCH ? LIMIT 10000", (search + "*",)
            ).fetchall()
            ids = [r[0] for r in fts]
        except Exception:
            ids = []
        if ids:
            wheres.append(f"p.rowid IN ({','.join('?'*len(ids))})"); params += ids
        else:
            # FTS unavailable or empty — fall back to LIKE on name/description
            wheres.append("(p.name LIKE ? OR p.description LIKE ?)"); params += [f"%{search}%", f"%{search}%"]
    if source_site:
        wheres.append("p.source_site = ?"); params.append(source_site)
    if brand_type:
        wheres.append("p.brand_type = ?"); params.append(brand_type.lower())
    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    total = conn.execute(
        f"SELECT COUNT(*) FROM products p {where_sql}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"""SELECT p.id, p.name, b.name AS brand_name, c.name AS category_name,
                   p.price, p.currency, p.brand_type, p.in_stock, p.source_site
            FROM products p
            LEFT JOIN brands b ON b.id = p.brand_id
            LEFT JOIN categories c ON c.id = p.category_id
            {where_sql}
            ORDER BY p.id DESC LIMIT ? OFFSET ?""",
        params + [per_page, page * per_page]
    ).fetchall()
    conn.close()
    return total, [dict(r) for r in rows]


# ── Site management ────────────────────────────────────────────────────────────

def enable_site(site_id, enabled: bool):
    conn = get_connection()
    conn.execute("UPDATE scrape_sites SET scrape_enabled=? WHERE id=?", (1 if enabled else 0, site_id))
    conn.commit(); conn.close()


def reset_site_schedule(site_id):
    """Clear last_scraped so site will be scraped on next run."""
    conn = get_connection()
    conn.execute("UPDATE scrape_sites SET last_scraped=NULL WHERE id=?", (site_id,))
    conn.commit(); conn.close()


def delete_site(site_id):
    conn = get_connection()
    conn.execute("DELETE FROM scrape_sites WHERE id=?", (site_id,))
    conn.commit(); conn.close()


def update_site(site_id, name, url, enabled, site_type, interval):
    conn = get_connection()
    conn.execute(
        "UPDATE scrape_sites SET name=?,url=?,scrape_enabled=?,site_type=?,scrape_interval=? WHERE id=?",
        (name, url, 1 if enabled else 0, site_type, int(interval), site_id))
    conn.commit(); conn.close()


def add_site(name, url, enabled=True, site_type="abdl", interval=None):
    if interval is None:
        interval = DEFAULT_SCRAPE_INTERVAL
    conn = get_connection()
    cur = conn.execute(
        "INSERT OR IGNORE INTO scrape_sites (name,url,scrape_enabled,site_type,scrape_interval) "
        "VALUES (?,?,?,?,?)", (name, url, 1 if enabled else 0, site_type, int(interval)))
    conn.commit(); lid = cur.lastrowid; conn.close()
    return lid


# ── Product management ─────────────────────────────────────────────────────────

def delete_products_by_ids(ids):
    if not ids: return 0
    conn = get_connection()
    ph = ",".join("?" * len(ids))
    cur = conn.execute(f"DELETE FROM products WHERE id IN ({ph})", list(ids))
    conn.commit(); n = cur.rowcount; conn.close()
    return n


def delete_products_by_source(source_site):
    conn = get_connection()
    cur = conn.execute("DELETE FROM products WHERE source_site=?", (source_site,))
    conn.commit(); n = cur.rowcount; conn.close()
    return n


def delete_all_products():
    conn = get_connection()
    cur = conn.execute("DELETE FROM products")
    conn.commit(); n = cur.rowcount; conn.close()
    return n


# ── DB health / maintenance ────────────────────────────────────────────────────

def get_db_health():
    """Return health dict matching keys expected by the UI."""
    import os
    conn = get_connection()
    tables = {}
    for tbl in ("products","brands","categories","scrape_sites","scrape_log","shopping_list","wishlist"):
        try: tables[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        except Exception: tables[tbl] = 0
    wal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    page_count= conn.execute("PRAGMA page_count").fetchone()[0]
    freelist  = conn.execute("PRAGMA freelist_count").fetchone()[0]
    db_bytes  = page_size * page_count
    conn.close()
    # WAL file size
    wal_path = DB_PATH + "-wal"
    wal_bytes = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
    return {
        "path":              DB_PATH,
        "size_mb":           round(db_bytes / 1024 / 1024, 2),
        "wal_mb":            round(wal_bytes / 1024 / 1024, 2),
        "wal_mode":          wal_mode,
        "page_size":         page_size,
        "page_count":        page_count,
        "freelist_count":    freelist,
        "tables":            tables,
        # convenience flat keys for UI grid
        "rows_products":     tables.get("products", 0),
        "rows_brands":       tables.get("brands", 0),
        "rows_categories":   tables.get("categories", 0),
        "rows_scrape_sites": tables.get("scrape_sites", 0),
        "rows_scrape_log":   tables.get("scrape_log", 0),
        "rows_shopping_list":tables.get("shopping_list", 0),
    }


def db_integrity_check():
    """Return list of result strings from PRAGMA integrity_check."""
    conn = get_connection()
    rows = conn.execute("PRAGMA integrity_check").fetchall()
    fk   = conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()
    msgs = [f"integrity_check: {r[0]}" for r in rows]
    if fk:
        msgs += [f"FK violation: table={r[0]} rowid={r[1]} parent={r[2]} fkid={r[3]}" for r in fk]
    else:
        msgs.append("✓ No foreign key violations")
    return msgs


def rebuild_fts():
    """Rebuild FTS5 index; handles brand col mismatch by recreating FTS table if needed."""
    conn = get_connection()
    # First try standard rebuild
    try:
        conn.execute("INSERT INTO products_fts(products_fts) VALUES('rebuild')")
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        conn.close()
        return n
    except Exception:
        pass
    # Rebuild failed — likely because FTS was created with 'brand' col but products has 'brand_id'
    # Solution: drop FTS table and recreate without brand col, then populate
    try:
        conn.execute("DROP TABLE IF EXISTS products_fts")
        conn.execute("""
            CREATE VIRTUAL TABLE products_fts USING fts5(
                name, description, tags, patterns,
                content='products', content_rowid='id'
            )
        """)
        conn.execute("""
            INSERT INTO products_fts(rowid, name, description, tags, patterns)
            SELECT id, coalesce(name,''), coalesce(description,''),
                   coalesce(tags,''), coalesce(patterns,'')
            FROM products
        """)
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        conn.close()
        return n
    except Exception as e2:
        conn.close()
        raise RuntimeError(f"FTS rebuild failed: {e2}") from e2


def db_checkpoint():
    """Force WAL checkpoint. Returns dict with log/checkpointed frame counts."""
    conn = get_connection()
    row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    conn.close()
    return {"busy": row[0], "log": row[1], "checkpointed": row[2]}


def db_vacuum():
    """Run VACUUM (outside WAL). Returns new DB size in MB."""
    import sqlite3 as _sq3, os
    conn = _sq3.connect(DB_PATH, isolation_level=None)
    conn.execute("VACUUM"); conn.close()
    page_size  = _sq3.connect(DB_PATH).execute("PRAGMA page_size").fetchone()[0]
    page_count = _sq3.connect(DB_PATH).execute("PRAGMA page_count").fetchone()[0]
    return round(page_size * page_count / 1024 / 1024, 2)


def db_backup(dest_path):
    """Backup DB to dest_path using sqlite3 backup API. Returns size in MB."""
    import sqlite3 as _sq3, os
    src = _sq3.connect(DB_PATH)
    dst = _sq3.connect(dest_path)
    src.backup(dst); src.close(); dst.close()
    return round(os.path.getsize(dest_path) / 1024 / 1024, 2)


reindex_fts = rebuild_fts  # alias kept for backward compat
