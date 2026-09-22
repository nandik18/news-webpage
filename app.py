from flask import Flask, jsonify, render_template
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import feedparser
import hashlib
import html
import re
import requests
import time
from bs4 import BeautifulSoup
import pytz

IST = pytz.timezone("Asia/Kolkata")


from config import (
    ALL_FEEDS, REFRESH_SECONDS, MAX_ARTICLES_PER_SOURCE,
    MAX_ARTICLE_AGE_HOURS, GDELT_ENABLED
)

app = Flask(__name__)
NEWS = {}
SOURCE_STATUS = {}
LAST_UPDATED = None
REFRESH_IN_PROGRESS = False

# Server-side refresh cache.
# The browser already requests /api/news every REFRESH_SECONDS.
# We therefore do not need a background scheduler.
SERVER_CACHE_TTL = max(30, min(int(REFRESH_SECONDS), 60))

COMMODITIES = {
    "GOLD": ["gold", "bullion", "xau"],
    "SILVER": ["silver", "xag"],
    "PALM OIL": ["palm oil"],
    "CRUDE OIL": ["crude oil", "crude", "brent", "wti", "oil prices", "oil price", "opec"],
    "NATURAL GAS": ["natural gas", "natgas", "lng"],
    "COPPER": ["copper"],
    "ALUMINIUM": ["aluminium", "aluminum"],
    "ZINC": ["zinc"],
    "LEAD": ["lead"],
    "NICKEL": ["nickel"],
    "COTTON": ["cotton"],
    "SUGAR": ["sugar"],
    "COFFEE": ["coffee"],
    "COCOA": ["cocoa"],
    "WHEAT": ["wheat"],
    "SOYBEAN": ["soybean", "soybeans"],
    "MENTHA OIL": ["mentha"],
}
CRYPTO_ASSETS = {
    "BITCOIN": ["bitcoin", "btc"],
    "ETHEREUM": ["ethereum", "eth"],
    "CRYPTO": [
        "cryptocurrency",
        "crypto market",
        "crypto markets",
        "digital asset",
        "digital assets",
        "altcoin",
        "altcoins",
    ],
}

# Directional headline language only. This is not a trading signal.
POSITIVE = [
    "rises", "rise", "rising", "surges", "surge", "gains", "gain", "jumps",
    "jump", "higher", "bullish", "boost", "boosts", "supports", "support",
    "strong demand", "demand rises", "shortage", "supply cut", "production cut",
    "output cut", "disruption", "disruptions", "weakens", "weaker dollar",
    "stimulus", "rebound", "recovery", "tight supply", "inventory draw",
    "inventories fall"
]
NEGATIVE = [
    "falls", "fall", "falling", "drops", "drop", "declines", "decline",
    "lower", "bearish", "pressure", "pressures", "oversupply", "surplus",
    "inventory build", "inventories rise", "stockpiles rise", "stronger dollar",
    "dollar strengthens", "recession", "slowdown", "weak demand", "demand falls",
    "eases", "ease", "production rises", "output rises"
]

