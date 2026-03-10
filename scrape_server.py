#!/usr/bin/env python3
"""
scrape_server.py -- Standalone ABDL Catalog scraper.
Can be run independently OR launched by the UI via QProcess.

Usage:
  python scrape_server.py              # scrape all due sites
  python scrape_server.py --force      # force all sites
  python scrape_server.py --site NAME  # one site (partial name ok)
  python scrape_server.py --list       # list sites + status
  python scrape_server.py --health     # DB health check
  python scrape_server.py --seed       # load demo data

Exit: 0=ok  1=no playwright  2=error
"""
import sys, argparse, json, datetime, io
# Force UTF-8 on Windows (cp1252 can't encode emoji/unicode in log messages)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))


def ts():
    return datetime.datetime.now().strftime("%H:%M:%S")

def log(msg):
    print(f"[{ts()}] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="ABDL Catalog standalone scraper")
    ap.add_argument("--site",   help="Scrape one site by name")
    ap.add_argument("--force",  action="store_true", help="Ignore schedule")
    ap.add_argument("--list",   action="store_true", help="List sites and exit")
    ap.add_argument("--health", action="store_true", help="DB health and exit")
    ap.add_argument("--seed",   action="store_true", help="Load demo data and exit")
    ap.add_argument("--json",   action="store_true", help="Print JSON result")
    ap.add_argument("--db",     default=None,        help="Override DB path")
    args = ap.parse_args()

    import database as db
    if args.db:
        db.DB_PATH = Path(args.db)

    try:
        db.init_db()
    except Exception as exc:
        log(f"ERROR DB init: {exc}"); sys.exit(2)

    if args.health:
        import db_mgmt
        h = db_mgmt.get_db_health()
        print(f"\n  Path: {h['db_path']}")
        print(f"  Size: {h['db_size_kb']} KB")
        print(f"  Integrity: {h['integrity']}")
        print(f"  FK violations: {h['fk_violations']}")
        print("\n  Row counts:")
        for tbl, cnt in h["tables"].items():
            print(f"    {tbl:<22} {cnt:>6}")
        print(f"\n  No brand:    {h['products_no_brand']}")
        print(f"  No price:    {h['products_no_price']}")
        print(f"  No category: {h['products_no_category']}")
        return

    if args.list:
        sites = db.get_scrape_sites()
        print(f"\n  {'ID':<4}  {'Name':<32}  {'Type':<8}  En  Products  Next")
        print("  " + "-" * 70)
        for s in sites:
            en  = "Y" if s["scrape_enabled"] else "N"
            nxt = db.next_scrape_time(s)
            print(f"  {s['id']:<4}  {s['name']:<32}  {(s['site_type'] or ''):<8}"
                  f"  {en}   {(s['products_found'] or 0):<9}  {nxt}")
        enabled = sum(1 for s in sites if s["scrape_enabled"])
        print(f"\n  {enabled} enabled / {len(sites)-enabled} disabled  ({len(sites)} total)\n")
        return

    try:
        from scraper import (scrape_all, scrape_site, seed_demo_data,
                             SCRAPE_AVAILABLE, MAX_CONCURRENT)
    except ImportError as exc:
        log(f"ERROR: scraper import: {exc}"); sys.exit(1)

    if not SCRAPE_AVAILABLE:
        log("ERROR: Playwright not installed.")
        log("  pip install playwright && playwright install chromium")
        sys.exit(1)

    if args.seed:
        log("Loading demo data...")
        n = seed_demo_data(pcb=log, force=True)
        log(f"Done -- {n} demo products loaded")
        return

    results = []
    if args.site:
        sites  = db.get_scrape_sites()
        target = next((s for s in sites if args.site.lower() == s["name"].lower()), None)
        if not target:
            target = next((s for s in sites if args.site.lower() in s["name"].lower()), None)
        if not target:
            log(f"ERROR: No site matching '{args.site}'")
            for s in sites: log(f"  {s['id']:>3}  {s['name']}")
            sys.exit(2)
        log(f"Scraping: {target['name']}  force={args.force}")
        results = [scrape_site(target, pcb=log, lcb=log, force=args.force)]
    else:
        enabled = sum(1 for s in db.get_scrape_sites() if s["scrape_enabled"])
        log(f"Scraping all {enabled} enabled sites  (max {MAX_CONCURRENT} browsers, force={args.force})")
        results = scrape_all(pcb=log, lcb=log, force=args.force)

    ok   = sum(1 for r in results if r.get("status") == "SUCCESS")
    skip = sum(1 for r in results if r.get("status") == "SKIPPED")
    err  = sum(1 for r in results if r.get("status") == "ERROR")
    total= sum(r.get("found", 0) for r in results)

    print()
    log("=== DONE ===")
    log(f"  Scraped: {ok}  Skipped: {skip}  Errors: {err}  Products: {total}")
    for r in results:
        if r.get("status") == "ERROR":
            log(f"  ERROR [{r.get('site','?')}]: {r.get('error','')}")

    if args.json:
        print("\n--- JSON ---")
        print(json.dumps(results, indent=2, default=str))

    sys.exit(0 if err == 0 else 2)


if __name__ == "__main__":
    main()
