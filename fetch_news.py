import anthropic
import json
import os
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

def danish_date(dt):
    return dt.strftime("%-d %b %Y")

ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
NEWS_KEY = os.environ["NEWS_API_KEY"]

RSS_FEEDS = [
    ("Dark Reading",        "https://www.darkreading.com/rss.xml"),
    ("Bleeping Computer",   "https://www.bleepingcomputer.com/feed/"),
    ("Help Net Security",   "https://www.helpnetsecurity.com/feed/"),
    ("SC Magazine",         "https://www.scmagazine.com/feed"),
    ("The Hacker News",     "https://feeds.feedburner.com/TheHackersNews"),
    ("Krebs on Security",   "https://krebsonsecurity.com/feed/"),
]

PAYWALL_DOMAINS = [
    "wsj.com", "ft.com", "bloomberg.com", "economist.com",
    "thetimes.co.uk", "nytimes.com", "washingtonpost.com",
    "hbr.org", "wired.com", "technologyreview.com",
]

HEADERS = {"User-Agent": "IAMNews/1.0 (+https://iamnews.org)"}

# ── OG IMAGE FETCHER ──────────────────────────────────────────────────────────

class OGParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.og_image = None
    def handle_starttag(self, tag, attrs):
        if tag == "meta" and not self.og_image:
            d = dict(attrs)
            if d.get("property") == "og:image" and d.get("content"):
                self.og_image = d["content"]
            elif d.get("name") == "og:image" and d.get("content"):
                self.og_image = d["content"]

def get_og_image(url):
    try:
        req = urllib.request.Request(url, headers={**HEADERS, "Range": "bytes=0-8192"})
        with urllib.request.urlopen(req, timeout=5) as r:
            html = r.read().decode("utf-8", errors="ignore")
        parser = OGParser()
        parser.feed(html)
        return parser.og_image
    except Exception:
        return None

# ── RSS FETCHER ───────────────────────────────────────────────────────────────

NS = {
    "media":   "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc":      "http://purl.org/dc/elements/1.1/",
}

def parse_rss(source_name, feed_url):
    articles = []
    try:
        req = urllib.request.Request(feed_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
        root = ET.fromstring(raw)
        channel = root.find("channel") or root
        items = channel.findall("item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        for item in items[:30]:
            def t(tag, ns=None):
                el = item.find(tag) if ns is None else item.find(tag, ns)
                return (el.text or "").strip() if el is not None and el.text else ""

            title = t("title")
            url   = t("link") or t("guid")
            if not url and item.find("{http://www.w3.org/2005/Atom}link") is not None:
                url = item.find("{http://www.w3.org/2005/Atom}link").get("href", "")
            desc  = t("description") or t("{http://www.w3.org/2005/Atom}summary")
            pub   = t("pubDate") or t("published") or t("{http://www.w3.org/2005/Atom}published")

            # Try to get image from media tags
            image = None
            mc = item.find("media:content", NS)
            if mc is not None:
                image = mc.get("url")
            if not image:
                mt = item.find("media:thumbnail", NS)
                if mt is not None:
                    image = mt.get("url")
            if not image:
                enc = item.find("enclosure")
                if enc is not None and "image" in (enc.get("type") or ""):
                    image = enc.get("url")

            # Parse date
            date_str = ""
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT",
                        "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
                try:
                    dt = datetime.strptime(pub.strip(), fmt)
                    date_str = danish_date(dt)
                    break
                except Exception:
                    continue
            if not date_str and pub:
                date_str = pub[:10]

            if title and url:
                articles.append({
                    "title": title,
                    "url": url,
                    "source": source_name,
                    "date": date_str,
                    "description": desc,
                    "image": image,
                })
    except Exception as e:
        print(f"  Warning: could not fetch {source_name}: {e}")
    return articles

# ── NEWSAPI FETCHER ───────────────────────────────────────────────────────────

def fetch_newsapi():
    url = (
        "https://newsapi.org/v2/everything"
        "?q=%22identity+and+access+management%22+OR+%22privileged+access+management%22"
        "+OR+%22zero+trust+identity%22+OR+%22Okta%22+OR+%22Microsoft+Entra%22"
        "+OR+%22CyberArk%22+OR+%22SailPoint%22+OR+%22identity+governance%22+OR+%22Omada%22"
        "&language=en&sortBy=publishedAt&pageSize=50"
        f"&apiKey={NEWS_KEY}"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    if data.get("status") != "ok":
        raise ValueError(f"NewsAPI error: {data.get('message')}")
    articles = []
    for a in data["articles"]:
        if "pypi.org" in (a.get("url") or ""):
            continue
        pub = a.get("publishedAt", "")
        try:
            dt = datetime.strptime(pub, "%Y-%m-%dT%H:%M:%SZ")
            date_str = danish_date(dt)
        except Exception:
            date_str = pub[:10]
        articles.append({
            "title": a.get("title") or "",
            "url": a.get("url") or "",
            "source": (a.get("source") or {}).get("name") or "",
            "date": date_str,
            "description": a.get("description") or "",
            "image": a.get("urlToImage") or None,
        })
    return articles

# ── DEDUPLICATION ─────────────────────────────────────────────────────────────

def is_sponsored(article):
    indicators = ["sponsored", "partner content", "paid post", "advertorial", "promoted"]
    title = (article.get("title") or "").lower()
    desc = (article.get("description") or "").lower()
    url = (article.get("url") or "").lower()
    return any(i in title or i in desc or i in url for i in indicators)

def is_paywalled(article):
    url = (article.get("url") or "").lower()
    return any(domain in url for domain in PAYWALL_DOMAINS)

def deduplicate(articles):
    seen_urls = set()
    seen_titles = set()
    unique = []
    for a in articles:
        url = a.get("url", "").split("?")[0].rstrip("/")
        title_key = a.get("title", "").lower()[:60]
        if url in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url)
        seen_titles.add(title_key)
        unique.append(a)
    return unique

# ── CLAUDE FILTER + SCORE + SUMMARIZE ────────────────────────────────────────

def filter_score_summarize(client, article):
    content = f"Title: {article['title']}\nDescription: {article.get('description') or ''}"
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{"role": "user", "content": f"""You are a filter and scorer for an IAM news site read by identity and access management professionals.

Decide if this article is relevant to IAM professionals. It must be directly about identity, authentication, authorization, access management, zero trust, PAM, SSO, MFA, identity governance, or specific IAM vendors (Okta, CyberArk, SailPoint, Microsoft Entra, Ping Identity, ForgeRock, Omada Identity, etc.).

Note: If the article mentions "Omada", only accept it if it is clearly about Omada Identity (the IAM/IGA vendor), not Omada Health or other unrelated companies.

If NOT relevant, reply with exactly: SKIP

If relevant, reply in this exact format and nothing else:
SCORE: <number 1-10>
SUMMARY: <two sentences, factual and direct: first states what happened, second provides the key details or context. No implications, no significance statements, no editorializing. Just the facts.>

Score 9-10: major breach, acquisition, product launch, or policy change with wide IAM impact
Score 6-8: significant vendor news, new research, or regulatory update relevant to IAM
Score 1-5: minor update, opinion piece, or niche interest

Article:
{content}"""}]
    )
    return response.content[0].text.strip()