def clean(value):
    value = html.unescape(value or "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()

def parse_datetime(entry):
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except Exception:
                pass

    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass
    return None

def detect_commodity(title, summary=""):
    """
    Detect the actual asset discussed by the article.

    The title gets priority over the summary. Generic feed/source names
    are deliberately not used to guess an asset, and unknown articles are
    marked UNCLASSIFIED rather than being assigned to Crude Oil.
    """
    title_text = str(title or "").lower()
    summary_text = str(summary or "").lower()

    # Crypto first so a Bitcoin article mentioning oil does not become Crude Oil.
    for asset, words in CRYPTO_ASSETS.items():
        for word in words:
            if re.search(r"\b" + re.escape(word) + r"\b", title_text):
                return asset

    # Then detect commodities from the headline.
    for name, words in COMMODITIES.items():
        for word in words:
            if re.search(r"\b" + re.escape(word) + r"\b", title_text):
                return name

    # If the headline is not enough, use the article summary.
    for asset, words in CRYPTO_ASSETS.items():
        for word in words:
            if re.search(r"\b" + re.escape(word) + r"\b", summary_text):
                return asset

    for name, words in COMMODITIES.items():
        for word in words:
            if re.search(r"\b" + re.escape(word) + r"\b", summary_text):
                return name

    return "UNCLASSIFIED"

def classify_market_impact(title, summary, commodity):
    """
    Multi-asset, event-aware classification.

    The goal is not ordinary language sentiment. The same headline can be
    negative for a commodity and positive for downstream users/equities.
    """
    text = f"{title} {summary}".lower()
    effects = []

    def add(asset, impact, reason):
        effects.append({
            "asset": asset,
            "impact": impact,
            "reason": reason
        })

    # --- Direct commodity price moves ---
    commodity_price_words = {
        "down": ["falls", "fall", "falling", "slides", "slide", "drops", "drop",
                 "declines", "decline", "slips", "eases", "retreats", "lower",
                 "loses", "tumbles", "dips", "dip", "dipped", "slid", "sliding"],
        "up": ["rises", "rise", "rising", "surges", "surge", "jumps", "jump",
               "gains", "gain", "climbs", "higher", "advances", "rallies"]
    }

    has_price_down = any(w in text for w in commodity_price_words["down"])
    has_price_up = any(w in text for w in commodity_price_words["up"])

    commodity_terms = {
        "GOLD": ["gold", "bullion"],
        "SILVER": ["silver"],
        "CRUDE OIL": ["crude oil", "crude", "brent", "wti", "opec"],
        "NATURAL GAS": ["natural gas", "lng"],
        "COPPER": ["copper"],
        "ALUMINIUM": ["aluminium", "aluminum"],
        "ZINC": ["zinc"],
        "LEAD": ["lead"],
        "NICKEL": ["nickel"],
        "COTTON": ["cotton"],
        "SUGAR": ["sugar"],
        "COFFEE": ["coffee"],
        "COCOA": ["cocoa"],
        "WHEAT": ["wheat"],
        "SOYBEAN": ["soybean", "soybeans"],
        "PALM OIL": ["palm oil"],
        "MENTHA OIL": ["mentha"],
    }

    relevant = commodity_terms.get(commodity, [])
    commodity_mentioned = any(
        re.search(r"\b" + re.escape(x) + r"\b", text)
        for x in relevant
    )

    if commodity_mentioned and has_price_down:
        add(commodity, "NEGATIVE",
            f"The article reports lower {commodity.lower()} prices, which is directly negative for the commodity price.")
    elif commodity_mentioned and has_price_up:
        add(commodity, "POSITIVE",
            f"The article reports higher {commodity.lower()} prices, which is directly positive for the commodity price.")

    # --- Supply / demand events ---
    supply_disruption = any(x in text for x in [
        "supply disruption", "supply disruptions", "production cut",
        "output cut", "supply cut", "pipeline outage", "pipeline disruption",
        "shipment disruption", "shipments disrupted", "export ban",
        "exports halted", "production outage"
    ])
    supply_recovery = any(x in text for x in [
        "supply recovers", "shipments recover", "shipments recovered",
        "exports recover", "exports recovered", "production resumes",
        "flows resume", "pipeline flows resume", "restarts production"
    ])
    demand_up = any(x in text for x in [
        "demand rises", "demand increased", "strong demand", "demand grows",
        "demand growth", "consumption rises", "buying increases"
    ])
    demand_down = any(x in text for x in [
        "demand falls", "demand declines", "weak demand", "demand slows",
        "consumption falls", "demand concerns"
    ])

    if supply_disruption:
        add(commodity, "POSITIVE",
            f"Supply disruption can reduce available supply and put upward pressure on {commodity.lower()} prices.")
    if supply_recovery:
        add(commodity, "NEGATIVE",
            f"Recovering supply can reduce scarcity and put downward pressure on {commodity.lower()} prices.")
    if demand_up:
        add(commodity, "POSITIVE",
            f"Stronger demand can support prices and producer revenues for {commodity.lower()}.")
    if demand_down:
        add(commodity, "NEGATIVE",
            f"Weaker demand can reduce consumption and put pressure on {commodity.lower()} prices.")

    # --- Inventories ---
    if any(x in text for x in ["inventory build", "inventories rise", "stockpiles rise",
                               "inventories increased", "inventory increased"]):
        add(commodity, "NEGATIVE",
            f"Higher inventories generally indicate more readily available supply, which can pressure {commodity.lower()} prices.")
    if any(x in text for x in ["inventory draw", "inventories fall", "stockpiles fall",
                                "inventories declined", "inventory declined"]):
        add(commodity, "POSITIVE",
            f"Falling inventories can indicate tighter supply and support {commodity.lower()} prices.")

    # --- USD / rates ---
    if commodity in {"GOLD", "SILVER", "CRUDE OIL", "COPPER"}:
        if any(x in text for x in ["dollar weakens", "dollar falls", "weaker dollar", "dollar slips"]):
            add(commodity, "POSITIVE",
                "A weaker U.S. dollar can support dollar-denominated commodities by improving affordability for non-dollar buyers.")
        if any(x in text for x in ["dollar strengthens", "dollar rises", "stronger dollar", "firmer dollar"]):
            add(commodity, "NEGATIVE",
                "A stronger U.S. dollar can pressure dollar-denominated commodity prices.")

    if any(x in text for x in ["interest rates rise", "rate hike", "higher rates", "higher interest rates"]):
        if commodity in {"GOLD", "SILVER"}:
            add(commodity, "NEGATIVE",
                "Higher rates can raise the opportunity cost of holding non-yielding precious metals.")
    if any(x in text for x in ["rate cut", "rate cuts", "lower rates", "interest rates fall"]):
        if commodity in {"GOLD", "SILVER"}:
            add(commodity, "POSITIVE",
                "Lower rates can reduce the opportunity cost of holding non-yielding precious metals.")

    # --- Oil-specific downstream effects ---
    if commodity == "CRUDE OIL":
        if has_price_down or supply_recovery:
            add("AIRLINES / TRANSPORT", "POSITIVE",
                "Lower fuel costs can reduce operating expenses for fuel-intensive transport businesses.")
            add("CONSUMERS / INFLATION", "POSITIVE",
                "Lower energy costs can reduce fuel and inflation pressure, all else equal.")
            add("ENERGY PRODUCERS", "NEGATIVE",
                "Lower oil prices can reduce realized prices and margins for upstream energy producers.")
            add("BROAD EQUITIES", "POSITIVE",
                "Lower oil prices can ease inflation and input-cost pressure, which can support broader equities when demand is not simultaneously weakening.")
        if has_price_up or supply_disruption:
            add("AIRLINES / TRANSPORT", "NEGATIVE",
                "Higher fuel costs can increase operating expenses for fuel-intensive transport businesses.")
            add("ENERGY PRODUCERS", "POSITIVE",
                "Higher oil prices can increase realized prices and revenue for upstream producers.")
            add("CONSUMERS / INFLATION", "NEGATIVE",
                "Higher energy costs can increase fuel and inflation pressure.")
            add("BROAD EQUITIES", "NEGATIVE",
                "A sustained oil-price rise can increase inflation and input costs, potentially weighing on broader equities.")

    # --- Tariff / trade-policy effects ---
    tariff = any(x in text for x in ["100% tariff", "tariff of 100%", "tariffs of up to 100%",
                                     "tariffs on", "tariff on", "punitive tariffs"])
    if tariff:
        if "oil" in text or "crude" in text or "natural gas" in text or "energy" in text:
            add("ENERGY / OIL DEMAND", "NEGATIVE",
                "Trade restrictions on major buyers or sellers can disrupt trade flows, raise uncertainty and potentially reduce affected demand.")
            add("GLOBAL OIL MARKET", "NEUTRAL",
                "The direct oil-price effect depends on whether physical supply is removed, rerouted, or simply becomes more expensive for buyers.")
            add("INFLATION / IMPORTERS", "NEGATIVE",
                "Tariffs can raise landed costs for affected imports and add uncertainty to supply chains.")
            add("AFFECTED EXPORTERS / TRADING PARTNERS", "NEGATIVE",
                "Reduced market access or higher trade barriers can pressure export volumes and margins.")

    # Avoid duplicate asset/impact pairs while preserving explanations.
    dedup = []
    seen = set()
    for e in effects:
        k = (e["asset"], e["impact"])
        if k not in seen:
            seen.add(k)
            dedup.append(e)

    # Overall article impact is based on the direct commodity effect first.
    direct = [e for e in dedup if e["asset"] == commodity]
    if direct:
        overall = direct[0]["impact"]
    elif dedup:
        # No direct commodity signal: neutral rather than forcing a market call.
        overall = "NEUTRAL"
    else:
        overall = "NEUTRAL"

    confidence = 55
    if direct:
        confidence = 82
    elif dedup:
        confidence = 72

        # ============================================================
    # NEWS-SPECIFIC TAKEAWAY / CONCLUSION
    # ============================================================
    #
    # IMPORTANT:
    # These fields must come from the actual article content.
    # Do NOT generate generic market commentary when the source
    # does not provide enough information.
    #

    def extract_sentences(value):
        value = clean(value)

        if not value:
            return []

        # Remove common RSS boilerplate.
        value = re.sub(
            r'^(read more|click here|continue reading)\s*[:\-]?\s*',
            '',
            value,
            flags=re.I
        )

        # Split into reasonably complete sentences.
        sentences = re.split(r'(?<=[.!?])\s+', value)

        result = []

        for sentence in sentences:
            sentence = sentence.strip()

            if len(sentence) < 35:
                continue

            # Avoid obvious RSS/navigation garbage.
            bad_phrases = [
                "subscribe",
                "sign up",
                "read more",
                "click here",
                "follow us",
                "advertisement",
                "all rights reserved",
            ]

            if any(x in sentence.lower() for x in bad_phrases):
                continue

            result.append(sentence)

        return result

    title_sentences = extract_sentences(title)
    summary_sentences = extract_sentences(summary)

    # ------------------------------------------------------------
    # News Takeaway
    # ------------------------------------------------------------
    #
    # Prefer the publisher's actual RSS description.
    # We do NOT create a sentence such as:
    # "The commodity is under downward pressure..."
    #
    # If there is no source summary, don't show a fake takeaway.
    #

    article_takeaway = None

    if summary_sentences:
        article_takeaway = " ".join(summary_sentences[:2])[:900]

    # ------------------------------------------------------------
    # Market Conclusion
    # ------------------------------------------------------------
    #
    # Select sentences from the actual news that contain evidence
    # relevant to the detected market impact.
    #
    # This means the conclusion is based on the article itself,
    # rather than a hardcoded paragraph.
    #

    evidence_words = [
        # price
        "price", "prices", "rose", "rises", "rising",
        "fell", "falls", "falling", "slid", "slides",
        "sliding", "dipped", "dips", "dropped", "drops",
        "declined", "declines", "higher", "lower",

        # supply
        "supply", "supplies", "production", "output",
        "exports", "export", "imports", "import",
        "shipment", "shipments", "flows", "outage",
        "disruption", "disruptions", "shortage",
        "surplus", "inventory", "inventories",
        "stockpiles",

        # demand
        "demand", "consumption", "buyers", "buying",
        "sales", "economic growth", "slowdown",
        "recession",

        # macro
        "inflation", "interest rates", "rate cut",
        "rate hike", "central bank", "dollar",
        "currency",

        # geopolitics / policy
        "tariff", "tariffs", "sanctions", "war",
        "conflict", "diplomacy", "negotiations",
        "iran", "russia", "ukraine", "opec",
        "saudi", "china", "united states", "us"
    ]

    # Use summary first because it normally contains more context
    # than the headline.
    candidate_sentences = summary_sentences[:]

    # If summary is unavailable, use the headline.
    if not candidate_sentences:
        candidate_sentences = title_sentences

    relevant_sentences = []

    for sentence in candidate_sentences:
        sentence_lower = sentence.lower()

        if any(word in sentence_lower for word in evidence_words):
            relevant_sentences.append(sentence)

    # Remove duplicate sentences while preserving order.
    unique_sentences = []
    seen_sentences = set()

    for sentence in relevant_sentences:
        key = re.sub(r"\s+", " ", sentence.lower()).strip()

        if key not in seen_sentences:
            seen_sentences.add(key)
            unique_sentences.append(sentence)

    if unique_sentences:
        conclusion = " ".join(unique_sentences[:3])[:1400]
    else:
        conclusion = None

    return overall, confidence, article_takeaway, conclusion, dedup

def classify(title, commodity, summary=""):
    return classify_market_impact(title, summary, commodity)

PAGE_TIME_CACHE = {}
PAGE_TIME_CACHE_TTL = 2 * 60
MAX_PAGE_TIME_LOOKUPS_PER_REFRESH = 20
PAGE_TIME_LOOKUPS_THIS_REFRESH = 0

def parse_iso_datetime(value):
    if not value:
        return None
    value = value.strip()
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def extract_page_times(url):
    """Best-effort source-page timestamps for Investing.com.
    RSS publication time is not assumed to equal the article's displayed update time.
    A small per-refresh lookup cap prevents the RSS refresh loop from becoming slow.
    """
    global PAGE_TIME_LOOKUPS_THIS_REFRESH
    if not url or "investing.com" not in url.lower():
        return None, None
    now = time.time()
    cached = PAGE_TIME_CACHE.get(url)
    if cached and now - cached[0] < PAGE_TIME_CACHE_TTL:
        return cached[1], cached[2]
    if PAGE_TIME_LOOKUPS_THIS_REFRESH >= MAX_PAGE_TIME_LOOKUPS_PER_REFRESH:
        return None, None
    PAGE_TIME_LOOKUPS_THIS_REFRESH += 1
    try:
        r = requests.get(
            url, timeout=8,
            headers={"User-Agent": "Mozilla/5.0 (compatible; MCX-Live-Commodity-News/4.0)"}
        )
        r.raise_for_status()
        body = r.text[:2_000_000]

        published = None
        updated = None
        patterns_published = [
            r'<meta[^>]+(?:property|name)=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',
            r'"datePublished"\s*:\s*"([^"]+)"',
            r'Published[^<]{0,80}(?:datetime=["\']([^"\']+)|([A-Z][a-z]+\s+\d{1,2},\s+\d{4},?[^<]{0,40}))',
        ]
        patterns_updated = [
            r'<meta[^>]+(?:property|name)=["\']article:modified_time["\'][^>]+content=["\']([^"\']+)',
            r'"dateModified"\s*:\s*"([^"]+)"',
            r'Updated[^<]{0,80}(?:datetime=["\']([^"\']+)|([A-Z][a-z]+\s+\d{1,2},\s+\d{4},?[^<]{0,40}))',
        ]
        for pat in patterns_published:
            m = re.search(pat, body, re.I | re.S)
            if m:
                for g in m.groups():
                    published = parse_iso_datetime(g) if g and "T" in g else None
                    if published:
                        break
                if published:
                    break
        for pat in patterns_updated:
            m = re.search(pat, body, re.I | re.S)
            if m:
                for g in m.groups():
                    updated = parse_iso_datetime(g) if g and "T" in g else None
                    if updated:
                        break
                if updated:
                    break
        PAGE_TIME_CACHE[url] = (now, published, updated)
        return published, updated
    except Exception:
        PAGE_TIME_CACHE[url] = (now, None, None)
        return None, None

def add_item(title, source, url, published_dt, summary="", updated_dt=None):
    title = clean(title)
    url = clean(url)
    summary = clean(summary)
    if not title or not url:
        return

    # Do not make additional article-page requests during RSS refresh.
    # RSS publication/update timestamps are used directly.

    # Age filtering uses the source publication time when available, not an RSS refresh time.
    now = datetime.now(timezone.utc)
    age_dt = published_dt or updated_dt
    if age_dt is not None and age_dt < now - timedelta(hours=MAX_ARTICLE_AGE_HOURS):
        return

    commodity = detect_commodity(title, summary)
    impact, confidence, article_takeaway, conclusion, market_effects = classify(
        title, commodity, summary
    )
    key = hashlib.sha256((url or title).encode("utf-8")).hexdigest()

    display_dt = updated_dt or published_dt
    NEWS[key] = {
        "id": key,
        "title": title,
        "source": source,
        "url": url,
        "published_at": published_dt.isoformat() if published_dt else None,
        "published_label": published_dt.astimezone(IST).strftime("%d %b %Y, %I:%M %p") if published_dt else "Time unavailable",
        "updated_at": updated_dt.isoformat() if updated_dt else None,
        "updated_label": updated_dt.astimezone(IST).strftime("%d %b %Y, %I:%M %p") if updated_dt else None,
        "display_time_at": display_dt.isoformat() if display_dt else None,
        "time_label": (
            ("Updated " + updated_dt.astimezone(IST).strftime("%d %b %Y, %I:%M %p")) if updated_dt else
            ("Published " + published_dt.astimezone(IST).strftime("%d %b %Y, %I:%M %p")) if published_dt else
            "Time unavailable"
        ),
        "commodity": commodity,
        "asset": commodity,
        "impact": impact,
        "confidence": confidence,
        "takeaway": article_takeaway,
        "conclusion": conclusion,
        "market_effects": market_effects,
    }

def fetch_feed(source, feed_url):
    started = time.time()

    try:
        # Cache-bust the RSS request.
        separator = "&" if "?" in feed_url else "?"
        request_url = f"{feed_url}{separator}_ts={int(time.time())}"

        response = requests.get(
            request_url,
            timeout=15,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/128.0 Safari/537.36"
                ),
                "Accept": (
                    "application/rss+xml, application/xml, "
                    "text/xml, text/html;q=0.9, */*;q=0.8"
                ),
                "Cache-Control": "no-cache, no-store, max-age=0",
                "Pragma": "no-cache",
            },
        )

        response.raise_for_status()

        feed = feedparser.parse(response.content)

        if getattr(feed, "bozo", 0) and not feed.entries:
            raise RuntimeError("Feed could not be parsed")

        count = 0

        for entry in feed.entries[:MAX_ARTICLES_PER_SOURCE]:
            dt = parse_datetime(entry)

            updated_dt = parse_datetime({
                "updated_parsed": entry.get("updated_parsed"),
                "updated": entry.get("updated"),
            })

            add_item(
                entry.get("title", ""),
                source,
                entry.get("link", ""),
                dt,
                entry.get("summary", ""),
                updated_dt,
            )

            count += 1

        SOURCE_STATUS[source] = {
            "ok": True,
            "articles": count,
            "message": "OK",
            "seconds": round(time.time() - started, 2),
        }

    except requests.HTTPError as exc:
        code = getattr(exc.response, "status_code", None)

        SOURCE_STATUS[source] = {
            "ok": False,
            "articles": 0,
            "message": f"HTTP {code}" if code else "HTTP error",
            "seconds": round(time.time() - started, 2),
        }

    except Exception as exc:
        SOURCE_STATUS[source] = {
            "ok": False,
            "articles": 0,
            "message": str(exc)[:120],
            "seconds": round(time.time() - started, 2),
        }

