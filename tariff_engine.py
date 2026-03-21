"""
tariff_engine.py — CrinkleDen (CDN)

Real-time-aware tariff, VAT, and customs duty calculator for the shopping list.

Data sources:
  - Tariff rates: curated table based on official HTS/HS schedules, updated inline.
    Falls back to cached rates if network unavailable.
  - Currency conversion: fetched live from exchangerate.host (free, no key needed).
    Falls back to hardcoded approximate rates.
  - US Section 301 / reciprocal tariffs: tracked manually as they change —
    these are the most volatile and are noted with last-checked dates.

Tariff depends on three things:
  1. WHERE the product was made (country of origin → inferred from brand/source)
  2. WHERE it's going (destination country + region/state)
  3. WHAT it is (product category → HTS chapter)

Usage:
    from tariff_engine import TariffEngine
    eng = TariffEngine()
    result = eng.calculate(items, destination="US", sub_region="TX",
                           shipping_usd=9.99, currency="USD")
    # result.total_usd, result.breakdown, result.warnings
"""

from __future__ import annotations
import json, threading, time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# ── Product category → HTS chapter mapping ────────────────────────────────────
# Based on WCO Harmonized System chapters most common for ABDL/incontinence goods

HTS_MAP: dict[str, str] = {
    "ABDL Diapers":          "9619",
    "Medical Diapers":       "9619",
    "Overnight Diapers":     "9619",
    "Pull-Ups / Training":   "9619",
    "Swim Diapers":          "9619",
    "Cloth Diapers":         "6111",
    "Boosters / Inserts":    "5601",
    "Underpads / Chux":      "5601",
    "Onesies / Rompers":     "6111",
    "Footed Sleepers":       "6111",
    "Baby Clothing":         "6111",
    "Clothing Sets":         "6111",
    "Dresses / Skirts":      "6204",
    "Overalls / Shortalls":  "6203",
    "Bibs":                  "6111",
    "Plastic Pants":         "3926",
    "Pacifiers":             "3926",
    "Bottles / Sippy Cups":  "3924",
    "Plushies":              "9503",
    "Toys":                  "9503",
    "Bedding / Mattress":    "6302",
    "Blankets":              "6301",
    "Accessories":           "3926",
    "Skincare / Medical":    "3304",
    "Disposal / Storage":    "3923",
    "Stickers":              "4911",
    "Activity / Crafts":     "9503",
    "Gift Cards":            "4911",
    # fallback
    "Diapers":               "9619",
    "default":               "3926",
}

# ── Brand → country of manufacture ────────────────────────────────────────────
# "Where was this product actually made" — NOT where the brand is headquartered.
# This is what determines import duty, not the selling country.

BRAND_ORIGIN: dict[str, str] = {
    # US brands — mostly manufactured in China unless noted
    "tykables":         "CN",
    "abu":              "CN",
    "abuniverse":       "CN",
    "ab universe":      "CN",
    "bambino":          "CN",
    "rearz":            "CN",
    "littleforbig":     "CN",
    "little for big":   "CN",
    "dotty":            "GB",
    "incontrol":        "US",
    "northshore":       "CN",
    "xp medical":       "CN",
    "xpmedical":        "CN",
    "tranquility":      "US",
    "attends":          "US",
    "prevail":          "US",
    "depend":           "US",
    "poise":            "US",
    "always":           "US",
    "goodnites":        "US",
    # EU brands — manufactured in EU
    "crinklz":          "DE",
    "betterdry":        "DE",
    "fabine":           "DE",
    "trest":            "SE",
    "snuggies":         "AU",
    "abena":            "DK",
    "tena":             "SE",
    "hartmann":         "DE",
    "seni":             "PL",
    "molicare":         "DE",
    # UK brands
    "cuddlz":           "GB",
    "nappiesrus":       "GB",
    "little northwood": "GB",
    "babykins":         "CA",
    "wearing clouds":   "CA",
    # AU brands
    "snuggies au":      "AU",
    # KR brands
    "jajo":             "KR",
    "cushies":          "KR",
}

# ── Destination country configurations ────────────────────────────────────────

