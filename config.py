import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()

REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "60"))
MAX_ARTICLES_PER_SOURCE = int(os.getenv("MAX_ARTICLES_PER_SOURCE", "40"))
MAX_ARTICLE_AGE_HOURS = int(os.getenv("MAX_ARTICLE_AGE_HOURS", "72"))
GDELT_ENABLED = os.getenv("GDELT_ENABLED", "0") == "1"

# These are public RSS feeds / search feeds. No paid API key is required.
# Google News RSS custom searches are used as a broad, fresh source aggregator.
GOOGLE_QUERIES = [
    ("Google News • MCX", '"MCX" commodity OR gold OR silver OR crude OR copper'),
    ("Google News • Gold", 'gold commodity OR gold prices OR bullion'),
    ("Google News • Silver", 'silver commodity OR silver prices'),
    ("Google News • Crude", 'crude oil OR Brent OR WTI'),
    ("Google News • Natural Gas", '"natural gas" OR LNG'),
    ("Google News • Base Metals", 'copper OR aluminium OR aluminum OR zinc OR nickel'),
    ("Google News • India Commodities", 'India commodity markets OR MCX'),
    ("Google News • Global Commodities", 'global commodity markets OR commodities'),
]

RSS_FEEDS = [
    ("Business Standard • Commodities",
     "https://www.business-standard.com/rss/markets/commodities-10609.rss"),
    ("Economic Times • Markets",
     "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    # Investing.com official Commodities & Futures RSS feed.
    ("Investing.com • Commodities",
     "https://www.investing.com/rss/news_11.rss"),
]

def google_news_feeds():
    feeds = []
    for name, query in GOOGLE_QUERIES:
        url = (
            "https://news.google.com/rss/search?q="
            + quote_plus(query)
            + "&hl=en-IN&gl=IN&ceid=IN:en"
        )
        feeds.append((name, url))
    return feeds

ALL_FEEDS = RSS_FEEDS + google_news_feeds()
