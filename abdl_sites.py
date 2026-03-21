"""
abdl_sites.py — Verified ABDL store registry
=============================================
Source: https://www.reddit.com/r/ABDL/wiki/stores/
Last updated from wiki: 2026-03

All sites in VERIFIED_ABDL_SITES are confirmed ABDL-specific or ABDL-aware
retailers.  Medical/incontinence-only retailers are in a separate list.
Offline / defunct stores are NOT included.

Each entry:
    name       : display name
    url        : base URL
    region     : US | CA | UK | EU | AU | JP | WORLD
    site_type  : shopify | woocommerce | html | api
    brand_type : abdl | both
    ships_intl : True/False
    discreet   : True/False (known discreet shipping)
    tags       : comma-separated product categories
    notes      : short freetext description
"""

# ── Primary ABDL product stores ──────────────────────────────────────────────

VERIFIED_ABDL_SITES = [
    # ── North America ──────────────────────────────────────────────────────
    {
        "name": "ABUniverse USA",
        "url": "https://www.abuniverse.com",
        "region": "US",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,onesies,accessories",
        "notes": "Super Dry Kids, Cushies, DinoRawrz, PeekABU, Space, LittlePawz",
    },
    {
        "name": "Tykables",
        "url": "https://tykables.com",
        "region": "US",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,clothing,accessories,onesies",
        "notes": "Tykables hook-and-loop diapers, NRU Str8Ups, physical store IL",
    },
    {
        "name": "Rearz Inc",
        "url": "https://rearz.ca",
        "region": "CA",
        "site_type": "shopify",
        "brand_type": "both",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,onesies,pacifiers,bottles,plastic_pants",
        "notes": "Rearz, Bambino, Abena, Tena, InControl reseller",
    },
    {
        "name": "LittleForBig",
        "url": "https://www.littleforbig.com",
        "region": "US",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,onesies,pajamas,pacifiers,socks",
        "notes": "DDlg focused ABDL store",
    },
    {
        "name": "ABDL Company",
        "url": "https://www.theabdlcompany.com",
        "region": "US",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,pacifiers,onesies,accessories",
        "notes": "Dotty, Rearz exclusive NA distributor",
    },
    {
        "name": "Baby Pants",
        "url": "https://www.babypants.com",
        "region": "US",
        "site_type": "html",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "cloth_diapers,onesies,training_pants",
        "notes": "California-based, cloth diapers and onesies",
    },
    {
        "name": "Bambino Diapers",
        "url": "https://www.bambinodiapers.com",
        "region": "US",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,accessories",
        "notes": "Classico, Bianco, Bellissimo, Abena reseller",
    },
    {
        "name": "Changing Times Diaper Co",
        "url": "https://www.changingtimesdiaperco.com",
        "region": "US",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,pacifiers,accessories",
        "notes": "Las Vegas ABDL store, online and physical",
    },
    {
        "name": "DDLG Playground",
        "url": "https://ddlgplayground.com",
        "region": "US",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": False,
        "tags": "pacifiers,bottles,onesies,accessories",
        "notes": "DDLG focused, pacifiers, onesies",
    },
    {
        "name": "Wearing Clouds",
        "url": "https://www.wearingclouds.com",
        "region": "US",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,accessories,samples",
        "notes": "Custom diaper sample kits, most ABDL brands",
    },
    {
        "name": "Lil Kink Boutique",
        "url": "https://www.lilkinkboutique.com",
        "region": "US",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,pajamas,clothing,rompers,accessories",
        "notes": "Diaper sample packs, pajamas, playsuits",
    },
    {
        "name": "Little Lavender",
        "url": "https://www.littlelavender.shop",
        "region": "US",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "clothing,pacifiers,sippy_cups,accessories",
        "notes": "ABDL clothing and accessories",
    },
    {
        "name": "Trest Elite",
        "url": "https://trestelite.com",
        "region": "US",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers",
        "notes": "Trest Elite 9500ml briefs",
    },
    {
        "name": "ABUniverse Canada",
        "url": "https://ca.abuniverse.com",
        "region": "CA",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": False,
        "discreet": True,
        "tags": "diapers,onesies,accessories",
        "notes": "ABU Canada store",
    },
    {
        "name": "Babykins",
        "url": "https://www.babykins.com",
        "region": "CA",
        "site_type": "html",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "cloth_diapers,plastic_pants,accessories",
        "notes": "Quality cloth diapers and plastic pants",
    },
    {
        "name": "InControl Diapers",
        "url": "https://www.incontrolbriefs.com",
        "region": "CA",
        "site_type": "shopify",
        "brand_type": "both",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,waterproof_pants",
        "notes": "Affiliated with Rearz, free ship US/CA $40+",
    },
    {
        "name": "Little Northwood",
        "url": "https://www.littlenorthwood.com",
        "region": "CA",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,plushies,onesies",
        "notes": "Quebec, Little Quest diapers",
    },
    {
        "name": "Cottontailz",
        "url": "https://cottontailz.com",
        "region": "CA",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers",
        "notes": "Flutterhops diapers",
    },
    {
        "name": "Pacifier Addict",
        "url": "https://www.pacifieraddict.com",
        "region": "CA",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "pacifiers,bottles,accessories",
        "notes": "Large range of adult pacifiers, associated with Rearz",
    },
    # ── United Kingdom ─────────────────────────────────────────────────────
    {
        "name": "ABUniverse UK",
        "url": "https://uk.abuniverse.com",
        "region": "UK",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,onesies,accessories",
        "notes": "ABU UK store",
    },
    {
        "name": "Cuddlz",
        "url": "https://www.cuddlz.com",
        "region": "UK",
        "site_type": "woocommerce",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,plastic_pants,pacifiers,accessories",
        "notes": "Custom printed adult diapers",
    },
    {
        "name": "The Dotty Diaper Company",
        "url": "https://www.dottydiapers.co.uk",
        "region": "UK",
        "site_type": "woocommerce",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers",
        "notes": "UK health company, alternative adult nappy designs",
    },
    {
        "name": "Nappies R Us",
        "url": "https://www.nappiesrus.co.uk",
        "region": "UK",
        "site_type": "woocommerce",
        "brand_type": "both",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,plastic_pants,pacifiers,onesies",
        "notes": "Large incontinence + ABDL range, ABU Cushies",
    },
    {
        "name": "Inner Child",
        "url": "https://www.innerchilduk.com",
        "region": "UK",
        "site_type": "html",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,pacifiers,bottles,plastic_pants,clothing",
        "notes": "Printed and plain adult diapers",
    },
    {
        "name": "Cosy n Dry",
        "url": "https://www.cosy-n-dry.com",
        "region": "UK",
        "site_type": "html",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,clothing,accessories",
        "notes": "UK leading AB retailer, custom clothing",
    },
    {
        "name": "Innocent Dreams",
        "url": "https://www.innocentdreamsuk.com",
        "region": "UK",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "onesies,dresses,rompers,sleep_suits",
        "notes": "ABDL clothing store",
    },
    {
        "name": "Snuggly Bears Emporium",
        "url": "https://snugglybears.co.uk",
        "region": "UK",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "clothing,pacifiers,plushies,accessories",
        "notes": "Free shipping UK/EU/US",
    },
    # ── Europe ─────────────────────────────────────────────────────────────
    {
        "name": "ABDL Factory",
        "url": "https://www.abdlfactory.com",
        "region": "EU",
        "site_type": "woocommerce",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,cloth_diapers,onesies,pacifiers,accessories",
        "notes": "Netherlands, large range ABU/Tykables/Rearz/Bambino",
    },
    {
        "name": "ABUniverse EU",
        "url": "https://eu.abuniverse.com",
        "region": "EU",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": False,
        "discreet": True,
        "tags": "diapers,accessories",
        "notes": "ABU continental Europe store",
    },
    {
        "name": "Buntewindel",
        "url": "https://buntewindel.de",
        "region": "EU",
        "site_type": "woocommerce",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers",
        "notes": "Germany, official Fabine diaper shop",
    },
    {
        "name": "Cloudrys",
        "url": "https://www.cloudrys.com",
        "region": "EU",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers",
        "notes": "Germany, Cloudrys Toys and Clouds diapers",
    },
    {
        "name": "Diaper Minister",
        "url": "https://www.diaper-minister.com",
        "region": "EU",
        "site_type": "woocommerce",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,accessories",
        "notes": "France, Kiddo diapers, EU reseller of ABU/Rearz/Tykables",
    },
    {
        "name": "Euro DL",
        "url": "https://www.eurodl.com",
        "region": "EU",
        "site_type": "html",
        "brand_type": "both",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,plastic_pants,onesies,pacifiers,accessories",
        "notes": "Netherlands, large range, sample packs",
    },
    {
        "name": "Cuddle Kingdom",
        "url": "https://www.cuddlekingdom.com",
        "region": "EU",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,onesies,bottles,pacifiers",
        "notes": "Netherlands",
    },
    {
        "name": "Wilulu",
        "url": "https://www.wilulu.de",
        "region": "EU",
        "site_type": "woocommerce",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,onesies,accessories",
        "notes": "Germany, diapers and ageplay accessories",
    },
    {
        "name": "Privatina",
        "url": "https://privatina.com",
        "region": "EU",
        "site_type": "html",
        "brand_type": "abdl",
        "ships_intl": True,
        "discreet": True,
        "tags": "clothing,onesies,custom",
        "notes": "Poland, best custom AB/DL clothes, high quality",
    },
    # ── Asia / Pacific ──────────────────────────────────────────────────────
    {
        "name": "ABUniverse Japan",
        "url": "https://jp.abuniverse.com",
        "region": "JP",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": False,
        "discreet": True,
        "tags": "diapers,accessories",
        "notes": "ABU Japan, also carries Crinklz",
    },
    {
        "name": "Littles Down Under",
        "url": "https://www.littlesdownunder.com",
        "region": "AU",
        "site_type": "shopify",
        "brand_type": "both",
        "ships_intl": True,
        "discreet": True,
        "tags": "diapers,pacifiers,onesies,cloth_diapers",
        "notes": "Australia, large selection, warehouse visits welcome",
    },
    {
        "name": "MyABDLSupplies",
        "url": "https://www.myabdlsupplies.com.au",
        "region": "AU",
        "site_type": "shopify",
        "brand_type": "abdl",
        "ships_intl": False,
        "discreet": True,
        "tags": "diapers,pacifiers,onesies,bottles",
        "notes": "Sydney, age player products",
    },
]

