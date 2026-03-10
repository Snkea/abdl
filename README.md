# ABDL Catalog System — LCARS Edition

A Python desktop application for cataloguing adult diaper and ABDL products,
with a built-in scraper and full database management UI.

## Requirements

```
pip install -r requirements.txt
playwright install chromium
```

`requirements.txt`:
```
PyQt6>=6.4.0
playwright>=1.40.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
```

---

## Run

```bash
python ui.py
```

---

## Tabs

| Tab | Description |
|-----|-------------|
| 📋 Catalog | Browse / filter / search 1300+ products |
| 🛒 Shopping List | Cart with qty, tax calculator, export |
| 🕷 Scraper | Run scrapers in-process or as external process |
| 📊 Stats | Live DB stats and scrape history |
| 🗄 Database | Site manager, product browser, health / maintenance |

---

## Standalone Scraper

```bash
python scrape_server.py                      # scrape all due sites
python scrape_server.py --force              # ignore schedule
python scrape_server.py --site "Tykables"   # one site
python scrape_server.py --list              # show all sites + status
python scrape_server.py --health            # DB health report
python scrape_server.py --seed              # load demo data
```

The UI's **🚀 External Process** button launches this as a child process,
streaming its output into the scraper log panel.

---

## File Layout

```
abdl/
├── ui.py               ← Main application (PyQt6 LCARS GUI)
├── database.py         ← SQLite schema, CRUD, all DB helpers
├── scraper.py          ← Playwright scraper + demo seed data
├── scrape_server.py    ← Standalone CLI scraper (run independently)
├── db_mgmt.py          ← DB health helpers (used by scrape_server --health)
├── requirements.txt
├── README.md
└── abdl_catalog.db     ← Auto-created on first run
```

---

## Adding Sites

Edit `scraper.py` → `SITE_PROFILES`:

```python
"My Site": {
    "type": "shopify",       # shopify | woocommerce | html
    "base": "https://mysite.com",
    "brand": "Brand Name",   # must match a brand in the DB
}
```

Then add a seed entry in `database.py` → `_seed_sites()`.

---

## LCARS Colour Palette

| Role | Hex |
|------|-----|
| Pink / primary | `#CC88AA` |
| Lavender | `#BB88FF` |
| Peach | `#FFAA66` |
| Mint | `#44FF88` |
| Gold / prices | `#FFDD00` |
| Sky / info | `#44CCFF` |
