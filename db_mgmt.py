"""
db_mgmt.py — Database management helpers for ABDL Catalog.
Imported by db_tab.py and available standalone.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import database as db

# Tables exposed in the browser
BROWSABLE_TABLES = {
    "products":      "Products",
    "brands":        "Brands",
    "categories":    "Categories",
    "scrape_sites":  "Scrape Sites",
    "scrape_log":    "Scrape Log",
    "shopping_list": "Shopping List",
    "wishlist":      "Wishlist",
}


def get_table_columns(table):
    """Return list of column name strings for a table."""
    if table not in BROWSABLE_TABLES:
        return []
    conn = db.get_connection()
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    conn.close()
    return cols


def get_table_rows(table, search="", limit=200, offset=0):
    """Return (list_of_dicts, total_count) for a browsable table."""
    if table not in BROWSABLE_TABLES:
        return [], 0
    conn = db.get_connection()
    cols = get_table_columns(table)

    where_clause = ""
    count_params = []
    row_params = []
    if search:
        # Search across text-ish columns (skip purely numeric FK columns)
        skip = {"id", "brand_id", "category_id", "site_id", "product_id",
                "scrape_enabled", "in_stock", "price", "price_usd",
                "quantity", "rating", "review_count"}
        text_cols = [c for c in cols if c not in skip][:8]
        if text_cols:
            clauses = " OR ".join(f"{c} LIKE ?" for c in text_cols)
            where_clause = f"WHERE {clauses}"
            term = [f"%{search}%"] * len(text_cols)
            count_params = term
            row_params = term

    total = conn.execute(
        f"SELECT COUNT(*) FROM {table} {where_clause}", count_params
    ).fetchone()[0]

    rows = conn.execute(
        f"SELECT * FROM {table} {where_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        row_params + [limit, offset]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def delete_rows(table, row_ids):
    """Delete rows by id list. Returns count deleted."""
    if table not in BROWSABLE_TABLES or not row_ids:
        return 0
    conn = db.get_connection()
    ph = ",".join("?" * len(row_ids))
    cur = conn.execute(f"DELETE FROM {table} WHERE id IN ({ph})", list(row_ids))
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


def toggle_site_enabled(site_id):
    """Flip scrape_enabled for a scrape site. Returns new value (0 or 1)."""
    conn = db.get_connection()
    row = conn.execute(
        "SELECT scrape_enabled FROM scrape_sites WHERE id=?", (site_id,)
    ).fetchone()
    if not row:
        conn.close()
        return None
    new_val = 0 if row["scrape_enabled"] else 1
    conn.execute(
        "UPDATE scrape_sites SET scrape_enabled=? WHERE id=?", (new_val, site_id)
    )
    conn.commit()
    conn.close()
    return new_val


def update_site(site_id, name=None, url=None, site_type=None):
    """Update mutable fields on a scrape_sites row."""
    conn = db.get_connection()
    if name:
        conn.execute("UPDATE scrape_sites SET name=? WHERE id=?", (name, site_id))
    if url:
        conn.execute("UPDATE scrape_sites SET url=? WHERE id=?", (url, site_id))
    if site_type:
        conn.execute("UPDATE scrape_sites SET site_type=? WHERE id=?", (site_type, site_id))
    conn.commit()
    conn.close()


def add_scrape_site(name, url, site_type="abdl", enabled=1):
    """Insert a new scrape site. Returns new id."""
    conn = db.get_connection()
    cur = conn.execute(
        "INSERT OR IGNORE INTO scrape_sites (name, url, scrape_enabled, site_type, scrape_interval)"
        " VALUES (?, ?, ?, ?, ?)",
        (name, url, enabled, site_type, db.DEFAULT_SCRAPE_INTERVAL)
    )
    conn.commit()
    lid = cur.lastrowid
    conn.close()
    return lid


def get_db_health():
    """Return a dict with full DB health info."""
    from database import DB_PATH
    conn = db.get_connection()
    h = {}
    h["db_path"]       = str(DB_PATH)
    h["integrity"]     = conn.execute("PRAGMA integrity_check").fetchone()[0]
    h["fk_violations"] = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    h["wal_mode"]      = conn.execute("PRAGMA journal_mode").fetchone()[0]
    h["page_size"]     = conn.execute("PRAGMA page_size").fetchone()[0]
    h["page_count"]    = conn.execute("PRAGMA page_count").fetchone()[0]
    h["freelist"]      = conn.execute("PRAGMA freelist_count").fetchone()[0]
    h["db_size_kb"]    = round(h["page_size"] * h["page_count"] / 1024, 1)

    h["tables"] = {}
    for tbl in BROWSABLE_TABLES:
        try:
            h["tables"][tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        except Exception:
            h["tables"][tbl] = "error"

    h["indexes"] = [
        dict(r) for r in conn.execute(
            "SELECT name, tbl_name FROM sqlite_master WHERE type='index' ORDER BY tbl_name"
        ).fetchall()
    ]

    h["products_no_brand"]    = conn.execute(
        "SELECT COUNT(*) FROM products WHERE brand_id IS NULL"
    ).fetchone()[0]
    h["products_no_price"]    = conn.execute(
        "SELECT COUNT(*) FROM products WHERE price_usd IS NULL AND price IS NULL"
    ).fetchone()[0]
    h["products_no_category"] = conn.execute(
        "SELECT COUNT(*) FROM products WHERE category_id IS NULL"
    ).fetchone()[0]
    conn.close()
    return h


def vacuum_db():
    """VACUUM the SQLite database to reclaim space."""
    from database import DB_PATH
    # VACUUM must run outside WAL transaction — use raw connection
    conn = sqlite3.connect(str(DB_PATH), isolation_level=None)
    conn.execute("VACUUM")
    conn.close()


def reindex_fts():
    """Rebuild FTS5 search index."""
    conn = db.get_connection()
    conn.execute("INSERT INTO products_fts(products_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()


def fix_missing_prices():
    """Sync price <-> price_usd where one is missing."""
    conn = db.get_connection()
    conn.execute(
        "UPDATE products SET price_usd=price WHERE price_usd IS NULL AND price IS NOT NULL"
    )
    conn.execute(
        "UPDATE products SET price=price_usd WHERE price IS NULL AND price_usd IS NOT NULL"
    )
    conn.commit()
    conn.close()


def fix_missing_brands():
    """Attempt to assign brand_id by matching source_site to brand names."""
    conn = db.get_connection()
    sites = conn.execute("SELECT * FROM scrape_sites").fetchall()
    fixed = 0
    for site in sites:
        # Try stripping common suffixes to match brand name
        name_clean = (
            site["name"]
            .replace(" Store", "")
            .replace(" Supply", "")
            .replace(" Products", "")
            .replace(" USA", "")
            .strip()
        )
        brand = conn.execute(
            "SELECT id FROM brands WHERE name LIKE ? OR name LIKE ? LIMIT 1",
            (f"%{name_clean}%", f"%{site['name'].split()[0]}%"),
        ).fetchone()
        if brand:
            cur = conn.execute(
                "UPDATE products SET brand_id=? WHERE brand_id IS NULL AND source_site=?",
                (brand["id"], site["name"]),
            )
            fixed += cur.rowcount
    conn.commit()
    conn.close()
    return fixed


def clear_scrape_log():
    """Delete all scrape_log rows."""
    conn = db.get_connection()
    n = conn.execute("SELECT COUNT(*) FROM scrape_log").fetchone()[0]
    conn.execute("DELETE FROM scrape_log")
    conn.commit()
    conn.close()
    return n


def delete_all_products():
    """Delete every product row."""
    conn = db.get_connection()
    n = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.execute("DELETE FROM products")
    conn.commit()
    conn.close()
    return n