# ── ABDL-aware medical/incontinence stores ───────────────────────────────────
# These are NOT scraped by default — opt-in via DB site management

MEDICAL_AWARE_SITES = [
    {
        "name": "NorthShore Care",
        "url": "https://www.northshorecare.com",
        "region": "US",
        "site_type": "html",
        "brand_type": "both",
        "ships_intl": False,
        "discreet": True,
        "tags": "diapers,pullups",
        "notes": "ABDL aware, MegaMax diapers, Crinklz reseller",
    },
    {
        "name": "XP Medical",
        "url": "https://www.xpmedical.com",
        "region": "US",
        "site_type": "html",
        "brand_type": "both",
        "ships_intl": False,
        "discreet": True,
        "tags": "diapers",
        "notes": "ABDL aware, medical diapers + Crinklz, sample packs",
    },
    {
        "name": "Personally Delivered",
        "url": "https://www.personallydelivered.com",
        "region": "US",
        "site_type": "html",
        "brand_type": "medical",
        "ships_intl": False,
        "discreet": True,
        "tags": "diapers,accessories",
        "notes": "Medical supply, discreet",
    },
    {
        "name": "Healthwick USA",
        "url": "https://www.healthwick.com",
        "region": "US",
        "site_type": "html",
        "brand_type": "both",
        "ships_intl": False,
        "discreet": True,
        "tags": "diapers,accessories",
        "notes": "ABDL aware, Crinklz/InControl/Rearz/Tykables",
    },
    {
        "name": "Healthwick Canada",
        "url": "https://www.healthwick.ca",
        "region": "CA",
        "site_type": "html",
        "brand_type": "both",
        "ships_intl": False,
        "discreet": True,
        "tags": "diapers,accessories",
        "notes": "ABDL aware Canada, same range as US site",
    },
]

