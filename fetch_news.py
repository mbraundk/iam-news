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
        "?q=identity+access+management+OR+IAM+OR+%22privileged+access%22+OR+%22zero+trust%22+OR+%22single+sign-on%22+OR+Okta+OR+%22Microsoft+Entra%22+OR+CyberArk+OR+SailPoint"
        "&language=en"
        "&sortBy=publishedAt"
        "&pageSize=20"
        f"&apiKey={NEWS_KEY}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "IAMNews/1.0"})
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    if data.get("status") != "ok":
        raise ValueError(f"NewsAPI error: {data.get('message')}")
    return data["articles"]

def summarize(client, article):
    content = f"Title: {article['title']}\nDescription: {article.get('description') or ''}\nContent: {article.get('content') or ''}"
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": f"Write a 2-3 sentence summary of this news article for IAM professionals, explaining what happened and why it matters:\n\n{content}"}]
    )
    return response.content[0].text.strip()

print("Fetching articles from NewsAPI...")
raw_articles = fetch_articles()
print(f"Got {len(raw_articles)} articles. Generating summaries...")

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

articles = []
for i, a in enumerate(raw_articles):
    print(f"Summarizing {i+1}/{len(raw_articles)}: {a['title'][:60]}")
    try:
        summary = summarize(client, a)
    except Exception as e:
        print(f"  Warning: could not summarize: {e}")
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
    })

output = {
    "updated": datetime.utcnow().strftime("%B %d, %Y at %H:%M UTC"),
    "articles": articles
}

with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"Done. Saved {len(articles)} articles to news.json")