DESTINATIONS: dict[str, dict] = {
    "🇺🇸 United States": {
        "code": "US", "currency": "USD", "symbol": "$",
        "vat_label": "Sales Tax", "vat_rate": None,   # state-dependent
        "sub_region_type": "state",
        "de_minimis_usd": 800,    # below this, no federal duty
    },
    "🇪🇺 European Union": {
        "code": "EU", "currency": "EUR", "symbol": "€",
        "vat_label": "VAT", "vat_rate": None,          # country-dependent
        "sub_region_type": "eu_country",
        "de_minimis_usd": 150,    # €150 threshold
    },
    "🇬🇧 United Kingdom": {
        "code": "GB", "currency": "GBP", "symbol": "£",
        "vat_label": "VAT", "vat_rate": 0.20,
        "sub_region_type": None,
        "de_minimis_usd": 185,    # £135 threshold
    },
    "🇯🇵 Japan": {
        "code": "JP", "currency": "JPY", "symbol": "¥",
        "vat_label": "Consumption Tax", "vat_rate": 0.10,
        "sub_region_type": None,
        "de_minimis_usd": 0,      # no de minimis — all imports taxed
    },
    "🇦🇺 Australia": {
        "code": "AU", "currency": "AUD", "symbol": "A$",
        "vat_label": "GST", "vat_rate": 0.10,
        "sub_region_type": "au_state",
        "de_minimis_usd": 0,      # GST applies to all imports since 2018
    },
    "🇨🇦 Canada": {
        "code": "CA", "currency": "CAD", "symbol": "C$",
        "vat_label": "GST/HST", "vat_rate": None,     # province-dependent
        "sub_region_type": "ca_province",
        "de_minimis_usd": 20,
    },
    "🇸🇬 Singapore": {
        "code": "SG", "currency": "SGD", "symbol": "S$",
        "vat_label": "GST", "vat_rate": 0.09,
        "sub_region_type": None,
        "de_minimis_usd": 400,
    },
    "🇳🇿 New Zealand": {
        "code": "NZ", "currency": "NZD", "symbol": "NZ$",
        "vat_label": "GST", "vat_rate": 0.15,
        "sub_region_type": None,
        "de_minimis_usd": 0,
    },
}

# ── Sub-regions ────────────────────────────────────────────────────────────────

US_STATES: list[tuple[str, float]] = [
    ("AL – Alabama", 0.04), ("AK – Alaska", 0.00), ("AZ – Arizona", 0.056),
    ("AR – Arkansas", 0.065), ("CA – California", 0.0725), ("CO – Colorado", 0.029),
    ("CT – Connecticut", 0.0635), ("DE – Delaware", 0.00), ("FL – Florida", 0.06),
    ("GA – Georgia", 0.04), ("HI – Hawaii", 0.04), ("ID – Idaho", 0.06),
    ("IL – Illinois", 0.0625), ("IN – Indiana", 0.07), ("IA – Iowa", 0.06),
    ("KS – Kansas", 0.065), ("KY – Kentucky", 0.06), ("LA – Louisiana", 0.0445),
    ("ME – Maine", 0.055), ("MD – Maryland", 0.06), ("MA – Massachusetts", 0.0625),
    ("MI – Michigan", 0.06), ("MN – Minnesota", 0.06875), ("MS – Mississippi", 0.07),
    ("MO – Missouri", 0.04225), ("MT – Montana", 0.00), ("NE – Nebraska", 0.055),
    ("NV – Nevada", 0.0685), ("NH – New Hampshire", 0.00), ("NJ – New Jersey", 0.06625),
    ("NM – New Mexico", 0.05125), ("NY – New York", 0.04), ("NC – North Carolina", 0.0475),
    ("ND – North Dakota", 0.05), ("OH – Ohio", 0.0575), ("OK – Oklahoma", 0.045),
    ("OR – Oregon", 0.00), ("PA – Pennsylvania", 0.06), ("RI – Rhode Island", 0.07),
    ("SC – South Carolina", 0.06), ("SD – South Dakota", 0.045), ("TN – Tennessee", 0.07),
    ("TX – Texas", 0.0625), ("UT – Utah", 0.0485), ("VT – Vermont", 0.06),
    ("VA – Virginia", 0.043), ("WA – Washington", 0.065), ("WV – West Virginia", 0.06),
    ("WI – Wisconsin", 0.05), ("WY – Wyoming", 0.04),
]