# ── Sites known to be defunct / offline ──────────────────────────────────────
OFFLINE_SITES = [
    "ABDL Marketplace UK",
    "ABDLDesigns US",
    "B4NS Canada",
    "Big4Little EU",
    "BKN Nappies UK",
    "Buster Tees UK",
    "Chameleon Clothing UK",
    "France ABDL",
    "Diaperhaus Germany",
    "QTTY Diapers US",
    "Regression Club US",
    "Salous nahtraume Germany",
    "Tykables EU",
    "Littles Laboratory US",
    "Little Den US",
    "Nurture ABDL US",
    "Lifestyles Emporium US",
]


# ── Scraper profile map ───────────────────────────────────────────────────────
# Extra profiles keyed by name, for sites where CSS selectors are known

EXTRA_PROFILES = {
    "ABUniverse USA": {
        "type": "shopify",
        "base": "https://www.abuniverse.com",
        "brand": "ABUniverse",
        "brand_type": "abdl",
    },
    "Tykables": {
        "type": "shopify",
        "base": "https://tykables.com",
        "brand": "Tykables",
        "brand_type": "abdl",
    },
    "Rearz Inc": {
        "type": "shopify",
        "base": "https://rearz.ca",
        "brand": "Rearz",
        "brand_type": "both",
    },
    "LittleForBig": {
        "type": "shopify",
        "base": "https://www.littleforbig.com",
        "brand": "LittleForBig",
        "brand_type": "abdl",
    },
    "Bambino Diapers": {
        "type": "shopify",
        "base": "https://www.bambinodiapers.com",
        "brand": "Bambino",
        "brand_type": "abdl",
    },
    "Lil Kink Boutique": {
        "type": "shopify",
        "base": "https://www.lilkinkboutique.com",
        "brand": "Lil Kink Boutique",
        "brand_type": "abdl",
    },
    "InControl Diapers": {
        "type": "shopify",
        "base": "https://www.incontrolbriefs.com",
        "brand": "InControl",
        "brand_type": "both",
    },
    "Cuddlz": {
        "type": "woocommerce",
        "base": "https://www.cuddlz.com",
        "brand": "Cuddlz",
        "brand_type": "abdl",
    },
    "ABDL Factory": {
        "type": "woocommerce",
        "base": "https://www.abdlfactory.com",
        "brand": "ABDL Factory",
        "brand_type": "abdl",
    },
    "Wilulu": {
        "type": "woocommerce",
        "base": "https://www.wilulu.de",
        "brand": "Wilulu",
        "brand_type": "abdl",
    },
    "Diaper Minister": {
        "type": "woocommerce",
        "base": "https://www.diaper-minister.com",
        "brand": "Diaper Minister",
        "brand_type": "abdl",
    },
    "Nappies R Us": {
        "type": "woocommerce",
        "base": "https://www.nappiesrus.co.uk",
        "brand": "Nappies R Us",
        "brand_type": "both",
    },
    "Cottontailz": {
        "type": "shopify",
        "base": "https://cottontailz.com",
        "brand": "Cottontailz",
        "brand_type": "abdl",
    },
    "Wearing Clouds": {
        "type": "shopify",
        "base": "https://www.wearingclouds.com",
        "brand": "Wearing Clouds",
        "brand_type": "abdl",
    },
    "Pacifier Addict": {
        "type": "shopify",
        "base": "https://www.pacifieraddict.com",
        "brand": "Pacifier Addict",
        "brand_type": "abdl",
    },
    "Snuggly Bears Emporium": {
        "type": "shopify",
        "base": "https://snugglybears.co.uk",
        "brand": "Snuggly Bears",
        "brand_type": "abdl",
    },
    "DDLG Playground": {
        "type": "shopify",
        "base": "https://ddlgplayground.com",
        "brand": "DDLG Playground",
        "brand_type": "abdl",
    },
    "Trest Elite": {
        "type": "shopify",
        "base": "https://trestelite.com",
        "brand": "Trest",
        "brand_type": "abdl",
    },
    "Littles Down Under": {
        "type": "shopify",
        "base": "https://www.littlesdownunder.com",
        "brand": "Littles Down Under",
        "brand_type": "both",
    },
    "Cloudrys": {
        "type": "shopify",
        "base": "https://www.cloudrys.com",
        "brand": "Cloudrys",
        "brand_type": "abdl",
    },
}


