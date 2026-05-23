#!/usr/bin/env python3
"""
Idaho Homeless Tracker — Weekly Scraper
Run: python scraper.py
Output: data/incidents.json, data/housing_meta.json
Cron (Sunday 2am): 0 2 * * 0 python scraper.py  (run from project folder)
"""

import json, time, re, os, urllib.request, urllib.parse, random
from datetime import datetime, timedelta

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(OUTPUT_DIR, exist_ok=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def fetch(url, delay=2):
    time.sleep(delay)
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"  FETCH ERROR {url}: {e}")
        return ""

# ── REDDIT ────────────────────────────────────────────────────────────────────

SUBREDDITS = [
    ('Boise',               43.6150, -116.2023),
    ('Coeur_d_Alene',       47.6741, -116.7800),
    ('Idaho',               44.0682, -114.7420),
    ('Nampa',               43.5407, -116.5635),
    ('TwinFalls',           42.5630, -114.4618),
    ('Pocatello',           42.8713, -112.4455),
    ('LewisClarknorthwest', 46.4165, -117.0177),
    ('SandpointIdaho',      48.2766, -116.5535),
]

# Must match at least one of these (whole-word or phrase matched)
KEYWORDS = ['homeless','encampment','tent city','tent camp','vagrant',
            'sleeping outside','sleeping rough','panhandl','unsheltered',
            'shelter overflow','street camp','living in their car',
            'living in a tent','people living outside']

# Exclude posts containing these — catches false positives
EXCLUDE_KEYWORDS = ['campaign','primary','republican','democrat','election',
                    'camp fire','camp site','campsite','camping trip','summer camp',
                    'camp david','transient ischemic','transit','transistor']

def is_homeless_related(text):
    t = text.lower()
    if any(ex in t for ex in EXCLUDE_KEYWORDS):
        return False
    # 'camp' alone only counts if paired with homeless context words
    if 'camp' in t and not any(kw in t for kw in ['homeless','encampment','tent','unsheltered','vagrant']):
        return False
    return any(kw in t for kw in KEYWORDS)

def scrape_reddit():
    print("Scraping Reddit...")
    results = []
    cutoff = datetime.now() - timedelta(days=30)
    for sub, lat, lng in SUBREDDITS:
        q = urllib.parse.quote('homeless OR encampment OR "tent city" OR transient')
        url = f"https://www.reddit.com/r/{sub}/search.json?q={q}&restrict_sr=1&sort=new&limit=25"
        raw = fetch(url, delay=2.5)
        if not raw:
            continue
        try:
            posts = json.loads(raw).get('data', {}).get('children', [])
        except:
            continue
        for post in posts:
            p = post.get('data', {})
            title = p.get('title', '')
            created = datetime.fromtimestamp(p.get('created_utc', 0))
            score = p.get('score', 0)
            if created < cutoff or score < 2:
                continue
            if not is_homeless_related(title + ' ' + p.get('selftext','')):
                continue
            results.append({
                'type': 'reddit',
                'lat': round(lat + random.uniform(-0.04, 0.04), 4),
                'lng': round(lng + random.uniform(-0.04, 0.04), 4),
                'title': f"r/{sub}",
                'desc': title[:200],
                'date': created.strftime('%Y-%m-%d'),
                'source': f"r/{sub}",
                'url': 'https://reddit.com' + p.get('permalink', ''),
                'score': score
            })
            print(f"  [r/{sub}] {title[:60]}")
    print(f"  → {len(results)} Reddit posts")
    return results

# ── NEWS RSS ──────────────────────────────────────────────────────────────────

NEWS_FEEDS = [
    ('KTVB (Boise)',        'https://www.ktvb.com/feeds/syndication/rss/news',                       43.6150, -116.2023),
    ('KIVI (Boise)',        'https://kivitv.com/news.rss',                                           43.6150, -116.2023),
    ('East Idaho News',     'https://eastidahonews.com/feed',                                        43.4917, -112.0408),
    ('Magic Valley TN',     'https://magicvalley.com/search/?q=homeless&template=rss',               42.5630, -114.4618),
    ('Idaho State Journal', 'https://www.idahostatejournal.com/search/?q=homeless&template=rss',     42.8713, -112.4455),
    ('Post Register',       'https://www.postregister.com/search/?q=homeless&template=rss',          43.4917, -112.0408),
]

def extract_items(xml, source, lat, lng):
    results = []
    for item in re.findall(r'<item>(.*?)</item>', xml, re.DOTALL)[:20]:
        def tag(t): m = re.search(rf'<{t}[^>]*>(.*?)</{t}>', item, re.DOTALL); return re.sub(r'<[^>]+>','',m.group(1)).replace('<![CDATA[','').replace(']]>','').strip() if m else ''
        title, desc, date_s, link = tag('title'), tag('description'), tag('pubDate'), tag('link')
        if not is_homeless_related(title + ' ' + desc):
            continue
        try:
            pub = datetime.strptime(date_s[:25], '%a, %d %b %Y %H:%M:%S')
            if pub < datetime.now() - timedelta(days=45): continue
            date_out = pub.strftime('%Y-%m-%d')
        except:
            date_out = datetime.now().strftime('%Y-%m-%d')
        itype = 'arrest' if any(w in (title+desc).lower() for w in ['arrest','cited','cleared','enforcement','removed']) else 'camp' if any(w in (title+desc).lower() for w in ['camp','encampment','tent']) else 'news'
        results.append({
            'type': itype,
            'lat': round(lat + random.uniform(-0.03, 0.03), 4),
            'lng': round(lng + random.uniform(-0.03, 0.03), 4),
            'title': title[:100],
            'desc': desc[:200],
            'date': date_out,
            'source': source,
            'url': link
        })
        print(f"  [{source}] {title[:60]}")
    return results

def scrape_news():
    print("Scraping news RSS feeds...")
    results = []
    for name, url, lat, lng in NEWS_FEEDS:
        print(f"  Fetching {name}...")
        xml = fetch(url, delay=2)
        if xml:
            results.extend(extract_items(xml, name, lat, lng))
    print(f"  → {len(results)} news items")
    return results

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n=== Idaho Homeless Tracker Scraper — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")
    incidents = scrape_reddit() + scrape_news()
    incidents.sort(key=lambda x: x['date'], reverse=True)
    seen, deduped = set(), []
    for i in incidents:
        k = i['title'][:40].lower()
        if k not in seen:
            seen.add(k); deduped.append(i)
    out = os.path.join(OUTPUT_DIR, 'incidents.json')
    with open(out, 'w') as f:
        json.dump({'updated': datetime.now().isoformat(), 'count': len(deduped), 'incidents': deduped}, f, indent=2)
    meta = os.path.join(OUTPUT_DIR, 'housing_meta.json')
    with open(meta, 'w') as f:
        json.dump({'source':'Idaho Housing and Finance Association','year':2024,'total_pit':1756,'note':'Manual update annually from idahohousing.com PDF report'}, f, indent=2)
    print(f"\n✓ {len(deduped)} incidents → {out}")
    print("✓ Push to GitHub to auto-deploy: git add . && git commit -m 'Weekly scrape' && git push\n")

if __name__ == '__main__':
    main()
