"""
CrinkleDen — database.py  v3.0
Schema v3.0 — abdl_catalog.db
Added: shopping_list, image_library, tag system, download jobs, site credentials.
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_VERSION = "4.0"   # checked by ui.py at startup

# DB lives next to database.py (i.e. I:\abdl\abdl_catalog.db).
# If the folder doesn't exist for some reason, create it so SQLite
# doesn't raise "unable to open database file".
DB_PATH = Path(__file__).resolve().parent / "abdl_catalog.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_SCRAPE_INTERVAL = 259_200   # 3 days


def get_connection():
    # Ensure the parent directory exists every time (covers mapped drives,
    # USB sticks, first-run scenarios, and moved installs).
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
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


# Versioned migrations — each runs exactly once, tracked in schema_version table
_MIGRATIONS = [
    (1, "Add price_was and on_sale to products", [
        "ALTER TABLE products ADD COLUMN price_was REAL",
        "ALTER TABLE products ADD COLUMN on_sale   INTEGER DEFAULT 0",
    ]),
    (2, "Add wishlist notes and target_price", [
        "ALTER TABLE wishlist ADD COLUMN target_price REAL",
        "ALTER TABLE wishlist ADD COLUMN notified_at  TEXT",
    ]),
    (3, "Add gender column to products", [
        "ALTER TABLE products ADD COLUMN gender TEXT DEFAULT 'unisex'",
    ]),
    (4, "Add scrape_sites brand_type column", [
        "ALTER TABLE scrape_sites ADD COLUMN brand_type TEXT DEFAULT 'abdl'",
    ]),
    (5, "Add products rating columns", [
        "ALTER TABLE products ADD COLUMN rating       REAL",
        "ALTER TABLE products ADD COLUMN review_count INTEGER DEFAULT 0",
    ]),
    (6, "Add website to brands for old DBs", [
        "ALTER TABLE brands ADD COLUMN website TEXT",
    ]),
    (7, "Add notes/target_price/notified_at to wishlist for old DBs", [
        "ALTER TABLE wishlist ADD COLUMN notes        TEXT",
        "ALTER TABLE wishlist ADD COLUMN target_price REAL",
        "ALTER TABLE wishlist ADD COLUMN notified_at  TEXT",
    ]),
    (8, "Add brand active flag", [
        "ALTER TABLE brands ADD COLUMN active INTEGER DEFAULT 1",
    ]),
]


def _run_migrations(conn):
    """
    Run any migrations that haven't been applied yet.
    schema_version table tracks which have run.
    Safe to call multiple times — skips already-applied migrations.
    """
    # Create schema_version if it somehow doesn't exist yet
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT DEFAULT (datetime('now')),
            description TEXT
        )
    """)
    applied = {r[0] for r in conn.execute(
        "SELECT version FROM schema_version").fetchall()}
    for ver, desc, stmts in _MIGRATIONS:
        if ver in applied:
            continue
        for stmt in stmts:
            try:
                conn.execute(stmt)
            except Exception:
                pass   # column may already exist — that's fine
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?,?)",
            (ver, desc))
    conn.commit()

def init_db():
    # Guarantee the DB file's parent directory exists before first connect.
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
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
            product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
            target_price REAL,
            notified_at  TEXT,
            notes        TEXT,
            added_at     TEXT DEFAULT (datetime('now'))
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
        CREATE TABLE IF NOT EXISTS product_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
            image_data BLOB, image_url TEXT, filename TEXT,
            mime_type TEXT DEFAULT 'image/jpeg',
            width INTEGER, height INTEGER, file_size INTEGER,
            is_primary INTEGER DEFAULT 0, label TEXT,
            source TEXT DEFAULT 'upload',
            added_at TEXT DEFAULT (datetime('now'))
        );
    """)
    _migrate(conn)
    _run_migrations(conn)
    c.executescript("""
        CREATE TABLE IF NOT EXISTS price_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
            price_usd  REAL    NOT NULL,
            checked_at TEXT    DEFAULT (datetime('now')),
            source     TEXT    DEFAULT 'scrape'
        );
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT DEFAULT (datetime('now')),
            description TEXT
        );
        CREATE TABLE IF NOT EXISTS app_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS talker_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            mode       TEXT    NOT NULL,
            input_text TEXT    NOT NULL,
            output_text TEXT   NOT NULL,
            created_at TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS talker_presets (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL UNIQUE,
            input_text TEXT    NOT NULL,
            mode       TEXT    DEFAULT 'little',
            notes      TEXT,
            created_at TEXT    DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_talker_hist_mode ON talker_history(mode);
        CREATE INDEX IF NOT EXISTS idx_talker_hist_time ON talker_history(created_at);
        CREATE INDEX IF NOT EXISTS idx_products_brand   ON products(brand_id);
        CREATE INDEX IF NOT EXISTS idx_products_cat     ON products(category_id);
        CREATE INDEX IF NOT EXISTS idx_products_price   ON products(price_usd);
        CREATE INDEX IF NOT EXISTS idx_products_type    ON products(brand_type);
        CREATE INDEX IF NOT EXISTS idx_products_updated ON products(last_updated);
        CREATE INDEX IF NOT EXISTS idx_products_source  ON products(source_site);
        CREATE INDEX IF NOT EXISTS idx_shopping_prod    ON shopping_list(product_id);
        CREATE INDEX IF NOT EXISTS idx_images_product   ON product_images(product_id);
        CREATE INDEX IF NOT EXISTS idx_price_hist_prod  ON price_history(product_id);
        CREATE INDEX IF NOT EXISTS idx_price_hist_time  ON price_history(checked_at);
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
        ("Plushies / Stuffies","Stuffed animals and comfort plushies for littles","🧸"),
        ("Activity / Art","Coloring books, stickers, crayons, activity sets","🎨"),
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
    ]:
        c.execute("INSERT OR IGNORE INTO brands "
                  "(name,country,website,description,brand_type,discreet_shipping,free_sample) "
                  "VALUES (?,?,?,?,?,?,?)", row)
    for name, url, enabled, stype in [
        # ── ABDL Specialty ──────────────────────────────────────────────────
        ("Tykables Store",          "https://tykables.com",                        1, "abdl"),
        ("ABUniverse Store",        "https://abuniverse.com",                      1, "abdl"),
        ("ABUniverse EU",           "https://eu.abuniverse.com",                   1, "abdl"),
        ("Rearz Store",             "https://rearz.ca",                            1, "abdl"),
        ("Bambino Diapers",         "https://bambinodiapers.com/shop",             1, "abdl"),
        ("BetterDry",               "https://www.betterdrydiapers.com",            1, "abdl"),
        ("Crinklz",                 "https://www.crinklz.com/shop",                1, "abdl"),
        ("Little For Big",          "https://www.littleforbig.com",                1, "abdl"),
        ("ABDL Factory",            "https://abdlfactory.com",                     1, "abdl"),
        ("Fabine",                  "https://fabine.de",                           1, "abdl"),
        ("MyDiaper",                "https://mydiaper.eu",                         1, "abdl"),
        ("InControl Designs",       "https://www.incontroldesigns.com",            1, "abdl"),
        ("Snuggies AU",             "https://snuggies.com.au",                     1, "abdl"),
        ("NappiesRus",              "https://www.nappiesrus.co.uk",                1, "abdl"),
        ("Cuddlz",                  "https://www.cuddlz.com",                      1, "abdl"),
        ("TNT Diaper Store",        "https://www.tntdiaper.com",                   1, "abdl"),
        ("PeekABU",                 "https://www.peekabu.com",                     1, "abdl"),
        ("Diaper Bros",             "https://www.diaperbroshop.com",               1, "abdl"),
        # ── Age Regression ──────────────────────────────────────────────────
        ("DDLG World",              "https://ddlgworld.com",                       1, "regression"),
        ("Kawaii Goodsn",           "https://www.kawaiigoodsn.com",                1, "regression"),
        ("Blippo Kawaii",           "https://www.blippo.com",                      1, "regression"),
        ("Sanrio Shop",             "https://www.sanrio.com/collections/all",      1, "regression"),
        ("Littleforbig Bottles",    "https://www.littleforbig.com",                1, "regression"),
        # ── Medical / Incontinence ──────────────────────────────────────────
        ("NorthShore Care Supply",  "https://northshorecare.com",                  1, "medical"),
        ("XP Medical",              "https://www.xpmedical.com",                   1, "medical"),
        ("HDIS",                    "https://www.hdis.com/incontinence",           1, "medical"),
        ("Personally Delivered",    "https://www.personallydelivered.com",         1, "medical"),
        ("Parentgiving",            "https://www.parentgiving.com",                1, "medical"),
        ("Vitality Medical",        "https://www.vitalitymedical.com/briefs.html", 1, "medical"),
        ("Health Products For You", "https://www.healthproductsforyou.com",        1, "medical"),
        ("Carewell",                "https://www.carewell.com",                    1, "medical"),
        ("Tranquility Products",    "https://www.tranquilityproducts.com",         1, "medical"),
        ("Unique Wellness",         "https://wellnessbriefs.com",                  1, "medical"),
        ("DiapersEtc",              "https://www.diapersetc.com",                  1, "medical"),
        ("Abena Global",            "https://www.abena.com",                       1, "both"),
        ("Attends Shop",            "https://shop.attends.com",                    1, "medical"),
        ("Prevail Products",        "https://prevailproducts.com",                 1, "medical"),
    ]:
        c.execute("""INSERT INTO scrape_sites (name,url,scrape_enabled,site_type,scrape_interval)
                     VALUES (?,?,?,?,?)
                     ON CONFLICT(name) DO UPDATE SET
                         url=excluded.url, scrape_enabled=excluded.scrape_enabled,
                         site_type=excluded.site_type""",
                  (name, url, enabled, stype, DEFAULT_SCRAPE_INTERVAL))
    conn.commit()
    conn.close()

    # Remove any stale/renamed/dead site entries from old versions
    # (disable FK for this step — sites may still have scrape_log rows)
    try:
        _purge_dead_sites_no_fk()
    except Exception as e:
        print(f"[purge_dead_sites] {e}")

    # Init standalone image library tables on a fresh connection
    # (init_db's connection is fully closed above so no locking conflict)
    try:
        init_library()
    except Exception as e:
        print(f"[init_library] WARNING: {e}")
        try:
            import time; time.sleep(0.5)
            init_library()
            print("[init_library] retry succeeded")
        except Exception as e2:
            print(f"[init_library] retry also failed: {e2}")

    # Migrate any old product_images rows into new library
    try:
        migrate_product_images_to_library()
    except Exception as e:
        print(f"[migrate] {e}")


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
    # Pull out extra_images before DB column filtering — handled separately below
    extra_images = data.pop("extra_images", [])

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
    existing = conn.execute(
        "SELECT id, image_url, price_usd FROM products WHERE url=?", (url,)
    ).fetchone() if url else None
    now = datetime.now().isoformat()
    try:
        if existing:
            pid       = existing["id"]
            old_price = existing["price_usd"]
            new_price = data.get("price_usd") or data.get("price")
            # ── Price drop detection ────────────────────────────────────────
            if old_price and new_price and new_price > 0:
                if new_price < old_price * 0.995:      # ≥0.5% drop
                    data["price_was"] = old_price
                    data["on_sale"]   = 1
                elif new_price >= old_price:
                    data.setdefault("on_sale",   0)
                    data.setdefault("price_was", None)
            # Never overwrite a good image_url with blank
            if not data.get("image_url") and existing["image_url"]:
                data.pop("image_url", None)
            data["last_updated"] = now
            sets = ", ".join(f"{k}=?" for k in data if k != "id")
            conn.execute(f"UPDATE products SET {sets} WHERE id=?",
                         [v for k,v in data.items() if k!="id"] + [pid])
        else:
            old_price = None
            data.setdefault("date_added", now); data["last_updated"] = now
            cols = ", ".join(data.keys()); ph = ", ".join("?"*len(data))
            cur = conn.execute(f"INSERT INTO products ({cols}) VALUES ({ph})", list(data.values()))
            pid = cur.lastrowid
        conn.commit()

        # ── Update FTS5 index (critical for search correctness) ────────────────
        # FTS5 content tables don't auto-update — must explicitly sync.
        if pid:
            try:
                # Delete old FTS entry then insert fresh one
                conn.execute("DELETE FROM products_fts WHERE rowid=?", (pid,))
                prod_row = conn.execute(
                    "SELECT p.name, p.description, b.name AS brand, p.tags, p.patterns "
                    "FROM products p LEFT JOIN brands b ON b.id=p.brand_id WHERE p.id=?",
                    (pid,)
                ).fetchone()
                if prod_row:
                    conn.execute(
                        "INSERT INTO products_fts(rowid, name, description, brand, tags, patterns) "
                        "VALUES (?,?,?,?,?,?)",
                        (pid,
                         prod_row[0] or "",
                         prod_row[1] or "",
                         prod_row[2] or "",
                         prod_row[3] or "",
                         prod_row[4] or "")
                    )
                conn.commit()
            except Exception:
                pass   # FTS table may not exist on old DBs — non-fatal

        # ── Record price snapshot ───────────────────────────────────────────
        new_price = data.get("price_usd") or data.get("price")
        if pid and new_price and new_price > 0:
            try:
                last_ph = conn.execute(
                    "SELECT price_usd FROM price_history WHERE product_id=? "
                    "ORDER BY checked_at DESC LIMIT 1", (pid,)
                ).fetchone()
                if last_ph is None or abs(last_ph[0] - new_price) > 0.001:
                    conn.execute(
                        "INSERT INTO price_history (product_id,price_usd,source) VALUES (?,?,?)",
                        (pid, new_price, "scrape")
                    )
                    conn.commit()
            except Exception:
                pass

        # Store all product images (URL references — actual pixels downloaded separately)
        # Primary image is already in products.image_url; extras go in product_images
        all_image_urls = []
        if data.get("image_url"):
            all_image_urls.append(data["image_url"])
        all_image_urls += [u for u in (extra_images or []) if u and u not in all_image_urls]

        if all_image_urls:
            # Get existing URLs to avoid duplicates
            existing_urls = {
                r[0] for r in conn.execute(
                    "SELECT image_url FROM product_images WHERE product_id=? AND image_url IS NOT NULL",
                    (pid,)
                ).fetchall()
            }
            for idx, img_url in enumerate(all_image_urls):
                if img_url and img_url not in existing_urls:
                    conn.execute(
                        "INSERT INTO product_images "
                        "(product_id, image_url, is_primary, source, added_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (pid, img_url, 1 if idx == 0 else 0, "scrape", now)
                    )
            conn.commit()

    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()
    return pid