def seed_verified_sites(abdl_only=True):
    """
    Seed VERIFIED_ABDL_SITES (and optionally MEDICAL_AWARE_SITES) into the DB.
    Adds brand_type column to scrape_sites if it doesn't already exist.
    Returns count of rows inserted.
    """
    try:
        from database import get_connection
    except ImportError:
        return 0

    sites = list(VERIFIED_ABDL_SITES)
    if not abdl_only:
        sites += MEDICAL_AWARE_SITES

    conn = get_connection()

    # Ensure brand_type column exists (not in original schema — migrate safely)
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(scrape_sites)").fetchall()}
    if "brand_type" not in existing_cols:
        try:
            conn.execute("ALTER TABLE scrape_sites ADD COLUMN brand_type TEXT DEFAULT 'abdl'")
            conn.commit()
        except Exception:
            pass  # Already added by another session

    added = 0
    for s in sites:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO scrape_sites
                    (name, url, site_type, brand_type, scrape_enabled,
                     scrape_interval, notes)
                VALUES (?,?,?,?,1,259200,?)
            """, (
                s["name"], s["url"], s["site_type"],
                s.get("brand_type", "abdl"),
                s.get("notes", ""),
            ))
            if conn.execute("SELECT changes()").fetchone()[0]:
                added += 1
        except Exception as e:
            print(f"[abdl_sites] seed error {s['name']}: {e}")
    conn.commit()
    conn.close()
    return added


def patch_scraper_profiles():
    """Inject EXTRA_PROFILES into scraper.SITE_PROFILES at runtime."""
    try:
        import scraper
        if hasattr(scraper, "SITE_PROFILES"):
            scraper.SITE_PROFILES.update(EXTRA_PROFILES)
            print(f"[abdl_sites] Injected {len(EXTRA_PROFILES)} verified site profiles.")
    except ImportError:
        pass
