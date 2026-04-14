import anthropic
import json
import os
import urllib.request
from datetime import datetime

ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
NEWS_KEY = os.environ["NEWS_API_KEY"]

def fetch_articles():
    url = (
        "https://newsapi.org/v2/everything"
        "?q=%22identity+and+access+management%22+OR+%22privileged+access+management%22+OR+%22zero+trust+identity%22+OR+%22Okta%22+OR+%22Microsoft+Entra%22+OR+%22CyberArk%22+OR+%22SailPoint%22+OR+%22identity+governance%22"
        "&language=en"
        "&sortBy=publishedAt"
        "&pageSize=100"
        f"&apiKey={NEWS_KEY}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "IAMNews/1.0"})
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    if data.get("status") != "ok":
        raise ValueError(f"NewsAPI error: {data.get('message')}")
    articles = data["articles"]
    articles = [a for a in articles if "pypi.org" not in (a.get("url") or "")]
    return articles

def filter_summarize_score(client, article):
    content = f"Title: {article['title']}\nDescription: {article.get('description') or ''}\nContent: {article.get('content') or ''}"
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{"role": "user", "content": f"""You are a filter and scorer for an IAM news site read by identity and access management professionals.

First decide if this article is relevant to IAM professionals. It must be directly about identity, authentication, authorization, access management, zero trust, PAM, SSO, MFA, identity governance, or specific IAM vendors (Okta, CyberArk, SailPoint, Microsoft Entra, Ping Identity, ForgeRock, etc.).

If NOT relevant, reply with exactly: SKIP

If relevant, reply in this exact format and nothing else:
SCORE: <number 1-10>
SUMMARY: <single sentence for IAM professionals explaining what happened and why it matters>

Score 9-10: major breach, acquisition, product launch, or policy change with wide IAM impact
Score 6-8: significant vendor news, new research, or regulatory update relevant to IAM
Score 1-5: minor update, opinion piece, or niche interest

Article:
{content}"""}]
    )
    return response.content[0].text.strip()

print("Fetching articles from NewsAPI...")
raw_articles = fetch_articles()
print(f"Got {len(raw_articles)} articles. Filtering, scoring and summarizing...")

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

articles = []
for i, a in enumerate(raw_articles):
    print(f"Processing {i+1}/{len(raw_articles)}: {a['title'][:60]}")
    try:
        result = filter_summarize_score(client, a)
        if result == "SKIP":
            print("  → Skipped (not IAM relevant)")
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

        print(f"  → Score: {score}")

    except Exception as e:
        print(f"  Warning: could not process: {e}")
        score = 5
        summary = a.get("description") or ""

    pub = a.get("publishedAt", "")
    try:
        dt = datetime.strptime(pub, "%Y-%m-%dT%H:%M:%SZ")
        date_str = dt.strftime("%b %d, %Y")
    except Exception:
        date_str = pub[:10]

    articles.append({
        "title": a.get("title") or "",
        "url": a.get("url") or "",
        "source": (a.get("source") or {}).get("name") or "",
        "date": date_str,
        "summary": summary,
        "image": a.get("urlToImage") or None,
        "importance": score,
    })

articles = articles[:20]

# Top stories = highest importance score
top_stories = sorted(articles, key=lambda x: x.get("importance", 0), reverse=True)[:6]
top_urls = [a["url"] for a in top_stories]

output = {
    "updated": datetime.utcnow().strftime("%B %d, %Y at %H:%M UTC"),
    "articles": articles,
    "top_stories": top_urls
}

with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"Done. Saved {len(articles)} articles, {len(top_stories)} top stories to news.json")