# ── MAIN ──────────────────────────────────────────────────────────────────────

print("Fetching RSS feeds...")
all_articles = []
for name, url in RSS_FEEDS:
    print(f"  {name}...")
    items = parse_rss(name, url)
    print(f"    Got {len(items)} items")
    all_articles.extend(items)

print("Fetching NewsAPI...")
try:
    newsapi_items = fetch_newsapi()
    print(f"  Got {len(newsapi_items)} items")
    all_articles.extend(newsapi_items)
except Exception as e:
    print(f"  Warning: NewsAPI failed: {e}")

print(f"\nTotal before dedup: {len(all_articles)}")
all_articles = deduplicate(all_articles)
print(f"Total after dedup: {len(all_articles)}")
all_articles = [a for a in all_articles if not is_sponsored(a)]
print(f"Total after sponsored filter: {len(all_articles)}")

print("\nFiltering, scoring and summarizing with Claude...")
client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

processed = []
for i, a in enumerate(all_articles):
    print(f"  [{i+1}/{len(all_articles)}] {a['title'][:70]}")
    try:
        result = filter_score_summarize(client, a)
        if result == "SKIP":
            print("    → Skipped")
            continue
        score = 5
        summary = ""
        for line in result.splitlines():
            if line.startswith("SCORE:"):
                try:
                    score = int(line.replace("SCORE:", "").strip())
                except ValueError:
                    pass
            elif line.startswith("SUMMARY:"):
                summary = line.replace("SUMMARY:", "").strip()
        if not summary:
            summary = a.get("description") or ""
        print(f"    → Score: {score}")

        # Fetch og:image if no image found in feed
        image = a.get("image")
        if not image and a.get("url"):
            print(f"    → Fetching og:image...")
            image = get_og_image(a["url"])

        processed.append({
            "title": a["title"],
            "url": a["url"],
            "source": a["source"],
            "date": a["date"],
            "summary": summary,
            "image": image,
            "importance": score,
            "paywall": is_paywalled(a),
        })
    except Exception as e:
        print(f"    Warning: {e}")

print(f"\nProcessed {len(processed)} relevant articles")

# Filter to last 7 days for top story candidates
now = datetime.now(timezone.utc)

def parse_date_str(date_str):
    for fmt in ("%d. %b. %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None

recent = [a for a in processed if (lambda d: d and (now - d).days < 7)(parse_date_str(a.get("date", "")))]
top_story_pool = recent if recent else processed

# Sort by importance for top stories, keep chronological for news
top_stories = sorted(top_story_pool, key=lambda x: x.get("importance", 0), reverse=True)[:5]
top_urls = {a["url"] for a in top_stories}
news = [a for a in processed if a["url"] not in top_urls][:30]

output = {
    "updated": datetime.utcnow().strftime("%B %d, %Y at %H:%M UTC"),
    "top_stories": top_stories,
    "news": news,
}

with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"Done. Saved {len(top_stories)} top stories and {len(news)} news articles.")