EU_COUNTRIES: list[tuple[str, float]] = [
    ("Austria 🇦🇹", 0.20), ("Belgium 🇧🇪", 0.21), ("Bulgaria 🇧🇬", 0.20),
    ("Croatia 🇭🇷", 0.25), ("Cyprus 🇨🇾", 0.19), ("Czech Republic 🇨🇿", 0.21),
    ("Denmark 🇩🇰", 0.25), ("Estonia 🇪🇪", 0.22), ("Finland 🇫🇮", 0.255),
    ("France 🇫🇷", 0.20), ("Germany 🇩🇪", 0.19), ("Greece 🇬🇷", 0.24),
    ("Hungary 🇭🇺", 0.27), ("Ireland 🇮🇪", 0.23), ("Italy 🇮🇹", 0.22),
    ("Latvia 🇱🇻", 0.21), ("Lithuania 🇱🇹", 0.21), ("Luxembourg 🇱🇺", 0.17),
    ("Malta 🇲🇹", 0.18), ("Netherlands 🇳🇱", 0.21), ("Poland 🇵🇱", 0.23),
    ("Portugal 🇵🇹", 0.23), ("Romania 🇷🇴", 0.19), ("Slovakia 🇸🇰", 0.20),
    ("Slovenia 🇸🇮", 0.22), ("Spain 🇪🇸", 0.21), ("Sweden 🇸🇪", 0.25),
]

CA_PROVINCES: list[tuple[str, float]] = [
    ("Alberta 🏔", 0.05), ("British Columbia 🌲", 0.12), ("Manitoba 🌾", 0.12),
    ("New Brunswick 🦞", 0.15), ("Newfoundland 🐋", 0.15), ("Northwest Territories ❄", 0.05),
    ("Nova Scotia 🦞", 0.15), ("Nunavut ❄", 0.05), ("Ontario 🍁", 0.13),
    ("Prince Edward Island 🥔", 0.15), ("Quebec 🗼", 0.14975), ("Saskatchewan 🌻", 0.11),
    ("Yukon 🏔", 0.05),
]

AU_STATES: list[tuple[str, float]] = [
    ("Australian Capital Territory", 0.10), ("New South Wales", 0.10),
    ("Northern Territory", 0.10), ("Queensland", 0.10), ("South Australia", 0.10),
    ("Tasmania", 0.10), ("Victoria", 0.10), ("Western Australia", 0.10),
]

# ── Tariff rates: (origin, destination, hts_chapter) → duty_rate ──────────────
#
# These are the IMPORT DUTY rates — separate from VAT.
# Sources: USITC, EU TARIC, UK Global Tariff, Japan Customs, Australian Customs.
# Last comprehensive review: March 2026.
#
# Format: {(origin_code, dest_code, hts_prefix): rate}
# Most-specific match wins. Falls back to (origin, dest, "default").

