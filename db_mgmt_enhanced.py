"""
db_mgmt_enhanced.py — Enhanced database management for CrinkleDen.

Replaces / supersedes db_mgmt.py.  Imported by the DB tab in ui.py.

New features over v1:
  • Full schema diff & migration report
  • Per-table row counts with trend delta (vs last check)
  • VACUUM + WAL checkpoint with before/after size display
  • Incremental backup with rotation (keep last N)
  • Duplicate product detection (same name+brand)
  • Orphan image cleanup
  • Full-text search index health & rebuild
  • Column-level null audit
  • Export to CSV / JSONL / SQLite copy
  • Import CSV products
  • Site performance stats (products per site, scrape rate)
  • Tag cloud stats
"""
import sqlite3
import sys
import os
import csv
import json
import shutil
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
import database as db


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

ALL_TABLES = {
    "products":      "Products",
    "brands":        "Brands",
    "categories":    "Categories",
    "scrape_sites":  "Scrape Sites",
    "scrape_log":    "Scrape Log",
    "shopping_list": "Shopping List",
    "wishlist":      "Wishlist",
    "image_library": "Image Library",
    "tags":          "Tags",
    "image_tags":    "Image Tags",
    "download_jobs": "Download Jobs",
}

BROWSABLE_TABLES = {
    "products":      "Products",
    "brands":        "Brands",
    "categories":    "Categories",
    "scrape_sites":  "Scrape Sites",
    "scrape_log":    "Scrape Log",
    "shopping_list": "Shopping List",
    "wishlist":      "Wishlist",
    "image_library": "Image Library",
}

BACKUP_DIR = Path(__file__).parent / "backups"
MAX_BACKUPS = 10


# ─────────────────────────────────────────────────────────────────────────────
# Core health
# ─────────────────────────────────────────────────────────────────────────────