def get_all_products(search="", brand_id=None, category_id=None, in_stock_only=False,
                     sort="name", brand_type=None, size_filter=None,
                     discreet_only=False, free_sample_only=False, max_price=None,
                     on_sale_only=False, gender=None, limit=2000):
    """
    Fetch filtered products.  All filters pushed into SQL — no client-side passes.
    Default limit=2000 prevents loading the entire DB into RAM.
    """
    conn = get_connection()
    params, where = [], []
    if search:
        where.append("(p.name LIKE ? OR p.description LIKE ? OR p.tags LIKE ?)")
        params += [f"%{search}%"]*3
    if brand_id:      where.append("p.brand_id=?");    params.append(brand_id)
    if category_id:   where.append("p.category_id=?"); params.append(category_id)
    if in_stock_only: where.append("p.in_stock=1")
    if on_sale_only:  where.append("p.on_sale=1")
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
    if gender and gender != "any":
        where.append("(LOWER(p.gender)=? OR LOWER(p.gender)='unisex' OR p.gender IS NULL)")
        params.append(gender.lower())
    order = {"name":"p.name ASC","price":"COALESCE(p.price_usd,p.price) ASC",
             "newest":"p.date_added DESC","rating":"p.rating DESC NULLS LAST"}.get(sort,"p.name ASC")
    sql = f"""
        SELECT p.*, COALESCE(p.price_usd,p.price) AS display_price,
               b.name AS brand_name, b.brand_type AS b_btype,
               b.discreet_shipping AS b_discreet, b.free_sample AS b_free_sample,
               b.website AS b_website,
               c.name AS category_name, c.icon AS category_icon
        FROM products p
        LEFT JOIN brands b ON p.brand_id=b.id
        LEFT JOIN categories c ON p.category_id=c.id
        {"WHERE " + " AND ".join(where) if where else ""}
        ORDER BY {order}
        LIMIT ?"""
    params.append(limit)
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
               p.on_sale, p.price_was,
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
    for tbl in ("products","brands","categories","scrape_sites","scrape_log",
                "shopping_list","wishlist","image_library","tags","image_tags"):
        try: tables[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        except Exception: tables[tbl] = 0
    # Image storage size (BLOBs only)
    try:
        img_bytes = conn.execute(
            "SELECT COALESCE(SUM(LENGTH(image_data)),0) FROM image_library"
        ).fetchone()[0] or 0
    except Exception:
        img_bytes = 0
    wal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    page_count= conn.execute("PRAGMA page_count").fetchone()[0]
    freelist  = conn.execute("PRAGMA freelist_count").fetchone()[0]
    db_bytes  = page_size * page_count
    conn.close()
    # WAL file size
    wal_path = str(DB_PATH) + "-wal"
    wal_bytes = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
    return {
        "path":              str(DB_PATH),
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
        "rows_images":       tables.get("image_library", 0),
        "rows_tags":         tables.get("tags", 0),
        "rows_image_tags":   tables.get("image_tags", 0),
        "img_blob_mb":       round(img_bytes / 1024 / 1024, 2),
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


def db_rebuild(pcb=None):
    """
    Full database rebuild:
      1. Auto-backup the current DB before touching anything.
      2. Drop every user-data table (products, brands, categories,
         images, shopping list, scrape log, download jobs, etc.).
      3. Re-run init_db() to recreate all tables with the latest schema.
      4. Re-seed scrape sites so the scraper can run immediately.

    The scrape_sites table is NOT wiped by default — existing site
    schedules and credentials are preserved so you don't have to
    re-enter them. Pass wipe_sites=True to also reset that.

    Returns the path of the auto-backup created before rebuilding.
    """
    import shutil, os

    def log(msg):
        if pcb: pcb(msg)

    # ── Step 1: auto-backup ───────────────────────────────────────────────────
    backup_path = None
    if DB_PATH.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = DB_PATH.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"pre_rebuild_{ts}.db"
        try:
            shutil.copy2(DB_PATH, backup_path)
            size_mb = round(backup_path.stat().st_size / 1024 / 1024, 2)
            log(f"  💾 Backed up to {backup_path.name} ({size_mb} MB)")
        except Exception as e:
            log(f"  ⚠ Backup failed: {e} — continuing anyway")
            backup_path = None

    # ── Step 2: drop all data tables ─────────────────────────────────────────
    DATA_TABLES = [
        "product_images", "image_tags", "tags", "tag_namespaces",
        "shopping_list", "wishlist", "download_jobs",
        "scrape_log", "products", "brands", "categories",
        "image_library",
    ]
    # site_credentials preserved — don't need to re-enter logins
    # scrape_sites preserved  — don't need to re-add all 80+ sites

    try:
        conn = get_connection()
        conn.execute("PRAGMA foreign_keys=OFF")
        dropped = []
        for table in DATA_TABLES:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            ).fetchone()
            if exists:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
                dropped.append(table)
        conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")
        conn.close()
        log(f"  🗑  Dropped {len(dropped)} table(s): {', '.join(dropped)}")
    except Exception as e:
        log(f"  ✗ Drop failed: {e}")
        raise

    # ── Step 3: recreate schema ───────────────────────────────────────────────
    try:
        init_db()
        log("  ✓ Schema recreated (latest version)")
    except Exception as e:
        log(f"  ✗ init_db failed: {e}")
        raise

    # ── Step 4: vacuum to reclaim disk space ──────────────────────────────────
    try:
        db_vacuum()
        size_mb = round(DB_PATH.stat().st_size / 1024 / 1024, 2)
        log(f"  🧹 Vacuumed — DB is now {size_mb} MB")
    except Exception as e:
        log(f"  ⚠ Vacuum failed: {e}")

    log("  ✅ Rebuild complete — run a scrape to repopulate the catalog")
    return backup_path


reindex_fts = rebuild_fts  # alias kept for backward compat


# ── Dead-site cleanup (run once on init) ─────────────────────────────────────

def _purge_dead_sites_no_fk():
    """
    Delete stale scrape_site rows without triggering FK failures.
    FK is disabled for this connection so cascading child rows don't block the delete.
    """
    dead_names = [
        "ABDLand","Bear Paw Creek","ABDL Diaper Store EU","Oasis Diapers",
        "BareBum","Paddedpanda","Snuggies AU","Littlespace Online",
        "DDLG World (old)","My Little One","Age Regression Store","CGL Shop",
        "Daddy's Angle","Little Dreamers","Pastel Carousel",
        "Abena USA","Adult Diaper Superstore","Seni Care US","McKesson Medical",
        "Seni Care","LittleForBig Littles","Little For Big Paci",
        "LittleForBig Bottles","Littleforbig Bottles","Redbubble Littlespace",
        "Dolls Kill Little","Kawaii Goodsn (old)",
    ]
    conn = sqlite3.connect(DB_PATH, timeout=10)   # raw connection — FK OFF by default
    conn.execute("PRAGMA foreign_keys=OFF")
    ph  = ",".join("?" * len(dead_names))
    cur = conn.execute(f"DELETE FROM scrape_sites WHERE name IN ({ph})", dead_names)
    conn.commit()
    conn.close()
    return cur.rowcount


def purge_dead_sites():
    """Remove scrape_site rows whose names are known-dead/renamed domains."""
    dead_names = [
        "ABDLand","Bear Paw Creek","ABDL Diaper Store EU","Oasis Diapers",
        "BareBum","Paddedpanda","Snuggies AU","Littlespace Online",
        "DDLG World (old)","My Little One","Age Regression Store","CGL Shop",
        "Daddy's Angle","Little Dreamers","Pastel Carousel",
        "Abena USA","Adult Diaper Superstore","Seni Care US","McKesson Medical",
        "Seni Care","LittleForBig Littles","Little For Big Paci",
        "LittleForBig Bottles","Littleforbig Bottles","Redbubble Littlespace",
        "Dolls Kill Little","Kawaii Goodsn (old)",
    ]
    conn = get_connection()
    ph   = ",".join("?" * len(dead_names))
    cur  = conn.execute(f"DELETE FROM scrape_sites WHERE name IN ({ph})", dead_names)
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


# ── Product Image System ──────────────────────────────────────────────────────

def add_product_image(product_id, *, image_data=None, image_url=None,
                      filename=None, mime_type="image/jpeg",
                      width=None, height=None, label=None,
                      source="upload", set_primary=False):
    conn = get_connection()
    file_size = len(image_data) if image_data else None
    cur = conn.execute(
        "INSERT INTO product_images "
        "(product_id,image_data,image_url,filename,mime_type,width,height,file_size,is_primary,label,source) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (product_id, image_data, image_url, filename, mime_type,
         width, height, file_size, 1 if set_primary else 0, label, source))
    iid = cur.lastrowid
    if set_primary:
        conn.execute("UPDATE product_images SET is_primary=0 WHERE product_id=? AND id!=?",
                     (product_id, iid))
    conn.commit(); conn.close()
    return iid


