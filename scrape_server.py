#!/usr/bin/env python3
"""
scrape_server.py — CrinkleDen standalone scraper
====================================================
Can be run independently OR launched by the UI via QProcess.

Usage
-----
  python scrape_server.py                    # scrape all due sites
  python scrape_server.py --force            # ignore schedule
  python scrape_server.py --site "Tykables"  # one site (partial match ok)
  python scrape_server.py --list             # list sites + status
  python scrape_server.py --health           # DB health report
  python scrape_server.py --seed             # load demo data
  python scrape_server.py --json             # print JSON result at end
  python scrape_server.py --db PATH          # override database path

Exit codes: 0 = ok   1 = playwright missing   2 = error
"""

import sys, argparse, json, datetime, io
from pathlib import Path

# Force UTF-8 output on Windows (cp1252 can't encode emoji/unicode)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Ensure project root is on path regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parent))


# ── Logging helpers ────────────────────────────────────────────────────────

def ts():
    return datetime.datetime.now().strftime("%H:%M:%S")

def log(msg):
    print(f"[{ts()}] {msg}", flush=True)


# ── Bootstrap extension modules ────────────────────────────────────────────

def _bootstrap():
    """
    Initialise all extension modules before scraping begins:
      - abdl_logger  → errors.txt / timeouts.txt
      - abdl_sites   → verified ABDL site list + profiles
      - scraper_ext  → profile injection + image cache hook
      - image_cache  → local thumbnail cache
    """
    # 1. Debug logger
    try:
        from abdl_logger import log_error, log_scrape_result
        log("[init] abdl_logger ready (errors.txt / timeouts.txt)")
    except ImportError:
        log("[init] abdl_logger not found — file logging disabled")

    # 2. Image cache (for product thumbnails)
    try:
        from image_cache import get_cache
        get_cache()
        log("[init] Image cache ready (cache/)")
    except ImportError:
        pass

    # 3. Patch scraper profiles + image cache hook
    try:
        from scraper_extended import patch_scraper, add_extra_sites
        patch_scraper()
        n2 = add_extra_sites()
        if n2 > 0:
            log(f"[init] Added {n2} extra sites from scraper_extended")
    except ImportError:
        pass


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="CrinkleDen standalone scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--site",   help="Scrape one site by name (partial match ok)")
    ap.add_argument("--force",  action="store_true", help="Ignore scrape schedule")
    ap.add_argument("--list",   action="store_true", help="List all sites and exit")
    ap.add_argument("--health", action="store_true", help="Print DB health and exit")
    ap.add_argument("--seed",   action="store_true", help="Load demo data and exit")
    ap.add_argument("--json",   action="store_true", help="Print JSON result at end")
    ap.add_argument("--db",     default=None,        help="Override database path")
    ap.add_argument("--abdl-only", action="store_true", dest="abdl_only",
                    help="Only scrape verified ABDL sites (skip medical/regression)")
    args = ap.parse_args()

    # ── Database init ──────────────────────────────────────────────────────
    import database as db

    if args.db:
        db.DB_PATH = Path(args.db)
        log(f"Using DB: {db.DB_PATH}")

    try:
        db.init_db()
    except Exception as exc:
        log(f"ERROR DB init: {exc}")
        sys.exit(2)

    # ── Bootstrap extension modules ────────────────────────────────────────
    _bootstrap()

    # ── --health ──────────────────────────────────────────────────────────
    if args.health:
        try:
            import db_mgmt_enhanced as mgmt
            h = mgmt.get_full_health()
        except ImportError:
            import db_mgmt as mgmt
            h = mgmt.get_db_health()

        print(f"\n  Path      : {h.get('db_path', db.DB_PATH)}")
        print(f"  Size      : {h.get('db_size_mb', '?')} MB")
        print(f"  Integrity : {h.get('integrity', '?')}")
        print(f"  WAL mode  : {h.get('wal_mode', '?')}")
        print("\n  Row counts:")

        tables = h.get("tables", {})
        if tables:
            for tbl, cnt in sorted(tables.items()):
                print(f"    {tbl:<26} {cnt:>8,}")
        else:
            for key in sorted(h):
                if key.startswith("rows_"):
                    tbl = key[5:]
                    print(f"    {tbl:<26} {h[key]:>8,}")

        print(f"\n  Products without brand    : {h.get('products_no_brand', '?')}")
        print(f"  Products without price    : {h.get('products_no_price', '?')}")
        print(f"  Products without category : {h.get('products_no_category', '?')}")

        # Image cache stats if available
        try:
            from image_cache import get_cache
            cs = get_cache().get_stats()
            print(f"  Image cache               : {cs['ok']:,} cached  "
                  f"({cs['disk_human']} on disk)")
        except ImportError:
            pass

        print()
        return

    # ── --list ─────────────────────────────────────────────────────────────
    if args.list:
        sites = db.get_scrape_sites()
        print(f"\n  {'ID':<4}  {'Name':<34}  {'Type':<10}  {'Brand':<10}  En  Products  Next")
        print("  " + "─" * 82)
        for s in sites:
            en  = "✓" if s["scrape_enabled"] else "✗"
            nxt = db.next_scrape_time(s) or "due now"
            bt  = s.get("brand_type") or s.get("site_type") or "?"
            print(
                f"  {s['id']:<4}  {s['name']:<34}  "
                f"{(s['site_type'] or ''):<10}  {bt:<10}  "
                f"{en}   {(s['products_found'] or 0):<9}  {nxt}"
            )
        enabled  = sum(1 for s in sites if s["scrape_enabled"])
        disabled = len(sites) - enabled
        print(f"\n  {enabled} enabled / {disabled} disabled  ({len(sites)} total)\n")
        return

    # ── Import scraper ─────────────────────────────────────────────────────
    try:
        from scraper import (scrape_all, scrape_site_by_id, seed_demo_data,
                             SCRAPE_AVAILABLE, MAX_CONCURRENT)
        # scrape_site_by_id may be named differently — try alias
        scrape_site = scrape_site_by_id
    except ImportError as exc:
        log(f"ERROR: scraper import failed: {exc}")
        sys.exit(1)

    # Try legacy name too
    try:
        from scraper import scrape_site
    except ImportError:
        pass   # scrape_site already set above

    if not SCRAPE_AVAILABLE:
        log("ERROR: Playwright not installed — scraper is disabled.")
        log("  Install it with:")
        log("    pip install playwright")
        log("    playwright install chromium")
        sys.exit(1)

    # ── --seed ─────────────────────────────────────────────────────────────
    if args.seed:
        log("Loading demo data…")
        n = seed_demo_data(pcb=log, force=True)
        log(f"Done — {n} demo products loaded")
        return

    # ── Scrape ─────────────────────────────────────────────────────────────
    results = []

    if args.site:
        # Find by name (exact match first, then partial)
        sites  = db.get_scrape_sites()
        name_l = args.site.lower()
        target = (
            next((s for s in sites if s["name"].lower() == name_l), None) or
            next((s for s in sites if name_l in s["name"].lower()), None)
        )
        if not target:
            log(f"ERROR: No site matching '{args.site}'")
            log("Available sites:")
            for s in sites:
                log(f"  {s['id']:>4}  {s['name']}")
            sys.exit(2)

        log(f"Scraping: {target['name']}  force={args.force}")
        try:
            result = scrape_site(target["id"], pcb=log, lcb=log, force=args.force)
        except TypeError:
            result = scrape_site(target, pcb=log, lcb=log, force=args.force)
        results = [result] if isinstance(result, dict) else (result or [])

    else:
        # Scrape all enabled sites
        all_sites = db.get_scrape_sites()
        enabled   = [s for s in all_sites if s["scrape_enabled"]]

        # --abdl-only: filter to verified ABDL brand_type only
        if args.abdl_only:
            try:
                from abdl_sites import VERIFIED_ABDL_SITES
                verified_urls = {s["url"].rstrip("/") for s in VERIFIED_ABDL_SITES}
                enabled = [
                    s for s in enabled
                    if s.get("url","").rstrip("/") in verified_urls
                    or s.get("brand_type","").lower() == "abdl"
                ]
                log(f"--abdl-only: {len(enabled)} ABDL-specific sites selected")
            except ImportError:
                log("--abdl-only: abdl_sites.py not found, scraping all enabled sites")

        log(f"Scraping {len(enabled)} enabled sites  "
            f"(max {MAX_CONCURRENT} browsers, force={args.force})")
        results = scrape_all(pcb=log, lcb=log, force=args.force)

    # ── Summary ────────────────────────────────────────────────────────────
    ok    = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "SUCCESS")
    skip  = sum(1 for r in results if isinstance(r, dict) and r.get("status") in ("SKIPPED","SKIP"))
    err   = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "ERROR")
    total = sum(r.get("found", 0) for r in results if isinstance(r, dict))

    print()
    log("═" * 50)
    log("DONE")
    log(f"  Scraped: {ok}   Skipped: {skip}   Errors: {err}   Products found: {total}")
    for r in results:
        if isinstance(r, dict) and r.get("status") == "ERROR":
            log(f"  ✗ [{r.get('site','?')}]: {r.get('error','')}")

    if args.json:
        print("\n--- JSON RESULT ---")
        print(json.dumps(results, indent=2, default=str))

    # Log summary to abdl_logger
    try:
        from abdl_logger import log_scrape_result
        for r in results:
            if isinstance(r, dict):
                log_scrape_result(
                    r.get("site", "?"),
                    r.get("status", "?"),
                    r.get("found", 0),
                    r.get("error", ""),
                )
    except ImportError:
        pass

    sys.exit(0 if err == 0 else 2)


if __name__ == "__main__":
    main()