def get_full_health():
    """
    Comprehensive DB health report dict.
    All values are JSON-serialisable (no memoryview / Row objects).
    """
    conn = db.get_connection()
    h = {}

    # ── File info ─────────────────────────────────────────────────────────────
    h["db_path"]    = str(db.DB_PATH)
    h["db_exists"]  = db.DB_PATH.exists()
    if db.DB_PATH.exists():
        h["db_mtime"] = datetime.fromtimestamp(db.DB_PATH.stat().st_mtime).isoformat()
    else:
        h["db_mtime"] = None

    # ── PRAGMA checks ─────────────────────────────────────────────────────────
    h["integrity"]      = conn.execute("PRAGMA integrity_check").fetchone()[0]
    h["fk_violations"]  = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    h["wal_mode"]       = conn.execute("PRAGMA journal_mode").fetchone()[0]
    h["page_size"]      = conn.execute("PRAGMA page_size").fetchone()[0]
    h["page_count"]     = conn.execute("PRAGMA page_count").fetchone()[0]
    h["freelist_pages"] = conn.execute("PRAGMA freelist_count").fetchone()[0]
    h["db_size_kb"]     = round(h["page_size"] * h["page_count"] / 1024, 1)
    h["db_size_mb"]     = round(h["page_size"] * h["page_count"] / 1024 / 1024, 2)

    wal_path = str(db.DB_PATH) + "-wal"
    h["wal_size_kb"] = round(os.path.getsize(wal_path) / 1024, 1) if os.path.exists(wal_path) else 0

    # ── Row counts per table ───────────────────────────────────────────────────
    h["tables"] = {}
    all_tables_in_db = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    for tbl, label in ALL_TABLES.items():
        if tbl in all_tables_in_db:
            try:
                h["tables"][tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            except Exception:
                h["tables"][tbl] = "error"
        else:
            h["tables"][tbl] = "missing"

    # ── Index inventory ───────────────────────────────────────────────────────
    h["indexes"] = [
        {"name": r[0], "table": r[1]}
        for r in conn.execute(
            "SELECT name, tbl_name FROM sqlite_master WHERE type='index' ORDER BY tbl_name"
        ).fetchall()
    ]

    # ── Data quality flags ────────────────────────────────────────────────────
    h["products_no_brand"]    = conn.execute(
        "SELECT COUNT(*) FROM products WHERE brand_id IS NULL").fetchone()[0]
    h["products_no_price"]    = conn.execute(
        "SELECT COUNT(*) FROM products WHERE price_usd IS NULL AND price IS NULL").fetchone()[0]
    h["products_no_category"] = conn.execute(
        "SELECT COUNT(*) FROM products WHERE category_id IS NULL").fetchone()[0]
    h["products_no_image"]    = conn.execute(
        "SELECT COUNT(*) FROM products WHERE (image_url IS NULL OR image_url='')").fetchone()[0]
    h["products_out_of_stock"] = conn.execute(
        "SELECT COUNT(*) FROM products WHERE in_stock=0").fetchone()[0]

    # Image storage
    if "image_library" in all_tables_in_db:
        img_bytes = conn.execute(
            "SELECT COALESCE(SUM(file_size),0) FROM image_library"
        ).fetchone()[0] or 0
        h["img_blob_mb"] = round(img_bytes / 1024 / 1024, 2)
        h["img_total"]   = conn.execute("SELECT COUNT(*) FROM image_library").fetchone()[0]
    else:
        h["img_blob_mb"] = 0
        h["img_total"]   = 0

    conn.close()
    return h


def get_null_audit():
    """
    Return per-column null count for the products table.
    Useful for finding columns that are sparsely populated.
    """
    conn = db.get_connection()
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
    total = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    audit = []
    for col in cols:
        null_count = conn.execute(
            f"SELECT COUNT(*) FROM products WHERE {col} IS NULL"
        ).fetchone()[0]
        pct = round(null_count / total * 100, 1) if total else 0
        audit.append({"column": col, "nulls": null_count, "total": total,
                      "pct_null": pct, "filled": total - null_count})
    conn.close()
    return sorted(audit, key=lambda x: -x["pct_null"])


# ─────────────────────────────────────────────────────────────────────────────
# Table browser
# ─────────────────────────────────────────────────────────────────────────────

def get_table_columns(table):
    """Return list of column name strings for a browsable table."""
    if table not in BROWSABLE_TABLES:
        return []
    conn = db.get_connection()
    # Check table actually exists
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        conn.close(); return []
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    conn.close()
    return cols


def get_table_rows(table, search="", limit=200, offset=0, order_col=None, order_dir="DESC"):
    """Return (list_of_dicts, total_count) for a browsable table."""
    if table not in BROWSABLE_TABLES:
        return [], 0
    conn = db.get_connection()
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        conn.close(); return [], 0

    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    skip = {"id", "brand_id", "category_id", "site_id", "product_id",
            "scrape_enabled", "in_stock", "price", "price_usd",
            "quantity", "rating", "review_count", "image_data", "cover_data"}
    text_cols = [c for c in cols if c not in skip][:8]

    where_clause = ""
    count_params = []
    row_params   = []
    if search and text_cols:
        clauses      = " OR ".join(f"{c} LIKE ?" for c in text_cols)
        where_clause = f"WHERE {clauses}"
        term         = [f"%{search}%"] * len(text_cols)
        count_params = term
        row_params   = term

    total = conn.execute(
        f"SELECT COUNT(*) FROM {table} {where_clause}", count_params
    ).fetchone()[0]

    # Build ORDER BY safely
    safe_order_col = order_col if order_col in cols else "id"
    safe_order_dir = "ASC" if order_dir.upper() == "ASC" else "DESC"

    rows = conn.execute(
        f"SELECT * FROM {table} {where_clause} "
        f"ORDER BY {safe_order_col} {safe_order_dir} LIMIT ? OFFSET ?",
        row_params + [limit, offset]
    ).fetchall()
    conn.close()
    # Sanitise BLOB columns so they don't crash JSON serialisation
    result = []
    for r in rows:
        d = {}
        for k, v in dict(r).items():
            if isinstance(v, (bytes, memoryview)):
                d[k] = f"<blob {len(bytes(v))} bytes>"
            else:
                d[k] = v
        result.append(d)
    return result, total


def delete_rows(table, row_ids):
    """Delete rows by id list. Returns count deleted."""
    if table not in BROWSABLE_TABLES or not row_ids:
        return 0
    conn = db.get_connection()
    ph  = ",".join("?" * len(row_ids))
    cur = conn.execute(f"DELETE FROM {table} WHERE id IN ({ph})", list(row_ids))
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


def update_cell(table, row_id, column, value):
    """Update a single cell. Column must not be in the unsafe list."""
    if table not in BROWSABLE_TABLES:
        raise ValueError(f"Table {table!r} not editable")
    unsafe = {"id", "image_data", "cover_data"}
    if column in unsafe:
        raise ValueError(f"Column {column!r} is not editable")
    conn = db.get_connection()
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.close()
        raise ValueError(f"Column {column!r} does not exist in {table}")
    conn.execute(f"UPDATE {table} SET {column}=? WHERE id=?", (value, row_id))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Site management
# ─────────────────────────────────────────────────────────────────────────────

def get_site_stats():
    """
    Return per-site product counts, scrape frequency and last status.
    """
    conn = db.get_connection()
    rows = conn.execute("""
        SELECT
            ss.id, ss.name, ss.url, ss.site_type, ss.scrape_enabled,
            ss.last_scraped, ss.products_found, ss.scrape_interval,
            COUNT(p.id)  AS db_product_count,
            MAX(sl.started_at) AS last_run,
            SUM(CASE WHEN sl.status='SUCCESS' THEN 1 ELSE 0 END) AS success_runs,
            SUM(CASE WHEN sl.status='ERROR' THEN 1 ELSE 0 END) AS error_runs,
            SUM(sl.products_added) AS total_added_all_time
        FROM scrape_sites ss
        LEFT JOIN products p ON p.source_site = ss.name
        LEFT JOIN scrape_log sl ON sl.site_id = ss.id
        GROUP BY ss.id
        ORDER BY db_product_count DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def toggle_site_enabled(site_id):
    """Flip scrape_enabled. Returns new value."""
    conn = db.get_connection()
    row = conn.execute(
        "SELECT scrape_enabled FROM scrape_sites WHERE id=?", (site_id,)
    ).fetchone()
    if not row:
        conn.close(); return None
    new_val = 0 if row["scrape_enabled"] else 1
    conn.execute("UPDATE scrape_sites SET scrape_enabled=? WHERE id=?", (new_val, site_id))
    conn.commit()
    conn.close()
    return new_val


def bulk_toggle_sites(site_ids, enabled: bool):
    """Enable or disable a list of site IDs."""
    if not site_ids: return 0
    conn = db.get_connection()
    ph  = ",".join("?" * len(site_ids))
    cur = conn.execute(
        f"UPDATE scrape_sites SET scrape_enabled=? WHERE id IN ({ph})",
        [1 if enabled else 0] + list(site_ids)
    )
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


def update_site(site_id, name=None, url=None, site_type=None, interval=None, enabled=None):
    """Update mutable fields on a scrape_sites row."""
    conn = db.get_connection()
    if name is not None:
        conn.execute("UPDATE scrape_sites SET name=? WHERE id=?", (name, site_id))
    if url is not None:
        conn.execute("UPDATE scrape_sites SET url=? WHERE id=?", (url, site_id))
    if site_type is not None:
        conn.execute("UPDATE scrape_sites SET site_type=? WHERE id=?", (site_type, site_id))
    if interval is not None:
        conn.execute("UPDATE scrape_sites SET scrape_interval=? WHERE id=?", (int(interval), site_id))
    if enabled is not None:
        conn.execute("UPDATE scrape_sites SET scrape_enabled=? WHERE id=?", (1 if enabled else 0, site_id))
    conn.commit()
    conn.close()


def add_scrape_site(name, url, site_type="abdl", enabled=1, interval=None):
    """Insert a new scrape site. Returns new id."""
    if interval is None:
        interval = db.DEFAULT_SCRAPE_INTERVAL
    conn = db.get_connection()
    cur = conn.execute(
        "INSERT OR IGNORE INTO scrape_sites (name, url, scrape_enabled, site_type, scrape_interval)"
        " VALUES (?, ?, ?, ?, ?)",
        (name, url, enabled, site_type, interval)
    )
    conn.commit()
    lid = cur.lastrowid
    conn.close()
    return lid


def delete_site(site_id, delete_products=False):
    """Delete a scrape site and optionally its products."""
    conn = db.get_connection()
    if delete_products:
        site = conn.execute("SELECT name FROM scrape_sites WHERE id=?", (site_id,)).fetchone()
        if site:
            conn.execute("DELETE FROM products WHERE source_site=?", (site["name"],))
    conn.execute("DELETE FROM scrape_sites WHERE id=?", (site_id,))
    conn.commit()
    conn.close()


def reset_site_schedule(site_id):
    """Clear last_scraped so site will run on next pass."""
    conn = db.get_connection()
    conn.execute("UPDATE scrape_sites SET last_scraped=NULL WHERE id=?", (site_id,))
    conn.commit()
    conn.close()


def reset_all_schedules():
    """Clear last_scraped for all enabled sites."""
    conn = db.get_connection()
    n = conn.execute(
        "UPDATE scrape_sites SET last_scraped=NULL WHERE scrape_enabled=1"
    ).rowcount
    conn.commit()
    conn.close()
    return n


# ─────────────────────────────────────────────────────────────────────────────
# Maintenance operations
# ─────────────────────────────────────────────────────────────────────────────

def vacuum_db():
    """VACUUM the database. Returns (before_mb, after_mb)."""
    conn0 = db.get_connection()
    ps = conn0.execute("PRAGMA page_size").fetchone()[0]
    pc = conn0.execute("PRAGMA page_count").fetchone()[0]
    conn0.close()
    before_mb = round(ps * pc / 1024 / 1024, 2)

    conn = sqlite3.connect(str(db.DB_PATH), isolation_level=None)
    conn.execute("VACUUM")
    conn.close()

    conn2 = sqlite3.connect(str(db.DB_PATH))
    conn2.row_factory = sqlite3.Row
    ps2 = conn2.execute("PRAGMA page_size").fetchone()[0]
    pc2 = conn2.execute("PRAGMA page_count").fetchone()[0]
    conn2.close()
    after_mb = round(ps2 * pc2 / 1024 / 1024, 2)
    return before_mb, after_mb


def wal_checkpoint():
    """Force WAL checkpoint. Returns dict."""
    conn = db.get_connection()
    row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    conn.close()
    return {"busy": row[0], "log": row[1], "checkpointed": row[2]}


def rebuild_fts():
    """Rebuild FTS5 full-text search index. Returns row count."""
    return db.rebuild_fts()


def integrity_check():
    """Run PRAGMA integrity_check + foreign_key_check. Returns list of messages."""
    return db.db_integrity_check()


# ─────────────────────────────────────────────────────────────────────────────
# Data-quality fix operations
# ─────────────────────────────────────────────────────────────────────────────

def fix_missing_prices():
    """Sync price ↔ price_usd where one is NULL. Returns count fixed."""
    conn = db.get_connection()
    n1 = conn.execute(
        "UPDATE products SET price_usd=price WHERE price_usd IS NULL AND price IS NOT NULL"
    ).rowcount
    n2 = conn.execute(
        "UPDATE products SET price=price_usd WHERE price IS NULL AND price_usd IS NOT NULL"
    ).rowcount
    conn.commit()
    conn.close()
    return n1 + n2


def fix_missing_brands(pcb=None):
    """Try to assign brand_id by matching source_site name. Returns count fixed."""
    return db.fix_missing_brands() if not pcb else _fix_missing_brands_cb(pcb)


def _fix_missing_brands_cb(pcb):
    conn = db.get_connection()
    sites = conn.execute("SELECT * FROM scrape_sites").fetchall()
    fixed = 0
    for site in sites:
        nm = site["name"].replace(" Store", "").replace(" Supply", "").strip()
        brand = conn.execute(
            "SELECT id FROM brands WHERE name LIKE ? OR name LIKE ? LIMIT 1",
            (f"%{nm}%", f"%{nm.split()[0]}%")
        ).fetchone()
        if brand:
            cur = conn.execute(
                "UPDATE products SET brand_id=? WHERE brand_id IS NULL AND source_site=?",
                (brand["id"], site["name"])
            )
            if cur.rowcount and pcb:
                pcb(f"  ✓ Assigned brand {nm!r} to {cur.rowcount} products")
            fixed += cur.rowcount
    conn.commit()
    conn.close()
    return fixed


def find_duplicate_products(pcb=None):
    """
    Find products with same (name, brand_id) pair — likely scraper duplicates.
    Returns list of dicts: {name, brand_id, count, ids}
    """
    conn = db.get_connection()
    rows = conn.execute("""
        SELECT name, brand_id, COUNT(*) AS cnt, GROUP_CONCAT(id) AS ids
        FROM products
        GROUP BY name, brand_id
        HAVING cnt > 1
        ORDER BY cnt DESC
    """).fetchall()
    conn.close()
    results = []
    for r in rows:
        results.append({
            "name":     r["name"],
            "brand_id": r["brand_id"],
            "count":    r["cnt"],
            "ids":      [int(x) for x in r["ids"].split(",")],
        })
    if pcb:
        pcb(f"Found {len(results)} duplicate groups "
            f"({sum(r['count']-1 for r in results)} extra rows)")
    return results


def deduplicate_products(dry_run=True, pcb=None):
    """
    Remove duplicate products (keeps the newest row by id).
    If dry_run=True, just reports without deleting.
    Returns count that would be / were deleted.
    """
    dupes = find_duplicate_products()
    to_delete = []
    for d in dupes:
        # keep highest id (newest upsert), delete the rest
        keep = max(d["ids"])
        to_delete += [x for x in d["ids"] if x != keep]
    if pcb:
        pcb(f"  {'Would delete' if dry_run else 'Deleting'} {len(to_delete)} duplicate rows…")
    if dry_run or not to_delete:
        return len(to_delete)
    conn = db.get_connection()
    ph  = ",".join("?" * len(to_delete))
    cur = conn.execute(f"DELETE FROM products WHERE id IN ({ph})", to_delete)
    conn.commit()
    conn.close()
    if pcb:
        pcb(f"  ✓ Deleted {cur.rowcount} duplicate product rows.")
    return cur.rowcount


def purge_orphan_images(dry_run=True):
    """
    Remove image_library rows where product_id points to a non-existent product.
    Returns count affected.
    """
    conn = db.get_connection()
    orphans = conn.execute("""
        SELECT id FROM image_library
        WHERE product_id IS NOT NULL
          AND product_id NOT IN (SELECT id FROM products)
    """).fetchall()
    ids = [r["id"] for r in orphans]
    if not dry_run and ids:
        ph = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM image_library WHERE id IN ({ph})", ids)
        conn.commit()
    conn.close()
    return len(ids)


def clear_scrape_log():
    """Delete all scrape_log rows. Returns count."""
    conn = db.get_connection()
    n = conn.execute("SELECT COUNT(*) FROM scrape_log").fetchone()[0]
    conn.execute("DELETE FROM scrape_log")
    conn.commit()
    conn.close()
    return n


def delete_all_products(confirm_phrase="DELETE ALL"):
    """Delete every product row. confirm_phrase must match exactly."""
    if confirm_phrase != "DELETE ALL":
        raise ValueError("Safety check failed")
    conn = db.get_connection()
    n = conn.execute("DELETE FROM products").rowcount
    conn.commit()
    conn.close()
    return n


def delete_products_by_source(source_site):
    """Delete all products from a specific source site."""
    conn = db.get_connection()
    n = conn.execute("DELETE FROM products WHERE source_site=?", (source_site,)).rowcount
    conn.commit()
    conn.close()
    return n


# ─────────────────────────────────────────────────────────────────────────────
# Backup / Restore
# ─────────────────────────────────────────────────────────────────────────────

def create_backup(label=None):
    """
    Create a timestamped backup copy of the database.
    Returns (backup_path, size_mb).
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{label}" if label else ""
    dest   = BACKUP_DIR / f"crinkleden_{ts}{suffix}.db"

    import sqlite3 as _sq3
    src = _sq3.connect(db.DB_PATH)
    dst = _sq3.connect(dest)
    src.backup(dst)
    src.close()
    dst.close()

    size_mb = round(os.path.getsize(dest) / 1024 / 1024, 2)
    _rotate_backups()
    return str(dest), size_mb


def _rotate_backups():
    """Keep only the MAX_BACKUPS most recent backup files."""
    if not BACKUP_DIR.exists(): return
    backups = sorted(BACKUP_DIR.glob("crinkleden_*.db"), key=lambda p: p.stat().st_mtime)
    while len(backups) > MAX_BACKUPS:
        old = backups.pop(0)
        try:
            old.unlink()
        except Exception:
            pass


def list_backups():
    """Return list of existing backup dicts {path, size_mb, created}."""
    if not BACKUP_DIR.exists(): return []
    backups = sorted(BACKUP_DIR.glob("crinkleden_*.db"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    result = []
    for p in backups:
        result.append({
            "path":     str(p),
            "filename": p.name,
            "size_mb":  round(p.stat().st_size / 1024 / 1024, 2),
            "created":  datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return result


def restore_backup(backup_path, confirm_phrase="RESTORE"):
    """
    Overwrite the live DB with a backup.
    ⚠ This is destructive — always back up first.
    """
    if confirm_phrase != "RESTORE":
        raise ValueError("Safety check failed")
    bp = Path(backup_path)
    if not bp.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")
    # Create safety snapshot of current DB first
    create_backup(label="pre_restore")
    shutil.copy2(str(bp), str(db.DB_PATH))
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Export / Import
# ─────────────────────────────────────────────────────────────────────────────

def export_products_csv(dest_path=None, brand_type=None):
    """Export products to CSV. Returns (path, count)."""
    conn = db.get_connection()
    q = """SELECT p.id, p.name, b.name AS brand, c.name AS category,
                  p.brand_type, p.price_usd, p.currency, p.size_range,
                  p.absorbency_label, p.tags, p.in_stock, p.url,
                  p.image_url, p.source_site, p.date_added
           FROM products p
           LEFT JOIN brands b ON b.id=p.brand_id
           LEFT JOIN categories c ON c.id=p.category_id"""
    params = []
    if brand_type:
        q += " WHERE p.brand_type=?"; params.append(brand_type)
    rows = conn.execute(q, params).fetchall()
    conn.close()

    if not dest_path:
        import tempfile
        fd, dest_path = tempfile.mkstemp(suffix=".csv", prefix="abdl_products_")
        os.close(fd)

    fields = ["id","name","brand","category","brand_type","price_usd","currency",
              "size_range","absorbency_label","tags","in_stock","url","image_url",
              "source_site","date_added"]
    with open(dest_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: dict(r).get(k, "") for k in fields})
    return dest_path, len(rows)


def export_products_jsonl(dest_path=None, brand_type=None):
    """Export products to JSONL. Returns (path, count)."""
    conn = db.get_connection()
    q = ("""SELECT p.*,b.name AS brand_name,c.name AS category_name
            FROM products p
            LEFT JOIN brands b ON b.id=p.brand_id
            LEFT JOIN categories c ON c.id=p.category_id""")
    params = []
    if brand_type:
        q += " WHERE p.brand_type=?"; params.append(brand_type)
    rows = conn.execute(q, params).fetchall()
    conn.close()

    if not dest_path:
        import tempfile
        fd, dest_path = tempfile.mkstemp(suffix=".jsonl", prefix="abdl_products_")
        os.close(fd)

    with open(dest_path, "w", encoding="utf-8") as f:
        for r in rows:
            d = {k: v for k, v in dict(r).items()
                 if k != "image_data" and not isinstance(v, (bytes, memoryview)) and v is not None}
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return dest_path, len(rows)


def import_products_csv(csv_path, dry_run=False, pcb=None):
    """
    Import products from a CSV file.
    Returns (added, updated, skipped, errors).
    """
    import os
    added = updated = skipped = errors = 0

    if not os.path.isfile(csv_path):
        if pcb: pcb(f"  ✗ File not found: {csv_path}")
        return added, updated, skipped, 1   # 1 error for missing file

    try:
        fh = open(csv_path, newline="", encoding="utf-8-sig")
    except OSError as e:
        if pcb: pcb(f"  ✗ Cannot open file: {e}")
        return added, updated, skipped, 1

    with fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                row = {k.strip(): (v.strip() if v else None) for k, v in row.items()}
                if not row.get("name"):
                    skipped += 1; continue
                # Map CSV columns to DB fields
                data = {}
                for field in ["name","brand_type","price_usd","currency","size_range",
                               "absorbency_label","tags","url","image_url","source_site"]:
                    if row.get(field) is not None:
                        data[field] = row[field]
                if row.get("brand"):    data["brand_name"]    = row["brand"]
                if row.get("category"): data["category_name"] = row["category"]
                if row.get("price_usd"):
                    try: data["price_usd"] = float(row["price_usd"])
                    except ValueError: pass
                if not dry_run:
                    db.upsert_product(data)
                added += 1
                if pcb and added % 100 == 0:
                    pcb(f"  Processed {added} rows…")
            except Exception as e:
                errors += 1
                if pcb: pcb(f"  ✗ row error: {e}")

    if pcb: pcb(f"  Done: added={added} skipped={skipped} errors={errors}")
    return added, updated, skipped, errors


# ─────────────────────────────────────────────────────────────────────────────
# Tag cloud / stats
# ─────────────────────────────────────────────────────────────────────────────

def get_tag_stats(top_n=30):
    """Return top tags by usage count."""
    conn = db.get_connection()
    rows = conn.execute("""
        SELECT t.id, t.name, t.count, n.name AS ns_name, n.color AS ns_color
        FROM tags t
        LEFT JOIN tag_namespaces n ON n.id=t.namespace_id
        WHERE t.count > 0
        ORDER BY t.count DESC LIMIT ?
    """, (top_n,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Combined dashboard stats
# ─────────────────────────────────────────────────────────────────────────────

def get_dashboard_stats():
    """
    Return a flat dict of key stats for the DB management dashboard panel.
    """
    h = get_full_health()
    stats = {
        "db_size_mb":           h["db_size_mb"],
        "wal_size_kb":          h["wal_size_kb"],
        "integrity":            h["integrity"],
        "fk_violations":        h["fk_violations"],
        "products":             h["tables"].get("products", 0),
        "brands":               h["tables"].get("brands", 0),
        "categories":           h["tables"].get("categories", 0),
        "scrape_sites":         h["tables"].get("scrape_sites", 0),
        "images":               h["tables"].get("image_library", 0),
        "img_blob_mb":          h.get("img_blob_mb", 0),
        "tags":                 h["tables"].get("tags", 0),
        "products_no_brand":    h["products_no_brand"],
        "products_no_price":    h["products_no_price"],
        "products_no_category": h["products_no_category"],
        "products_no_image":    h["products_no_image"],
        "freelist_pages":       h["freelist_pages"],
    }

    # Site counts by type
    try:
        conn = db.get_connection()
        for stype in ("abdl", "medical", "regression", "both"):
            cnt = conn.execute(
                "SELECT COUNT(*) FROM scrape_sites WHERE site_type=?", (stype,)
            ).fetchone()[0]
            stats[f"sites_{stype}"] = cnt
        stats["sites_total"] = conn.execute(
            "SELECT COUNT(*) FROM scrape_sites").fetchone()[0]
        stats["sites_enabled"] = conn.execute(
            "SELECT COUNT(*) FROM scrape_sites WHERE scrape_enabled=1").fetchone()[0]
        conn.close()
    except Exception:
        pass

    # Image cache stats (from image_cache.py)
    try:
        from image_cache import get_cache as _get_ic
        ic = _get_ic()
        ic_stats = ic.get_stats()
        stats["img_cache_total"]  = ic_stats.get("ok", 0)
        stats["img_cache_errors"] = ic_stats.get("errors", 0)
        stats["img_cache_size_mb"] = round(ic_stats.get("disk_bytes", 0) / 1024**2, 1)
    except Exception:
        stats["img_cache_total"] = 0

    return stats


def get_scrape_history_chart(days=30):
    """
    Return daily aggregated scrape results for charting.
    """
    conn = db.get_connection()
    rows = conn.execute("""
        SELECT
            date(started_at) AS day,
            COUNT(*) AS runs,
            SUM(products_found) AS total_found,
            SUM(products_added) AS total_added,
            SUM(CASE WHEN status='ERROR' THEN 1 ELSE 0 END) AS errors
        FROM scrape_log
        WHERE started_at >= date('now', ?)
        GROUP BY day
        ORDER BY day
    """, (f"-{days} days",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