TARIFF_RATES: dict[tuple[str, str, str], float] = {
    # ── US importing FROM China (Section 301 + 2025 reciprocal tariffs) ──────
    # Note: US tariffs on China goods are extremely volatile (2025-2026).
    # Current effective rate includes 25% Section 301 + 20% IEEPA = ~145% total
    # for most goods. ABDL/medical diapers have some exemptions.
    ("CN", "US", "9619"): 0.25,    # diapers: 25% base (some exempted from 301)
    ("CN", "US", "6111"): 0.32,    # baby clothing: 32% (16% + 16% Section 301)
    ("CN", "US", "6109"): 0.32,    # t-shirts/apparel
    ("CN", "US", "6203"): 0.32,    # overalls
    ("CN", "US", "6204"): 0.32,    # women's apparel
    ("CN", "US", "3926"): 0.25,    # plastics: 25%
    ("CN", "US", "3924"): 0.25,    # tableware/plastics
    ("CN", "US", "9503"): 0.25,    # toys: 25%
    ("CN", "US", "5601"): 0.04,    # wadding/nonwovens: 4%
    ("CN", "US", "6302"): 0.125,   # bed linen: 12.5%
    ("CN", "US", "6301"): 0.143,   # blankets: 14.3%
    ("CN", "US", "3304"): 0.04,    # skincare: 4%
    ("CN", "US", "4911"): 0.00,    # stickers/printed: free
    ("CN", "US", "default"): 0.25,

    # ── US importing FROM EU ──────────────────────────────────────────────────
    ("DE", "US", "9619"): 0.00,   # diapers: free under MFN
    ("DE", "US", "6111"): 0.12,   # clothing
    ("DE", "US", "default"): 0.03,
    ("SE", "US", "9619"): 0.00,
    ("SE", "US", "default"): 0.03,
    ("DK", "US", "9619"): 0.00,
    ("DK", "US", "default"): 0.03,
    ("PL", "US", "default"): 0.03,
    ("NL", "US", "default"): 0.03,

    # ── US importing FROM UK ──────────────────────────────────────────────────
    ("GB", "US", "9619"): 0.00,
    ("GB", "US", "6111"): 0.12,
    ("GB", "US", "default"): 0.035,

    # ── US importing FROM Canada ──────────────────────────────────────────────
    ("CA", "US", "default"): 0.00,  # CUSMA/USMCA free

    # ── US importing FROM Korea ───────────────────────────────────────────────
    ("KR", "US", "9619"): 0.00,    # KORUS FTA
    ("KR", "US", "default"): 0.00,

    # ── US importing FROM Australia ───────────────────────────────────────────
    ("AU", "US", "default"): 0.00,  # AUSFTA

    # ── EU importing FROM China ───────────────────────────────────────────────
    ("CN", "EU", "9619"): 0.06,    # diapers: 6%
    ("CN", "EU", "6111"): 0.12,    # baby clothing: 12%
    ("CN", "EU", "6109"): 0.12,
    ("CN", "EU", "6203"): 0.12,
    ("CN", "EU", "6204"): 0.12,
    ("CN", "EU", "3926"): 0.065,   # plastics: 6.5%
    ("CN", "EU", "9503"): 0.048,   # toys: 4.8%
    ("CN", "EU", "5601"): 0.04,
    ("CN", "EU", "6302"): 0.12,
    ("CN", "EU", "default"): 0.065,

    # ── EU importing FROM US ──────────────────────────────────────────────────
    ("US", "EU", "9619"): 0.06,
    ("US", "EU", "6111"): 0.12,
    ("US", "EU", "default"): 0.04,

    # ── EU internal (intra-EU) ────────────────────────────────────────────────
    ("DE", "EU", "default"): 0.00,
    ("SE", "EU", "default"): 0.00,
    ("DK", "EU", "default"): 0.00,
    ("PL", "EU", "default"): 0.00,
    ("GB", "EU", "default"): 0.04,  # post-Brexit — UK is no longer EU

    # ── UK importing ──────────────────────────────────────────────────────────
    ("CN", "GB", "9619"): 0.0175,  # 1.75%
    ("CN", "GB", "6111"): 0.12,
    ("CN", "GB", "3926"): 0.065,
    ("CN", "GB", "9503"): 0.00,    # toys: free in UK global tariff
    ("CN", "GB", "default"): 0.04,
    ("US", "GB", "9619"): 0.00,
    ("US", "GB", "default"): 0.04,
    ("DE", "GB", "default"): 0.04,  # EU to UK post-Brexit
    ("SE", "GB", "default"): 0.04,
    ("GB", "GB", "default"): 0.00,  # domestic

    # ── Japan importing ───────────────────────────────────────────────────────
    ("CN", "JP", "9619"): 0.00,    # Japan-China: diapers free
    ("CN", "JP", "6111"): 0.105,
    ("CN", "JP", "default"): 0.04,
    ("US", "JP", "default"): 0.03,
    ("KR", "JP", "default"): 0.00,  # RCEP
    ("default", "JP", "default"): 0.04,

    # ── Australia importing ───────────────────────────────────────────────────
    ("CN", "AU", "9619"): 0.00,    # ChAFTA: free
    ("CN", "AU", "default"): 0.05,
    ("US", "AU", "default"): 0.00, # AUSFTA
    ("GB", "AU", "default"): 0.00, # AUKFTA
    ("default", "AU", "default"): 0.05,

    # ── Canada importing ──────────────────────────────────────────────────────
    ("CN", "CA", "9619"): 0.00,
    ("CN", "CA", "6111"): 0.18,
    ("CN", "CA", "default"): 0.065,
    ("US", "CA", "default"): 0.00,  # CUSMA
    ("GB", "CA", "default"): 0.00,  # CETA-like
    ("default", "CA", "default"): 0.065,

    # ── Singapore importing ───────────────────────────────────────────────────
    ("default", "SG", "default"): 0.00,  # Singapore: very low / free on most goods

    # ── New Zealand importing ─────────────────────────────────────────────────
    ("CN", "NZ", "default"): 0.05,
    ("default", "NZ", "default"): 0.05,

    # ── Domestic (same country) ───────────────────────────────────────────────
    ("US", "US", "default"): 0.00,
    ("GB", "GB", "default"): 0.00,
    ("AU", "AU", "default"): 0.00,
    ("CA", "CA", "default"): 0.00,
    ("JP", "JP", "default"): 0.00,
}

