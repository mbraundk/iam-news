import anthropic
import json
import os
from datetime import datetime

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

prompt = """Search the web for the 50 most recent news articles about Identity and Access Management (IAM).
Include topics like: IAM security, identity governance, SSO, MFA, privileged access management (PAM), zero trust, Active Directory, OAuth, SAML, SCIM, Okta, Microsoft Entra, CyberArk, SailPoint, Ping Identity, ForgeRock, and related IAM vendors and technologies.

For each article return a JSON array (no markdown, no backticks, raw JSON only) with exactly these fields:
- title: the article headline
- url: the direct link to the article
- source: the publisher name
- date: publication date as a short string like "Apr 12, 2025"
- summary: a 2-3 sentence summary written for IAM professionals, explaining what happened and why it matters
- image: the article's main image URL if available, otherwise null

IMPORTANT: Return ONLY the raw JSON array. No preamble, no explanation, no markdown code blocks. Start directly with [ and end with ]"""

print("Fetching IAM news...")
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4000,
    tools=[{"type": "web_search_20250305", "name": "web_search"}],
    messages=[{"role": "user", "content": prompt}]
)

text_block = next((b for b in response.content if b.type == "text"), None)
if not text_block:
    all_types = [b.type for b in response.content]
    raise ValueError(f"No text block found. Block types were: {all_types}")

raw = text_block.text.strip()
print("Raw response preview:", raw[:300])

raw = raw.replace("```json", "").replace("```", "").strip()

start = raw.find("[")
end = raw.rfind("]")

if start == -1 or end == -1:
    raise ValueError(f"No JSON array found in response. Full text:\n{raw}")

articles = json.loads(raw[start:end+1])
articles = articles[:50]

output = {
    "updated": datetime.utcnow().strftime("%B %d, %Y at %H:%M UTC"),
    "articles": articles
}

with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"Saved {len(articles)} articles to news.json")