def fetch_investing_latest():
    """Fetch the live Investing.com commodities listing in addition to RSS.

    RSS feeds can be delayed or cached. The live section page is polled once per
    refresh so newly published Investing.com commodity stories can enter the
    dashboard even when the RSS feed has not caught up yet. Only a small number
    of newest links are followed to keep refreshes fast.
    """
    source = "Investing.com • Commodities (Live)"
    started = time.time()
    listing_url = "https://www.investing.com/news/commodities-news?cb=" + str(int(time.time()))
    try:
        response = requests.get(
            listing_url, timeout=12,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        seen = set()
        links = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "/news/commodities-news/" not in href:
                continue
            if href.startswith("/"):
                href = "https://www.investing.com" + href
            href = href.split("#")[0]
            title = clean(a.get_text(" ", strip=True))
            if not title or len(title) < 20 or href in seen:
                continue
            seen.add(href)
            links.append((title, href))
            if len(links) >= 8:
                break

        for title, href in links:
            # The article-page lookup extracts datePublished/dateModified.
            pub, upd = extract_page_times(href)
            now = datetime.now(timezone.utc)
            if pub or upd:
                add_item(title, source, href, pub or upd, "", upd)
            else:
                add_item(title, source, href, now, "", None)

        SOURCE_STATUS[source] = {
            "ok": True,
            "articles": len(links),
            "message": "Live page checked",
            "seconds": round(time.time() - started, 2),
        }
    except Exception as exc:
        SOURCE_STATUS[source] = {
            "ok": False,
            "articles": 0,
            "message": str(exc)[:120],
            "seconds": round(time.time() - started, 2),
        }

def refresh_news():
    global LAST_UPDATED, REFRESH_IN_PROGRESS
    global PAGE_TIME_LOOKUPS_THIS_REFRESH

    # If another request is already refreshing, don't start another one.
    if REFRESH_IN_PROGRESS:
        return False

    REFRESH_IN_PROGRESS = True
    PAGE_TIME_LOOKUPS_THIS_REFRESH = 0

    try:
        successful_sources = 0

        for source, url in ALL_FEEDS:
            fetch_feed(source, url)

            status = SOURCE_STATUS.get(source, {})
            if status.get("ok"):
                successful_sources += 1

        if GDELT_ENABLED:
            SOURCE_STATUS["GDELT"] = {
                "ok": False,
                "articles": 0,
                "message": "Optional; disabled by default",
                "seconds": 0,
            }

        # Mark the refresh time even if some feeds fail.
        LAST_UPDATED = datetime.now(timezone.utc)

        return successful_sources > 0

    finally:
        REFRESH_IN_PROGRESS = False

def sorted_articles():
    # Sort by the freshest known source timestamp. An updated article should
    # move upward even when its original publication time is older.
    def key(item):
        return item.get("display_time_at") or item.get("published_at") or ""
    return sorted(NEWS.values(), key=key, reverse=True)[:400]

@app.route("/")
def index():
    return render_template("index.html", refresh_seconds=REFRESH_SECONDS)

@app.route("/api/news")
def api_news():
    now = datetime.now(timezone.utc)

    needs_refresh = (
        LAST_UPDATED is None
        or (now - LAST_UPDATED).total_seconds() >= SERVER_CACHE_TTL
    )

    if needs_refresh and not REFRESH_IN_PROGRESS:
        refresh_news()

    articles = sorted_articles()

    latest = articles[0].get("display_time_at") if articles else None

    latest_age_minutes = None

    if latest:
        try:
            latest_dt = datetime.fromisoformat(latest)

            latest_age_minutes = max(
                0,
                int((now - latest_dt).total_seconds() / 60)
            )

        except Exception:
            pass

    return jsonify({
        "updated_at": (
            LAST_UPDATED.astimezone(IST).isoformat()
            if LAST_UPDATED else None
        ),

        "server_time": now.astimezone(IST).isoformat(),

        "count": len(articles),

        "latest_age_minutes": latest_age_minutes,

        "sources_ok": sum(
            1 for x in SOURCE_STATUS.values()
            if x.get("ok")
        ),

        "sources_total": len(SOURCE_STATUS),

        "sources": SOURCE_STATUS,

        "articles": articles,
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