def get_product_images(product_id, include_data=True):
    conn = get_connection()
    if include_data:
        rows = conn.execute(
            "SELECT * FROM product_images WHERE product_id=? ORDER BY is_primary DESC, id",
            (product_id,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id,product_id,image_url,filename,mime_type,width,height,"
            "file_size,is_primary,label,source,added_at "
            "FROM product_images WHERE product_id=? ORDER BY is_primary DESC, id",
            (product_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_primary_image(product_id, image_id):
    conn = get_connection()
    conn.execute("UPDATE product_images SET is_primary=0 WHERE product_id=?", (product_id,))
    conn.execute("UPDATE product_images SET is_primary=1 WHERE id=? AND product_id=?",
                 (image_id, product_id))
    conn.commit(); conn.close()


def delete_product_image(image_id):
    conn = get_connection(); conn.execute("DELETE FROM product_images WHERE id=?", (image_id,))
    conn.commit(); conn.close()


def get_image_stats():
    conn = get_connection()
    total   = conn.execute("SELECT COUNT(*) FROM product_images").fetchone()[0]
    blobs   = conn.execute("SELECT COUNT(*) FROM product_images WHERE image_data IS NOT NULL").fetchone()[0]
    urls    = conn.execute("SELECT COUNT(*) FROM product_images WHERE image_url IS NOT NULL AND image_data IS NULL").fetchone()[0]
    size_mb = conn.execute("SELECT COALESCE(SUM(file_size),0)/1048576.0 FROM product_images").fetchone()[0]
    prods   = conn.execute("SELECT COUNT(DISTINCT product_id) FROM product_images").fetchone()[0]
    conn.close()
    return {"total":total,"blobs":blobs,"url_refs":urls,
            "size_mb":round(size_mb,2),"products_with_images":prods}


def _ensure_product_images_table(conn):
    """Create product_images if it was somehow missing from an old DB."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS product_images (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id  INTEGER REFERENCES products(id) ON DELETE CASCADE,
            image_data  BLOB,
            image_url   TEXT,
            filename    TEXT,
            mime_type   TEXT DEFAULT 'image/jpeg',
            width       INTEGER,
            height      INTEGER,
            file_size   INTEGER,
            is_primary  INTEGER DEFAULT 0,
            label       TEXT,
            source      TEXT DEFAULT 'upload',
            added_at    TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_images_product "
        "ON product_images(product_id)"
    )
    conn.commit()


def download_missing_images(pcb=None, limit=999_999):
    """
    Download pixel data for every product that has an image URL but no stored blob.
    Handles three cases:
      1. product_images rows with a URL but no image_data yet.
      2. Products with image_url in the products table but NO product_images rows.
      3. Products where product_images exists but image_data was never fetched.
    Returns count of successfully downloaded images.
    """
    import urllib.request, random, time
    from urllib.parse import urlparse

    def log(msg):
        if pcb:
            pcb(msg)

    _UA_POOL = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    ]

    now = datetime.now().isoformat()
    conn = get_connection()

    # Always ensure the table exists (handles old DBs that predate product_images)
    _ensure_product_images_table(conn)

    # ── Step 1: backfill product_images from products.image_url ───────────────
    # Every product with a URL but zero product_images rows gets one inserted.
    try:
        missing_rows = conn.execute("""
            SELECT p.id AS product_id, p.image_url, p.url AS page_url, p.name
            FROM products p
            WHERE p.image_url IS NOT NULL
              AND p.image_url != ''
              AND p.id NOT IN (
                  SELECT DISTINCT product_id FROM product_images
                  WHERE image_url IS NOT NULL
              )
        """).fetchall()
    except Exception as e:
        log(f"  ✗ Backfill query failed: {e}")
        conn.close()
        return 0

    backfilled = 0
    for row in missing_rows:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO product_images "
                "(product_id, image_url, is_primary, source, added_at) "
                "VALUES (?, ?, 1, 'backfill', ?)",
                (row["product_id"], row["image_url"], now)
            )
            backfilled += 1
        except Exception as e:
            log(f"  ✗ Backfill insert error for '{row['name'][:30]}': {e}")

    if backfilled:
        conn.commit()
        log(f"  ↳ Backfilled {backfilled} product(s) into product_images")

    # ── Step 2: collect all rows that still need pixel data ───────────────────
    try:
        rows = conn.execute("""
            SELECT pi.id,
                   pi.product_id,
                   pi.image_url,
                   pi.is_primary,
                   p.url  AS page_url,
                   p.name AS product_name
            FROM product_images pi
            JOIN products p ON p.id = pi.product_id
            WHERE pi.image_url IS NOT NULL
              AND pi.image_url != ''
              AND pi.image_data IS NULL
            ORDER BY pi.is_primary DESC, pi.id
            LIMIT ?
        """, (limit,)).fetchall()
    except Exception as e:
        log(f"  ✗ Could not query pending images: {e}")
        conn.close()
        return 0

    conn.close()

    total = len(rows)
    log(f"  {total:,} image(s) to download")

    if total == 0:
        log("  ℹ  Nothing to download — either no products have been scraped yet,")
        log("  ℹ  or all images are already stored.")
        log("  ℹ  Run a scrape first from the Scraper tab, then try again.")
        return 0

    downloaded = 0
    failed     = 0

    for i, row in enumerate(rows, 1):
        iid        = row["id"]
        img_url    = row["image_url"]
        is_primary = row["is_primary"]
        page_url   = row["page_url"] or ""
        name       = (row["product_name"] or "")[:35]

        origin = ""
        if page_url:
            try:
                parsed = urlparse(page_url)
                origin = f"{parsed.scheme}://{parsed.netloc}"
            except Exception:
                pass

        headers = {
            "User-Agent":      random.choice(_UA_POOL),
            "Accept":          "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Dest":  "image",
            "Sec-Fetch-Mode":  "no-cors",
            "Sec-Fetch-Site":  "same-site",
            "DNT":             "1",
        }
        if origin:
            headers["Referer"] = page_url or origin

        try:
            req = urllib.request.Request(img_url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
                ct   = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()

            fname = img_url.rstrip("/").split("/")[-1].split("?")[0] or "image.jpg"

            if not data or len(data) < 100:
                raise ValueError(f"too small ({len(data)} bytes)")

            # Accept any image/* type; also accept octet-stream if magic bytes match
            if not ct.startswith("image/"):
                magic = data[:4]
                if magic not in (
                    b'\xff\xd8\xff\xe0', b'\xff\xd8\xff\xe1',   # JPEG
                    b'\x89PNG',                                    # PNG
                    b'RIFF',                                       # WebP
                ) and data[:6] not in (b'GIF87a', b'GIF89a'):    # GIF
                    raise ValueError(f"not an image (ct={ct})")

            c2 = get_connection()
            c2.execute(
                "UPDATE product_images "
                "SET image_data=?, filename=?, mime_type=?, file_size=? "
                "WHERE id=?",
                (data, fname, ct, len(data), iid)
            )
            c2.commit(); c2.close()

            # Generate thumbnail immediately — future catalog loads are instant
            try:
                from thumbnail_cache import get_thumb_cache
                get_thumb_cache().store(img_url, data)
            except Exception:
                pass

            downloaded += 1
            tag = "[primary] " if is_primary else ""
            log(f"  ✓ {tag}{name}  ({len(data)//1024} KB)")

        except Exception as e:
            failed += 1
            fname_short = img_url.split("/")[-1].split("?")[0][:30]
            log(f"  ✗ {name}  {fname_short}: {e}")

        # Human-like pacing: brief pause every 10 images
        if i % 10 == 0:
            time.sleep(random.uniform(0.3, 0.8))

    log(f"\n  Done — {downloaded} downloaded, {failed} failed out of {total} total")
    return downloaded


def count_images_pending():
    """Return how many images still need to be downloaded."""
    conn = get_connection()
    _ensure_product_images_table(conn)
    try:
        pending_blobs = conn.execute(
            "SELECT COUNT(*) FROM product_images "
            "WHERE image_url IS NOT NULL AND image_data IS NULL"
        ).fetchone()[0]
        not_backfilled = conn.execute("""
            SELECT COUNT(*) FROM products p
            WHERE p.image_url IS NOT NULL AND p.image_url != ''
              AND p.id NOT IN (
                  SELECT DISTINCT product_id FROM product_images
                  WHERE image_url IS NOT NULL
              )
        """).fetchone()[0]
    except Exception:
        pending_blobs = 0
        not_backfilled = 0
    finally:
        conn.close()
    return pending_blobs + not_backfilled


def get_product_image_urls(product_id):
    """Return list of all image URLs for a product (no pixel data — fast)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, image_url, is_primary, filename, mime_type, file_size "
        "FROM product_images WHERE product_id=? "
        "ORDER BY is_primary DESC, id",
        (product_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Price History & Drop Detection ────────────────────────────────────────────

def record_price(product_id: int, price_usd: float, source: str = "scrape"):
    """Record a price snapshot.  Called from upsert_product on every scrape."""
    if not product_id or price_usd is None:
        return
    conn = get_connection()
    # Only record if price changed or no recent record (last 24 h)
    last = conn.execute(
        "SELECT price_usd FROM price_history WHERE product_id=? "
        "ORDER BY checked_at DESC LIMIT 1", (product_id,)
    ).fetchone()
    if last is None or abs(last[0] - price_usd) > 0.001:
        conn.execute(
            "INSERT INTO price_history (product_id, price_usd, source) VALUES (?,?,?)",
            (product_id, price_usd, source)
        )
        conn.commit()
    conn.close()


def get_price_history(product_id: int, limit: int = 30) -> list:
    """Return list of {price_usd, checked_at} dicts, newest first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT price_usd, checked_at FROM price_history "
        "WHERE product_id=? ORDER BY checked_at DESC LIMIT ?",
        (product_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_price_drops(min_drop_pct: float = 5.0, limit: int = 100) -> list:
    """
    Return products whose current price is lower than their recorded
    previous price by at least min_drop_pct percent.
    Returns list of product dicts with extra keys: price_was, drop_pct.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT
            p.id, p.name, p.url, p.image_url,
            p.price_usd AS current_price,
            p.price_was,
            b.name AS brand_name,
            c.name AS category_name,
            p.source_site,
            p.brand_type,
            p.in_stock,
            ROUND((p.price_was - p.price_usd) / p.price_was * 100, 1) AS drop_pct
        FROM products p
        LEFT JOIN brands    b ON b.id = p.brand_id
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.price_was IS NOT NULL
          AND p.price_usd  IS NOT NULL
          AND p.price_usd  > 0
          AND p.price_was  > p.price_usd
          AND ((p.price_was - p.price_usd) / p.price_was * 100) >= ?
        ORDER BY drop_pct DESC
        LIMIT ?
    """, (min_drop_pct, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_price_drop(product_id: int, old_price: float, new_price: float):
    """Update products.price_was and on_sale flag when price drops."""
    conn = get_connection()
    conn.execute(
        "UPDATE products SET price_was=?, on_sale=1, last_updated=? WHERE id=?",
        (old_price, datetime.now().isoformat(), product_id)
    )
    conn.commit(); conn.close()


def clear_price_drop(product_id: int):
    """Clear on_sale flag when price returns to normal."""
    conn = get_connection()
    conn.execute(
        "UPDATE products SET on_sale=0, price_was=NULL WHERE id=?",
        (product_id,)
    )
    conn.commit(); conn.close()


# ── Wishlist ───────────────────────────────────────────────────────────────────

def add_to_wishlist(product_id: int, notes: str = "",
                    target_price: float = None) -> int:
    """Add a product to the wishlist. Returns wishlist row id."""
    conn = get_connection()
    cur = conn.execute(
        "INSERT OR IGNORE INTO wishlist (product_id, notes, target_price) "
        "VALUES (?,?,?)",
        (product_id, notes or "", target_price)
    )
    lid = cur.lastrowid
    conn.commit(); conn.close()
    return lid


def remove_from_wishlist(product_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM wishlist WHERE product_id=?", (product_id,))
    conn.commit(); conn.close()


def is_on_wishlist(product_id: int) -> bool:
    conn = get_connection()
    r = conn.execute(
        "SELECT 1 FROM wishlist WHERE product_id=?", (product_id,)
    ).fetchone()
    conn.close()
    return r is not None


def get_wishlist(include_product_data: bool = True) -> list:
    """Return all wishlist items with full product details."""
    conn = get_connection()
    if include_product_data:
        rows = conn.execute("""
            SELECT w.id, w.notes, w.target_price, w.added_at, w.notified_at,
                   p.id AS product_id, p.name, p.price_usd, p.price_was,
                   p.on_sale, p.url, p.image_url, p.in_stock,
                   p.brand_type, p.source_site,
                   b.name AS brand_name, c.name AS category_name
            FROM wishlist w
            JOIN products p ON p.id = w.product_id
            LEFT JOIN brands b ON b.id = p.brand_id
            LEFT JOIN categories c ON c.id = p.category_id
            ORDER BY w.added_at DESC
        """).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM wishlist ORDER BY added_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_wishlist_alerts() -> list:
    """
    Return wishlist items where:
    - target_price set AND current price <= target_price, OR
    - on_sale=1 AND not yet notified
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT w.id AS wishlist_id, w.target_price, w.notified_at,
               p.id AS product_id, p.name, p.price_usd, p.price_was,
               p.on_sale, p.url, b.name AS brand_name
        FROM wishlist w
        JOIN products p ON p.id = w.product_id
        LEFT JOIN brands b ON b.id = p.brand_id
        WHERE (
            (w.target_price IS NOT NULL AND p.price_usd <= w.target_price)
            OR p.on_sale = 1
        )
        AND w.notified_at IS NULL
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_wishlist_notified(wishlist_id: int):
    conn = get_connection()
    conn.execute(
        "UPDATE wishlist SET notified_at=? WHERE id=?",
        (datetime.now().isoformat(), wishlist_id)
    )
    conn.commit(); conn.close()


# ── App Settings (key/value store) ────────────────────────────────────────────

def get_setting(key: str, default=None):
    """Get a persistent app setting."""
    try:
        conn = get_connection()
        r = conn.execute(
            "SELECT value FROM app_settings WHERE key=?", (key,)
        ).fetchone()
        conn.close()
        return r[0] if r else default
    except Exception:
        return default


def set_setting(key: str, value):
    """Persist an app setting."""
    try:
        conn = get_connection()
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?,?)",
            (key, str(value) if value is not None else None)
        )
        conn.commit(); conn.close()
    except Exception:
        pass


# ── Talker History & Presets ──────────────────────────────────────────────────

def talker_save_history(mode: str, input_text: str, output_text: str,
                         max_rows: int = 200) -> int:
    """Save a transform to history. Prunes to max_rows. Returns new row id."""
    try:
        conn = get_connection()
        cur = conn.execute(
            "INSERT INTO talker_history (mode, input_text, output_text) VALUES (?,?,?)",
            (mode, input_text, output_text)
        )
        new_id = cur.lastrowid
        conn.execute(
            "DELETE FROM talker_history WHERE id NOT IN ("
            "  SELECT id FROM talker_history ORDER BY id DESC LIMIT ?)",
            (max_rows,)
        )
        conn.commit(); conn.close()
        return new_id
    except Exception:
        return 0


def talker_get_history(limit: int = 50, mode: str = None) -> list:
    """Return recent transform history, newest first."""
    try:
        conn = get_connection()
        if mode:
            rows = conn.execute(
                "SELECT * FROM talker_history WHERE mode=? ORDER BY id DESC LIMIT ?",
                (mode, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM talker_history ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def talker_clear_history():
    conn = get_connection()
    conn.execute("DELETE FROM talker_history")
    conn.commit(); conn.close()


def talker_save_preset(name: str, input_text: str,
                        mode: str = "little", notes: str = "") -> int:
    """Save or replace a named preset."""
    try:
        conn = get_connection()
        cur = conn.execute(
            "INSERT OR REPLACE INTO talker_presets (name, input_text, mode, notes) "
            "VALUES (?,?,?,?)",
            (name, input_text, mode, notes)
        )
        pid = cur.lastrowid
        conn.commit(); conn.close()
        return pid
    except Exception:
        return 0


def talker_get_presets() -> list:
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM talker_presets ORDER BY name"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def talker_delete_preset(preset_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM talker_presets WHERE id=?", (preset_id,))
    conn.commit(); conn.close()


def talker_get_stats() -> dict:
    """Return usage statistics for the talker."""
    try:
        conn = get_connection()
        total = conn.execute("SELECT COUNT(*) FROM talker_history").fetchone()[0]
        by_mode = conn.execute(
            "SELECT mode, COUNT(*) as cnt FROM talker_history GROUP BY mode ORDER BY cnt DESC"
        ).fetchall()
        presets = conn.execute("SELECT COUNT(*) FROM talker_presets").fetchone()[0]
        conn.close()
        return {
            "total_transforms": total,
            "by_mode": {r["mode"]: r["cnt"] for r in by_mode},
            "saved_presets": presets,
        }
    except Exception:
        return {"total_transforms": 0, "by_mode": {}, "saved_presets": 0}


# ── FTS5 Search ────────────────────────────────────────────────────────────────

def search_products_fts(query: str, brand_type: str = None,
                         in_stock_only: bool = False,
                         discreet_only: bool = False,
                         free_sample_only: bool = False,
                         on_sale_only: bool = False,
                         max_price: float = None,
                         gender: str = None,
                         limit: int = 2000) -> list:
    """
    Fast FTS5 full-text search with all the same filters as get_all_products.
    Falls back to LIKE search if FTS index unavailable.
    """
    if not query or not query.strip():
        return []
    conn = get_connection()
    q = query.strip()
    fts_q = f'"{q}"' if " " in q else f'{q}*'

    extra_where, params = [], [fts_q]

    if brand_type and brand_type != "all":
        extra_where.append("(p.brand_type=? OR p.brand_type='both')")
        params.append(brand_type)
    if in_stock_only:    extra_where.append("p.in_stock=1")
    if on_sale_only:     extra_where.append("p.on_sale=1")
    if discreet_only:    extra_where.append("(p.discreet_shipping=1 OR b.discreet_shipping=1)")
    if free_sample_only: extra_where.append("(p.free_sample=1 OR b.free_sample=1)")
    if max_price and max_price > 0:
        extra_where.append("COALESCE(p.price_usd,p.price)<=?")
        params.append(max_price)
    if gender and gender != "any":
        extra_where.append("(LOWER(p.gender)=? OR LOWER(p.gender)='unisex' OR p.gender IS NULL)")
        params.append(gender.lower())

    extra_sql = ("AND " + " AND ".join(extra_where)) if extra_where else ""

    try:
        rows = conn.execute(f"""
            SELECT p.*, COALESCE(p.price_usd, p.price) AS display_price,
                   b.name AS brand_name, c.name AS category_name, c.icon AS category_icon,
                   b.discreet_shipping AS b_discreet, b.free_sample AS b_free_sample,
                   p.on_sale, p.price_was
            FROM products_fts f
            JOIN products p ON p.id = f.rowid
            LEFT JOIN brands b ON b.id = p.brand_id
            LEFT JOIN categories c ON c.id = p.category_id
            WHERE products_fts MATCH ? {extra_sql}
            ORDER BY rank
            LIMIT ?
        """, params + [limit]).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        conn.close()
        return get_all_products(
            search=query, brand_type=brand_type,
            in_stock_only=in_stock_only, discreet_only=discreet_only,
            free_sample_only=free_sample_only, on_sale_only=on_sale_only,
            max_price=max_price, gender=gender,
        )


# ── JSON Import ───────────────────────────────────────────────────────────────

def parse_product_json(path, source_site="JSON Import", brand_type="abdl",
                       dry_run=False, pcb=None):
    """
    Parse a .json or .jsonl file containing product data and import into the DB.

    Auto-detects format:
      - Shopify  : {"products": [{title, images, variants, body_html, tags, handle}]}
      - WooCommerce: [{name, price, images:[{src}], description, permalink}]
      - Flat     : [{name/title, image/image_url/photo, price, description, url}]
      - JSONL    : one product JSON object per line

    Returns (products_list, format_name, warnings_list).
    If dry_run=True, nothing is written to the DB.
    """
    import json as _json
    from pathlib import Path as _Path
    from bs4 import BeautifulSoup as _BS

    path = _Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    warnings = []

    # ── Parse raw text ────────────────────────────────────────────────────────
    data = None
    fmt  = "unknown"

    # JSONL: one object per line
    if path.suffix.lower() == ".jsonl" or "\n{" in raw[:500]:
        try:
            lines = [l.strip() for l in raw.splitlines() if l.strip().startswith("{")]
            data = [_json.loads(l) for l in lines]
            fmt  = "JSONL (one product per line)"
        except Exception:
            pass

    if data is None:
        try:
            parsed = _json.loads(raw)
        except Exception as e:
            raise ValueError(f"Not valid JSON: {e}")

        if isinstance(parsed, dict) and "products" in parsed:
            # Shopify /products.json format
            data = parsed["products"]
            fmt  = "Shopify"
        elif isinstance(parsed, list):
            data = parsed
            # Detect WooCommerce vs flat by field names in first record
            if data and isinstance(data[0], dict):
                first = data[0]
                if "permalink" in first or "slug" in first or "regular_price" in first:
                    fmt = "WooCommerce REST API"
                else:
                    fmt = "Flat list"
        elif isinstance(parsed, dict):
            # Single product
            data = [parsed]
            fmt  = "Single product object"

    if not data:
        return ([], fmt, ["No products found in file."])

    # ── Extract fields per format ─────────────────────────────────────────────
    def _clean_html(html):
        if not html: return ""
        try:
            return _BS(str(html), "html.parser").get_text(" ", strip=True)[:1200]
        except Exception:
            return str(html)[:1200]

    def _parse_price(val):
        if val is None: return None
        import re
        m = re.search(r'[\d]+\.?\d*', str(val).replace(",",""))
        return float(m.group()) if m else None

    def _clean_url(u):
        return str(u).strip() if u else ""

    def _first_image(images, handle=""):
        """Extract first image URL from various image field shapes."""
        if not images:
            return ""
        if isinstance(images, str):
            return images.split("?")[0]
        if isinstance(images, list):
            for img in images:
                if isinstance(img, str) and img:
                    return img.split("?")[0]
                if isinstance(img, dict):
                    src = img.get("src") or img.get("url") or img.get("href","")
                    if src: return src.split("?")[0]
        if isinstance(images, dict):
            src = images.get("src") or images.get("url","")
            return src.split("?")[0] if src else ""
        return ""

    def _all_images(images):
        """Extract all image URLs."""
        urls = []
        if not images: return urls
        if isinstance(images, str):
            if images: urls.append(images.split("?")[0])
            return urls
        if isinstance(images, list):
            for img in images:
                if isinstance(img, str) and img:
                    urls.append(img.split("?")[0])
                elif isinstance(img, dict):
                    src = img.get("src") or img.get("url") or img.get("href","")
                    if src: urls.append(src.split("?")[0])
        elif isinstance(images, dict):
            src = images.get("src") or images.get("url","")
            if src: urls.append(src.split("?")[0])
        return [u for u in urls if u]

    products = []
    now = datetime.now().isoformat()

    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            warnings.append(f"Row {idx}: skipped (not a dict)")
            continue

        # ── Name ──────────────────────────────────────────────────────────────
        name = (item.get("title") or item.get("name") or
                item.get("product_name") or item.get("product") or "").strip()
        if not name:
            warnings.append(f"Row {idx}: skipped (no name/title)")
            continue

        # ── Description ───────────────────────────────────────────────────────
        desc_raw = (item.get("body_html") or item.get("description") or
                    item.get("short_description") or item.get("desc") or "")
        desc = _clean_html(desc_raw)

        # ── Price ─────────────────────────────────────────────────────────────
        price_raw = (item.get("price") or
                     item.get("price_usd") or item.get("price_gbp") or
                     item.get("regular_price") or item.get("sale_price") or
                     item.get("cost"))
        # Shopify variant prices
        if price_raw is None and item.get("variants"):
            v = item["variants"][0] if isinstance(item["variants"], list) else {}
            price_raw = v.get("price")
        price = _parse_price(price_raw)

        # ── URL ───────────────────────────────────────────────────────────────
        url = _clean_url(
            item.get("url") or item.get("permalink") or
            item.get("link") or item.get("product_url") or
            item.get("page_url") or ""
        )
        # Shopify: build URL from handle
        if not url and item.get("handle"):
            url = f"/{item['handle']}"   # relative; will be updated on next scrape

        # ── Images ────────────────────────────────────────────────────────────
        images_raw = (item.get("images") or item.get("image") or
                      item.get("photos") or item.get("photo") or
                      item.get("image_url") or item.get("thumbnail") or
                      item.get("featured_image") or "")
        all_imgs  = _all_images(images_raw)
        image_url = all_imgs[0] if all_imgs else ""
        extra     = all_imgs[1:]

        # ── Tags ──────────────────────────────────────────────────────────────
        tags_raw = item.get("tags") or item.get("tag_list") or []
        if isinstance(tags_raw, list):
            tags = ", ".join(str(t) for t in tags_raw)
        else:
            tags = str(tags_raw)

        # ── Brand ─────────────────────────────────────────────────────────────
        brand = (item.get("brand") or item.get("vendor") or
                 item.get("brand_name") or item.get("manufacturer") or source_site)

        # ── Category ──────────────────────────────────────────────────────────
        category = (item.get("category") or item.get("category_name") or
                    item.get("type") or item.get("product_type") or "")

        # ── In stock ──────────────────────────────────────────────────────────
        avail = item.get("available") or item.get("in_stock") or item.get("status")
        if avail is None:
            in_stock = 1
        elif isinstance(avail, bool):
            in_stock = 1 if avail else 0
        elif isinstance(avail, (int, float)):
            in_stock = 1 if avail else 0
        else:
            in_stock = 0 if str(avail).lower() in ("false","out","outofstock","0","no") else 1

        product = {
            "name":        name,
            "description": desc,
            "price_usd":   price,
            "price":       price,
            "url":         url,
            "image_url":   image_url,
            "extra_images":extra,
            "tags":        tags,
            "brand_name":  brand,
            "category_name": category if category else None,
            "source_site": source_site,
            "brand_type":  brand_type,
            "in_stock":    in_stock,
            "date_added":  now,
        }

        # ── Infer category from name+desc if not explicit ──────────────────
        if not product["category_name"]:
            try:
                from scraper import _infer_cat_name
                product["category_name"] = _infer_cat_name(name, desc)
            except ImportError:
                product["category_name"] = "Accessories"

        products.append(product)

    if not dry_run:
        added = 0
        for p in products:
            try:
                upsert_product(p)
                added += 1
                if pcb: pcb(f"  ✓ {p['name'][:50]}")
            except Exception as e:
                warnings.append(f"DB error for '{p['name'][:40]}': {e}")
        if pcb:
            pcb(f"\n  Imported {added} / {len(products)} products")

    return (products, fmt, warnings)


# ── AI / Model Learning ───────────────────────────────────────────────────────

def export_training_data(output_path=None, fmt="jsonl", brand_type=None):
    import json as _j, csv as _c, tempfile, os
    conn = get_connection()
    q = ("SELECT p.*,b.name AS brand_name,c.name AS category_name "
         "FROM products p LEFT JOIN brands b ON b.id=p.brand_id "
         "LEFT JOIN categories c ON c.id=p.category_id")
    params = []
    if brand_type:
        q += " WHERE p.brand_type=?"; params.append(brand_type)
    rows = conn.execute(q, params).fetchall(); conn.close()
    if not output_path:
        ext = ".csv" if fmt=="csv" else ".jsonl"
        fd, output_path = tempfile.mkstemp(suffix=ext, prefix="abdl_train_"); os.close(fd)
    count = 0
    if fmt == "jsonl":
        with open(output_path,"w",encoding="utf-8") as f:
            for r in rows:
                f.write(_j.dumps({k:v for k,v in dict(r).items() if k!="image_data" and v is not None},
                                 ensure_ascii=False)+"\n"); count+=1
    elif fmt == "qa":
        with open(output_path,"w",encoding="utf-8") as f:
            for r in rows:
                d=dict(r); p=d.get("price_usd") or d.get("price")
                entry={"messages":[
                    {"role":"system","content":"You are an ABDL/incontinence product catalog assistant."},
                    {"role":"user","content":f"Tell me about {d.get('name','')} by {d.get('brand_name','Unknown')}."},
                    {"role":"assistant","content":(
                        f"{d.get('name','')} is a {d.get('category_name','')} by {d.get('brand_name','')}. "
                        +(f"${p:.2f} USD. " if p else "")
                        +(f"Sizes: {d.get('size_range','')}. " if d.get('size_range') else "")
                        +((d.get('description','')or '')[:300]))}]}
                f.write(_j.dumps(entry,ensure_ascii=False)+"\n"); count+=1
    elif fmt == "csv":
        fields=["id","name","brand_name","category_name","brand_type","price_usd",
                "size_range","absorbency_label","tags","in_stock","source_site","url"]
        with open(output_path,"w",newline="",encoding="utf-8") as f:
            w=_c.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader()
            for r in rows: w.writerow({k:dict(r).get(k,"") for k in fields}); count+=1
    return output_path, count


def ai_suggest_tags(product_id, model="llama3", ollama_url="http://localhost:11434"):
    import json as _j, urllib.request as _r
    prod = get_product_by_id(product_id)
    if not prod: return {"error":"not found"}
    prompt = (f"You are an ABDL/incontinence catalog expert.\n"
              f"Product: {prod.get('name','')}\nBrand: {prod.get('brand_name','')}\n"
              f"Desc: {(prod.get('description','')or '')[:400]}\n"
              f"Reply ONLY valid JSON: {{\"tags\":\"...\",\"category_name\":\"...\","
              f"\"brand_type\":\"abdl|medical|both|regression\",\"confidence\":0.9}}")
    payload = _j.dumps({"model":model,"prompt":prompt,"stream":False,"format":"json"}).encode()
    try:
        rq = _r.Request(f"{ollama_url}/api/generate", data=payload, method="POST",
                        headers={"Content-Type":"application/json"})
        with _r.urlopen(rq, timeout=30) as resp:
            body = _j.loads(resp.read())
        return {**_j.loads(body.get("response","{}").strip()), "product_id":product_id}
    except Exception as e:
        return {"error":str(e),"product_id":product_id}


def ai_apply_suggestions(product_id, suggestions):
    if not suggestions or "error" in suggestions: return 0
    conn = get_connection()
    updates = {}
    if suggestions.get("tags"):          updates["tags"]       = suggestions["tags"]
    if suggestions.get("brand_type") in ("abdl","medical","both","regression"):
        updates["brand_type"] = suggestions["brand_type"]
    if suggestions.get("category_name"):
        cid = _resolve_category_id(conn, suggestions["category_name"])
        if cid: updates["category_id"] = cid
    if not updates: conn.close(); return 0
    updates["last_updated"] = datetime.now().isoformat()
    sets = ", ".join(f"{k}=?" for k in updates)
    conn.execute(f"UPDATE products SET {sets} WHERE id=?", list(updates.values())+[product_id])
    conn.commit(); conn.close()
    return len(updates)


def ai_batch_tag(product_ids=None, model="llama3", ollama_url="http://localhost:11434", pcb=None):
    import time as _t
    conn = get_connection()
    if product_ids is None:
        product_ids = [r[0] for r in conn.execute("SELECT id FROM products").fetchall()]
    conn.close()
    processed=updated=errors=0
    for pid in product_ids:
        s=ai_suggest_tags(pid,model=model,ollama_url=ollama_url)
        if "error" in s: errors+=1; pcb and pcb(f"  ✗ {pid}: {s['error']}")
        else: n=ai_apply_suggestions(pid,s); updated+=n; pcb and pcb(f"  ✓ {pid}: +{n}")
        processed+=1; _t.sleep(0.05)
    return {"processed":processed,"updated":updated,"errors":errors}


def get_products_missing_tags(limit=500):
    conn = get_connection()
    rows = conn.execute("SELECT id,name FROM products WHERE tags IS NULL OR tags='' LIMIT ?", (limit,)).fetchall()
    conn.close(); return [dict(r) for r in rows]


def get_products_missing_category(limit=500):
    conn = get_connection()
    rows = conn.execute("SELECT id,name FROM products WHERE category_id IS NULL LIMIT ?", (limit,)).fetchall()
    conn.close(); return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# IMAGE LIBRARY — standalone image database with tag system
# Modelled after Hydrus/Booru metadata approach:
#   image_library   — one row per image (BLOB or URL, no product required)
#   tag_namespaces  — e.g. "type", "brand", "character", "rating"
#   tags            — normalised tag list with usage count
#   image_tags      — M:N junction  (image_id, tag_id)
# ══════════════════════════════════════════════════════════════════════════════

def _init_library(conn):
    """Create image library tables if they don't exist. Safe to call repeatedly.
    Uses individual execute() calls instead of executescript() to avoid the
    implicit COMMIT that executescript() issues, which can cause 'database is locked'
    errors when called from within an existing transaction.
    """
    stmts = [
        """CREATE TABLE IF NOT EXISTS tag_namespaces (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT UNIQUE NOT NULL,
            color       TEXT DEFAULT '#9b8fc4',
            description TEXT,
            sort_order  INTEGER DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS tags (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            namespace_id INTEGER REFERENCES tag_namespaces(id) ON DELETE SET NULL,
            count        INTEGER DEFAULT 0,
            description  TEXT,
            alias_of     INTEGER REFERENCES tags(id) ON DELETE SET NULL,
            created_at   TEXT DEFAULT (datetime('now'))
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_ns_name ON tags(namespace_id, name)",
        """CREATE TABLE IF NOT EXISTS image_library (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            image_data    BLOB,
            image_url     TEXT,
            filename      TEXT,
            mime_type     TEXT DEFAULT 'image/jpeg',
            width         INTEGER,
            height        INTEGER,
            file_size     INTEGER,
            hash_md5      TEXT,
            rating        INTEGER DEFAULT 0,
            notes         TEXT,
            source_url    TEXT,
            source_name   TEXT,
            product_id    INTEGER REFERENCES products(id) ON DELETE SET NULL,
            date_added    TEXT DEFAULT (datetime('now')),
            date_modified TEXT DEFAULT (datetime('now'))
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_lib_hash ON image_library(hash_md5) WHERE hash_md5 IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_lib_product ON image_library(product_id)",
        "CREATE INDEX IF NOT EXISTS idx_lib_rating  ON image_library(rating)",
        "CREATE INDEX IF NOT EXISTS idx_lib_added   ON image_library(date_added)",
        """CREATE TABLE IF NOT EXISTS image_tags (
            image_id INTEGER NOT NULL REFERENCES image_library(id) ON DELETE CASCADE,
            tag_id   INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            PRIMARY KEY (image_id, tag_id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_imgtags_image ON image_tags(image_id)",
        "CREATE INDEX IF NOT EXISTS idx_imgtags_tag   ON image_tags(tag_id)",
        """CREATE TABLE IF NOT EXISTS download_jobs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            site        TEXT NOT NULL,
            query       TEXT NOT NULL,
            limit_n     INTEGER DEFAULT 20,
            status      TEXT DEFAULT 'pending',
            found       INTEGER DEFAULT 0,
            downloaded  INTEGER DEFAULT 0,
            duplicates  INTEGER DEFAULT 0,
            errors      INTEGER DEFAULT 0,
            started_at  TEXT,
            finished_at TEXT,
            notes       TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS site_credentials (
            site    TEXT PRIMARY KEY,
            login   TEXT,
            api_key TEXT,
            extra   TEXT
        )""",
    ]
    for stmt in stmts:
        try:
            conn.execute(stmt)
        except Exception as e:
            # Log but continue — partial schema is better than no schema
            print(f"[_init_library] stmt warning: {e}")
    conn.commit()


def _seed_default_tags(conn):
    """Seed ABDL-focused default tag namespaces and common tags."""
    namespaces = [
        ("type",      "#e06c75", "What kind of item/content",        1),
        ("brand",     "#61afef", "Brand or manufacturer",            2),
        ("style",     "#c678dd", "Visual/design style",              3),
        ("size",      "#56b6c2", "Size range",                       4),
        ("material",  "#98c379", "Material type",                    5),
        ("rating",    "#e5c07b", "Content rating (safe/explicit)",    6),
        ("character", "#d19a66", "Character or theme",               7),
        ("color",     "#abb2bf", "Color or pattern",                 8),
        ("source",    "#7c6f9f", "Where the image came from",        9),
        ("meta",      "#5c6370", "Meta tags (favorite, review, etc)",10),
    ]
    ns_ids = {}
    for name, color, desc, order in namespaces:
        conn.execute(
            "INSERT OR IGNORE INTO tag_namespaces (name,color,description,sort_order) VALUES(?,?,?,?)",
            (name, color, desc, order))
        row = conn.execute("SELECT id FROM tag_namespaces WHERE name=?", (name,)).fetchone()
        ns_ids[name] = row[0]

    default_tags = [
        # type namespace
        ("type","diaper"),("type","pull-up"),("type","booster"),("type","onesie"),
        ("type","romper"),("type","pacifier"),("type","bottle"),("type","sippy cup"),
        ("type","underpad"),("type","plastic pants"),("type","diaper cover"),
        ("type","swim diaper"),("type","plushie"),("type","sticker"),
        ("type","coloring page"),("type","bedding"),("type","accessory"),
        ("type","skincare"),("type","wipes"),("type","powder"),
        # brand namespace
        ("brand","tykables"),("brand","abu"),("brand","rearz"),("brand","bambino"),
        ("brand","betterdry"),("brand","crinklz"),("brand","little for big"),
        ("brand","northshore"),("brand","prevail"),("brand","tranquility"),
        ("brand","abena"),("brand","tena"),("brand","depend"),("brand","attends"),
        ("brand","unique wellness"),("brand","incontrol"),
        # style namespace
        ("style","abdl"),("style","medical"),("style","cute"),("style","printed"),
        ("style","plain"),("style","pastel"),("style","kawaii"),("style","babyish"),
        ("style","age regression"),("style","littlespace"),("style","ddlg"),
        # size namespace
        ("size","xs"),("size","small"),("size","medium"),("size","large"),
        ("size","xl"),("size","xxl"),("size","xxxl"),
        # material namespace
        ("material","cloth"),("material","disposable"),("material","plastic backed"),
        ("material","cloth backed"),("material","premium"),("material","ultra"),
        # rating namespace
        ("rating","safe"),("rating","suggestive"),("rating","explicit"),
        # character namespace
        ("character","animals"),("character","space"),("character","stars"),
        ("character","hearts"),("character","nursery"),("character","fantasy"),
        # color namespace
        ("color","white"),("color","pink"),("color","blue"),("color","yellow"),
        ("color","purple"),("color","green"),("color","rainbow"),("color","pastel"),
        # source namespace
        ("source","product photo"),("source","review"),("source","personal"),
        ("source","advertisement"),("source","fan art"),
        # meta namespace
        ("meta","favorite"),("meta","wishlist"),("meta","owned"),("meta","reviewed"),
    ]
    for ns_name, tag_name in default_tags:
        ns_id = ns_ids.get(ns_name)
        conn.execute(
            "INSERT OR IGNORE INTO tags (name, namespace_id) VALUES (?,?)",
            (tag_name, ns_id))
    conn.commit()


def init_library():
    """Public entry point — called from init_db and on first gallery open."""
    conn = get_connection()
    _init_library(conn)
    _seed_default_tags(conn)
    conn.close()


def ensure_library_tables():
    """
    Lazy guard — call this before any image_library / tags operation.
    Creates the tables if they don't exist (safe to call repeatedly).
    This handles the case where init_db() ran but init_library() failed,
    or where the user opened an older database that predates the library schema.
    """
    conn = get_connection()
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='image_library'"
    ).fetchone()
    conn.close()
    if not exists:
        print("[ensure_library_tables] image_library missing — creating now…")
        init_library()
        print("[ensure_library_tables] tables created OK")


# ── Tag CRUD ──────────────────────────────────────────────────────────────────

def get_all_namespaces():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM tag_namespaces ORDER BY sort_order, name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_tags(namespace_id=None, search="", limit=200):
    conn = get_connection()
    where, params = [], []
    if namespace_id:
        where.append("t.namespace_id=?"); params.append(namespace_id)
    if search:
        where.append("t.name LIKE ?"); params.append(f"%{search}%")
    sql = ("SELECT t.*, n.name AS ns_name, n.color AS ns_color "
           "FROM tags t LEFT JOIN tag_namespaces n ON n.id=t.namespace_id "
           + ("WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY t.count DESC, t.name LIMIT ?")
    rows = conn.execute(sql, params + [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_or_create_tag(name, namespace_id=None):
    """Return tag id, creating the tag if it doesn't exist."""
    name = name.strip().lower()
    if not name:
        return None
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM tags WHERE name=? AND (namespace_id=? OR (namespace_id IS NULL AND ? IS NULL))",
        (name, namespace_id, namespace_id)).fetchone()
    if row:
        tid = row[0]
    else:
        cur = conn.execute(
            "INSERT INTO tags (name, namespace_id) VALUES (?,?)", (name, namespace_id))
        tid = cur.lastrowid
    conn.commit(); conn.close()
    return tid


def search_tags(query, limit=30):
    """Autocomplete search — returns tags matching query prefix."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT t.id, t.name, t.count, n.name AS ns_name, n.color AS ns_color "
        "FROM tags t LEFT JOIN tag_namespaces n ON n.id=t.namespace_id "
        "WHERE t.name LIKE ? ORDER BY t.count DESC, t.name LIMIT ?",
        (f"%{query}%", limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _recalc_tag_counts(conn, tag_ids):
    for tid in tag_ids:
        n = conn.execute(
            "SELECT COUNT(*) FROM image_tags WHERE tag_id=?", (tid,)).fetchone()[0]
        conn.execute("UPDATE tags SET count=? WHERE id=?", (n, tid))


# ── Image Library CRUD ────────────────────────────────────────────────────────

def _md5(data):
    import hashlib
    return hashlib.md5(data).hexdigest() if data else None


def add_library_image(*, image_data=None, image_url=None, filename=None,
                      mime_type="image/jpeg", width=None, height=None,
                      source_url=None, source_name=None, notes=None,
                      product_id=None, tag_ids=None):
    """
    Add an image to the standalone library. No product required.
    Returns (image_id, 'added'|'duplicate').
    """
    conn = get_connection()
    h = _md5(image_data) if image_data else None
    if h:
        dup = conn.execute(
            "SELECT id FROM image_library WHERE hash_md5=?", (h,)).fetchone()
        if dup:
            conn.close()
            return dup[0], "duplicate"
    file_size = len(image_data) if image_data else None
    cur = conn.execute(
        "INSERT INTO image_library "
        "(image_data,image_url,filename,mime_type,width,height,file_size,"
        " hash_md5,notes,source_url,source_name,product_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (image_data, image_url, filename, mime_type, width, height,
         file_size, h, notes, source_url, source_name, product_id))
    iid = cur.lastrowid
    if tag_ids:
        conn.executemany(
            "INSERT OR IGNORE INTO image_tags (image_id,tag_id) VALUES (?,?)",
            [(iid, t) for t in tag_ids])
        _recalc_tag_counts(conn, tag_ids)
    conn.commit(); conn.close()
    return iid, "added"


def get_library_images(filter_tags=None, search_text=None, rating_min=0,
                       sort="newest", limit=200, offset=0, include_data=False):
    """
    Fetch images from the library with optional tag filtering.
    search_tags: list of tag_ids — returns images that have ALL tags.
    """
    conn = get_connection()
    wheres, params = [], []

    if filter_tags:
        for tid in filter_tags:
            wheres.append(
                "i.id IN (SELECT image_id FROM image_tags WHERE tag_id=?)")
            params.append(tid)

    if search_text:
        wheres.append(
            "(i.filename LIKE ? OR i.notes LIKE ? OR i.source_name LIKE ?)")
        params += [f"%{search_text}%"] * 3

    if rating_min > 0:
        wheres.append("i.rating>=?"); params.append(rating_min)

    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    order = {"newest":"i.date_added DESC","oldest":"i.date_added ASC",
             "rating":"i.rating DESC","name":"i.filename ASC",
             "size":"i.file_size DESC"}.get(sort, "i.date_added DESC")

    total = conn.execute(
        f"SELECT COUNT(*) FROM image_library i {where_sql}", params).fetchone()[0]

    data_col = "i.image_data," if include_data else ""
    rows = conn.execute(
        f"SELECT {data_col}i.id,i.image_url,i.filename,i.mime_type,i.width,i.height,"
        f"i.file_size,i.rating,i.notes,i.source_name,i.source_url,i.product_id,"
        f"i.date_added,i.hash_md5 "
        f"FROM image_library i {where_sql} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [limit, offset]).fetchall()
    conn.close()
    return total, [dict(r) for r in rows]


def get_library_image(image_id, include_data=True):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM image_library WHERE id=?", (image_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_image_tags(image_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT t.id, t.name, n.name AS ns_name, n.color AS ns_color "
        "FROM image_tags it "
        "JOIN tags t ON t.id=it.tag_id "
        "LEFT JOIN tag_namespaces n ON n.id=t.namespace_id "
        "WHERE it.image_id=? ORDER BY n.sort_order, t.name",
        (image_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_image_tags(image_id, tag_ids):
    """Replace all tags on an image with the given list."""
    conn = get_connection()
    old = [r[0] for r in conn.execute(
        "SELECT tag_id FROM image_tags WHERE image_id=?", (image_id,)).fetchall()]
    conn.execute("DELETE FROM image_tags WHERE image_id=?", (image_id,))
    if tag_ids:
        conn.executemany(
            "INSERT OR IGNORE INTO image_tags (image_id,tag_id) VALUES (?,?)",
            [(image_id, t) for t in tag_ids])
    _recalc_tag_counts(conn, list(set(old + list(tag_ids))))
    conn.execute("UPDATE image_library SET date_modified=datetime('now') WHERE id=?",
                 (image_id,))
    conn.commit(); conn.close()


def add_image_tag(image_id, tag_id):
    conn = get_connection()
    conn.execute("INSERT OR IGNORE INTO image_tags (image_id,tag_id) VALUES (?,?)",
                 (image_id, tag_id))
    _recalc_tag_counts(conn, [tag_id])
    conn.commit(); conn.close()


def remove_image_tag(image_id, tag_id):
    conn = get_connection()
    conn.execute("DELETE FROM image_tags WHERE image_id=? AND tag_id=?",
                 (image_id, tag_id))
    _recalc_tag_counts(conn, [tag_id])
    conn.commit(); conn.close()


def update_library_image(image_id, **fields):
    allowed = {"filename","notes","source_url","source_name","rating","product_id","image_url"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates: return
    updates["date_modified"] = datetime.now().isoformat()
    conn = get_connection()
    sets = ", ".join(f"{k}=?" for k in updates)
    conn.execute(f"UPDATE image_library SET {sets} WHERE id=?",
                 list(updates.values()) + [image_id])
    conn.commit(); conn.close()


def delete_library_image(image_id):
    conn = get_connection()
    conn.execute("DELETE FROM image_library WHERE id=?", (image_id,))
    conn.commit(); conn.close()


def get_library_stats():
    conn = get_connection()
    total   = conn.execute("SELECT COUNT(*) FROM image_library").fetchone()[0]
    blobs   = conn.execute("SELECT COUNT(*) FROM image_library WHERE image_data IS NOT NULL").fetchone()[0]
    size_mb = conn.execute(
        "SELECT COALESCE(SUM(file_size),0)/1048576.0 FROM image_library").fetchone()[0]
    tags    = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    tagged  = conn.execute(
        "SELECT COUNT(DISTINCT image_id) FROM image_tags").fetchone()[0]
    conn.close()
    return {"total":total,"blobs":blobs,"size_mb":round(size_mb,2),
            "total_tags":tags,"images_tagged":tagged}


def get_tag_cloud(limit=80):
    """Return top tags sorted by count for the sidebar cloud."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT t.id,t.name,t.count,n.name AS ns_name,n.color AS ns_color "
        "FROM tags t LEFT JOIN tag_namespaces n ON n.id=t.namespace_id "
        "WHERE t.count>0 ORDER BY t.count DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def migrate_product_images_to_library():
    """
    One-time migration: copy rows from old product_images table into
    the new image_library (preserving product_id link).
    Returns count migrated.
    """
    conn = get_connection()
    # Check if old table exists
    has_old = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='product_images'"
    ).fetchone()
    if not has_old:
        conn.close(); return 0
    rows = conn.execute(
        "SELECT * FROM product_images WHERE id NOT IN "
        "(SELECT COALESCE(p2.id,0) FROM product_images p2 "  # avoid re-migrate
        " JOIN image_library il ON il.hash_md5 = hex(p2.image_data))"
    ).fetchall()
    n = 0
    for row in rows:
        d = dict(row)
        data = d.get("image_data")
        if isinstance(data, memoryview): data = bytes(data)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO image_library "
                "(image_data,image_url,filename,mime_type,width,height,file_size,"
                " hash_md5,source_name,product_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (data, d.get("image_url"), d.get("filename"), d.get("mime_type","image/jpeg"),
                 d.get("width"), d.get("height"), d.get("file_size"),
                 _md5(data) if data else None,
                 d.get("source","product_images"), d.get("product_id")))
            n += 1
        except Exception:
            pass
    conn.commit(); conn.close()
    return n


# ── Download Job Tracking ─────────────────────────────────────────────────────

def create_download_job(site, query, limit_n=20):
    conn = get_connection()
    cur  = conn.execute(
        "INSERT INTO download_jobs (site,query,limit_n,status,started_at) VALUES(?,?,?,'pending',datetime('now'))",
        (site, query, limit_n))
    jid = cur.lastrowid; conn.commit(); conn.close(); return jid


def update_download_job(job_id, **fields):
    allowed = {"status","found","downloaded","duplicates","errors","finished_at","notes"}
    updates = {k:v for k,v in fields.items() if k in allowed}
    if "status" in updates and updates["status"] == "done":
        updates.setdefault("finished_at", datetime.now().isoformat())
    if not updates: return
    conn = get_connection()
    sets = ", ".join(f"{k}=?" for k in updates)
    conn.execute(f"UPDATE download_jobs SET {sets} WHERE id=?", list(updates.values())+[job_id])
    conn.commit(); conn.close()


def get_download_jobs(limit=50):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM download_jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close(); return [dict(r) for r in rows]


def get_site_credentials(site):
    conn = get_connection()
    row  = conn.execute("SELECT * FROM site_credentials WHERE site=?", (site,)).fetchone()
    conn.close(); return dict(row) if row else {}


def save_site_credentials(site, login=None, api_key=None, extra=None):
    import json as _j
    conn = get_connection()
    conn.execute(
        "INSERT INTO site_credentials(site,login,api_key,extra) VALUES(?,?,?,?) "
        "ON CONFLICT(site) DO UPDATE SET login=excluded.login, api_key=excluded.api_key, extra=excluded.extra",
        (site, login, api_key, _j.dumps(extra) if extra else None))
    conn.commit(); conn.close()