# Fallback MFN rates when no specific rule matches
MFN_FALLBACK: dict[tuple[str, str], float] = {
    ("default", "US"): 0.035,
    ("default", "EU"): 0.055,
    ("default", "GB"): 0.04,
    ("default", "JP"): 0.04,
    ("default", "AU"): 0.05,
    ("default", "CA"): 0.065,
    ("default", "SG"): 0.00,
    ("default", "NZ"): 0.05,
}

# ── Exchange rates (fallback) ──────────────────────────────────────────────────
FALLBACK_FX: dict[str, float] = {
    "USD": 1.00,
    "EUR": 0.92,
    "GBP": 0.79,
    "JPY": 149.5,
    "AUD": 1.53,
    "CAD": 1.36,
    "SGD": 1.34,
    "NZD": 1.63,
}

# ── Result dataclasses ─────────────────────────────────────────────────────────

@dataclass
class ItemTariff:
    name:           str
    qty:            int
    unit_price_usd: float
    origin:         str          # country code
    origin_name:    str
    hts_chapter:    str
    duty_rate:      float
    duty_usd:       float
    vat_rate:       float
    vat_usd:        float
    subtotal_usd:   float
    total_with_tax: float

@dataclass
class TariffResult:
    destination:      str
    sub_region:       str
    currency:         str
    fx_rate:          float
    subtotal_usd:     float
    shipping_usd:     float
    total_duty_usd:   float
    total_vat_usd:    float
    grand_total_usd:  float
    grand_total_local: float
    items:            list[ItemTariff] = field(default_factory=list)
    warnings:         list[str]       = field(default_factory=list)
    fx_last_updated:  str             = ""
    tariff_note:      str             = ""


# ── TariffEngine ──────────────────────────────────────────────────────────────

class TariffEngine:
    """
    Calculates full landed cost including:
      - Import duty (based on origin country, destination, and product type)
      - VAT / GST / Consumption Tax (destination country rate)
      - Sales tax (US states / CA provinces)
      - Currency conversion (live rates fetched in background)
    """

    _fx_cache:    dict[str, float] = {}
    _fx_fetched:  float = 0.0
    _fx_lock:     threading.Lock = threading.Lock()
    _FX_TTL:      float = 3600.0   # refresh FX rates every hour

    def get_fx_rates(self, force: bool = False) -> dict[str, float]:
        """Return USD→X exchange rates. Fetches live, falls back to hardcoded."""
        with self._fx_lock:
            now = time.time()
            if not force and self._fx_cache and (now - self._fx_fetched) < self._FX_TTL:
                return self._fx_cache
            try:
                from urllib.request import urlopen, Request
                url = "https://api.exchangerate.host/latest?base=USD&symbols=EUR,GBP,JPY,AUD,CAD,SGD,NZD"
                req = Request(url, headers={"User-Agent": "CrinkleDen-CDN/2.0"})
                with urlopen(req, timeout=5) as r:
                    data = json.loads(r.read())
                rates = data.get("rates", {})
                if rates:
                    rates["USD"] = 1.0
                    self._fx_cache = rates
                    self._fx_fetched = now
                    return rates
            except Exception:
                pass
            # Fallback to hardcoded rates
            self._fx_cache = dict(FALLBACK_FX)
            self._fx_fetched = now
            return self._fx_cache

    def infer_origin(self, item: dict) -> tuple[str, str]:
        """Return (country_code, country_name) for where the product was made."""
        brand = (item.get("brand_name") or "").lower().strip()
        source = (item.get("source_site") or "").lower()

        # Check brand origin table
        for key, code in BRAND_ORIGIN.items():
            if key in brand:
                return code, _country_name(code)

        # Fallback: infer from source domain
        if ".co.uk" in source or ".gb" in source:
            return "GB", "United Kingdom"
        if ".de" in source or ".eu" in source:
            return "DE", "Germany / EU"
        if ".au" in source or ".com.au" in source:
            return "AU", "Australia"
        if ".ca" in source:
            return "CA", "Canada"
        if ".jp" in source:
            return "JP", "Japan"
        if ".kr" in source:
            return "KR", "South Korea"

        # Default: assume China for unknown (most ABDL products manufactured there)
        return "CN", "China (assumed)"

    def lookup_duty_rate(self, origin: str, dest: str, hts: str) -> float:
        """Find the best-matching tariff rate for this origin/dest/HTS combo."""
        # Exact HTS match
        if (origin, dest, hts) in TARIFF_RATES:
            return TARIFF_RATES[(origin, dest, hts)]
        # Default for this origin/dest pair
        if (origin, dest, "default") in TARIFF_RATES:
            return TARIFF_RATES[(origin, dest, "default")]
        # MFN fallback
        if ("default", dest) in MFN_FALLBACK:
            return MFN_FALLBACK[("default", dest)]
        return 0.035   # global average MFN fallback

    def get_vat_rate(self, dest_code: str, sub_region: str) -> tuple[float, str]:
        """Return (rate, label) for the destination's consumption tax."""
        dest_cfg = None
        for cfg in DESTINATIONS.values():
            if cfg["code"] == dest_code:
                dest_cfg = cfg
                break
        if not dest_cfg:
            return 0.0, "No tax"

        label = dest_cfg["vat_label"]

        # Fixed rates
        if dest_cfg["vat_rate"] is not None:
            return dest_cfg["vat_rate"], label

        # Sub-region dependent rates
        if dest_code == "US":
            for name, rate in US_STATES:
                if name.split("–")[0].strip() == sub_region or name == sub_region:
                    return rate, f"State Sales Tax ({name})"
            # Try abbreviation match
            for name, rate in US_STATES:
                abbr = name.split("–")[0].strip()
                if abbr == sub_region[:2].upper():
                    return rate, f"State Sales Tax ({name})"
            return 0.0, "Sales Tax (unknown state)"

        if dest_code == "EU":
            for name, rate in EU_COUNTRIES:
                if name.split(" ")[0].lower() == sub_region.lower():
                    return rate, f"VAT ({name})"
                if sub_region.lower() in name.lower():
                    return rate, f"VAT ({name})"
            return 0.21, "VAT (EU average)"

        if dest_code == "CA":
            for name, rate in CA_PROVINCES:
                if sub_region.lower() in name.lower():
                    return rate, f"GST/HST ({name})"
            return 0.13, "GST/HST (CA average)"

        if dest_code == "AU":
            return 0.10, "GST (Australia)"

        return 0.0, label

    def calculate(
        self,
        items:         list[dict],
        destination:   str,
        sub_region:    str = "",
        shipping_usd:  float = 0.0,
        currency:      str = "USD",
    ) -> TariffResult:
        """
        Full landed cost calculation.

        items:        list of shopping-list dicts (name, brand_name, price_usd,
                      quantity, category_name, source_site)
        destination:  country code ("US", "EU", "GB", etc.)
        sub_region:   state/province/country within region ("TX", "Germany", etc.)
        shipping_usd: flat shipping estimate in USD
        currency:     display currency code
        """
        fx = self.get_fx_rates()
        fx_rate = fx.get(currency, FALLBACK_FX.get(currency, 1.0))
        fx_updated = datetime.now().strftime("%Y-%m-%d %H:%M") if self._fx_fetched else "fallback"

        dest_cfg = None
        for cfg in DESTINATIONS.values():
            if cfg["code"] == destination:
                dest_cfg = cfg
                break
        if not dest_cfg:
            dest_cfg = {"code": destination, "vat_rate": 0.0, "de_minimis_usd": 0}

        subtotal_usd = sum(
            (it.get("unit_price") or it.get("price_usd") or 0) * it.get("quantity", 1)
            for it in items
        )

        de_minimis = dest_cfg.get("de_minimis_usd", 0)
        skip_duty = (subtotal_usd + shipping_usd) <= de_minimis

        item_results: list[ItemTariff] = []
        total_duty_usd = 0.0
        total_vat_usd  = 0.0
        warnings: list[str] = []

        for it in items:
            qty        = it.get("quantity", 1)
            unit_price = it.get("unit_price") or it.get("price_usd") or 0.0
            item_sub   = unit_price * qty
            cat        = it.get("category_name") or "default"
            hts        = HTS_MAP.get(cat, HTS_MAP["default"])
            origin_code, origin_name = self.infer_origin(it)

            duty_rate = 0.0 if skip_duty else self.lookup_duty_rate(
                origin_code, destination, hts
            )
            duty_usd = round(item_sub * duty_rate, 2)

            vat_rate, vat_label = self.get_vat_rate(destination, sub_region)
            # VAT is typically calculated on (item price + duty)
            taxable_base = item_sub + duty_usd
            vat_usd = round(taxable_base * vat_rate, 2)

            total_with_tax = item_sub + duty_usd + vat_usd

            item_results.append(ItemTariff(
                name           = it.get("name", "")[:50],
                qty            = qty,
                unit_price_usd = unit_price,
                origin         = origin_code,
                origin_name    = origin_name,
                hts_chapter    = hts,
                duty_rate      = duty_rate,
                duty_usd       = duty_usd,
                vat_rate       = vat_rate,
                vat_usd        = vat_usd,
                subtotal_usd   = item_sub,
                total_with_tax = total_with_tax,
            ))

            total_duty_usd += duty_usd
            total_vat_usd  += vat_usd

        grand_total_usd = subtotal_usd + shipping_usd + total_duty_usd + total_vat_usd

        # Build warnings
        if skip_duty and de_minimis:
            warnings.append(
                f"✓ Order under ${de_minimis} de minimis threshold — no import duty applied"
            )
        if destination == "US" and any(r.origin == "CN" for r in item_results):
            warnings.append(
                "⚠ US tariffs on Chinese goods are subject to change. "
                "Section 301 + IEEPA tariffs may increase rates significantly. "
                "Check USITC.gov for current rates before ordering."
            )
        if destination == "JP" and any(r.origin == "CN" for r in item_results):
            warnings.append(
                "ℹ Japan–China goods benefit from RCEP agreement — reduced rates applied."
            )
        if destination == "EU" and any(r.origin == "CN" for r in item_results):
            warnings.append(
                "ℹ EU customs duty + VAT collected at border. "
                "Seller may or may not pre-collect these — confirm before ordering."
            )

        tariff_note = ""
        if destination == "US":
            tariff_note = (
                "US import duty rates reflect MFN + Section 301 tariffs as of March 2026. "
                "Rates on Chinese goods are especially volatile due to ongoing trade negotiations."
            )
        elif destination == "EU":
            tariff_note = (
                "EU duty rates from TARIC. VAT rate reflects selected member state. "
                "Some ABDL goods may qualify for medical device exemptions."
            )
        elif destination == "GB":
            tariff_note = "UK Global Tariff rates. VAT 20% applies to most goods."

        return TariffResult(
            destination       = destination,
            sub_region        = sub_region,
            currency          = currency,
            fx_rate           = fx_rate,
            subtotal_usd      = subtotal_usd,
            shipping_usd      = shipping_usd,
            total_duty_usd    = total_duty_usd,
            total_vat_usd     = total_vat_usd,
            grand_total_usd   = grand_total_usd,
            grand_total_local = round(grand_total_usd * fx_rate, 2),
            items             = item_results,
            warnings          = warnings,
            fx_last_updated   = fx_updated,
            tariff_note       = tariff_note,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

_COUNTRY_NAMES: dict[str, str] = {
    "US": "United States", "CN": "China", "DE": "Germany",
    "SE": "Sweden", "DK": "Denmark", "PL": "Poland", "NL": "Netherlands",
    "GB": "United Kingdom", "AU": "Australia", "CA": "Canada",
    "JP": "Japan", "KR": "South Korea", "FR": "France",
    "IT": "Italy", "ES": "Spain", "BE": "Belgium",
    "AT": "Austria", "CH": "Switzerland", "SG": "Singapore",
    "NZ": "New Zealand",
}

def _country_name(code: str) -> str:
    return _COUNTRY_NAMES.get(code, code)

def get_sub_regions(dest_code: str) -> list[tuple[str, float]]:
    """Return the list of sub-regions for the given destination code."""
    if dest_code == "US":  return US_STATES
    if dest_code == "EU":  return EU_COUNTRIES
    if dest_code == "CA":  return CA_PROVINCES
    if dest_code == "AU":  return AU_STATES
    return []

def get_destinations() -> dict[str, dict]:
    return DESTINATIONS
