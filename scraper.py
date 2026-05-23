#!/usr/bin/env python3
"""
Idaho Homeless Tracker — Weekly Scraper
Run: python3 scraper.py
Output: data/incidents.json, data/county_data.json
Schedule: cron weekly (Sunday 2am)
  0 2 * * 0 /usr/bin/python3 /path/to/scraper.py >> /path/to/scraper.log 2>&1
"""

import json
import time
import re
import os
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(OUTPUT_DIR, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; IdahoHomelessTracker/1.0; +https://idahoscore.com)'
}

def fetch(url, delay=1.5):
    """Fetch URL with polite delay."""
    time.sleep(delay)
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"  FETCH ERROR {url}: {e}")
        return ""

# ── REDDIT SCRAPER ────────────────────────────────────────────────────────────
# Uses Reddit's public JSON API (no auth needed for public subreddits)

SUBREDDITS = [
    'Boise',
    'Coeur_d_Alene',
    'Idaho',
    'Nampa',
    'TwinFalls',
    'Pocatello',
    'LewisClarknorthwest',  # Lewiston area
]

HOMELESS_KEYWORDS = [
    'homeless', 'camp', 'encampment', 'tent city', 'transient',
    'vagrants', 'sleeping outside', 'living outside', 'panhandling',
    'shelter', 'unsheltered', 'sleeping rough'
]

# Approximate city coords for geocoding subreddit posts
SUBREDDIT_COORDS = {
    'Boise':              (43.6150, -116.2023),
    'Coeur_d_Alene':      (47.6741, -116.7800),
    'Idaho':              (44.0682, -114.7420),  # state center
    'Nampa':              (43.5407, -116.5635),
    'TwinFalls':          (42.5630, -114.4618),
    'Pocatello':          (42.8713, -112.4455),
    'LewisClarknorthwest':(46.4165, -117.0177),
}

def scrape_reddit():
    print("Scraping Reddit...")
    results = []
    cutoff = datetime.now() - timedelta(days=30)

    for sub in SUBREDDITS:
        url = f"https://www.reddit.com/r/{sub}/search.json?q={urllib.parse.quote('homeless OR encampment OR tent+city OR transient')}&restrict_sr=1&sort=new&limit=25"
        raw = fetch(url, delay=2)
        if not raw:
            continue
        try:
            data = json.loads(raw)
            posts = data.get('data', {}).get('children', [])
        except Exception as e:
            print(f"  Parse error r/{sub}: {e}")
            continue

        for post in posts:
            p = post.get('data', {})
            title = p.get('title', '')
            selftext = p.get('selftext', '')
            created = datetime.fromtimestamp(p.get('created_utc', 0))
            score = p.get('score', 0)
            permalink = 'https://reddit.com' + p.get('permalink', '')

            if created < cutoff:
                continue

            text_lower = (title + ' ' + selftext).lower()
            if not any(kw in text_lower for kw in HOMELESS_KEYWORDS):
                continue

            # Skip very low-score posts (likely noise)
            if score < 3:
                continue

            coords = SUBREDDIT_COORDS.get(sub, (44.0682, -114.7420))
            # Slight jitter so pins don't stack
            import random
            jitter_lat = coords[0] + random.uniform(-0.05, 0.05)
            jitter_lng = coords[1] + random.uniform(-0.05, 0.05)

            results.append({
                'type': 'reddit',
                'lat': round(jitter_lat, 4),
                'lng': round(jitter_lng, 4),
                'title': f"r/{sub}",
                'desc': title[:200],
                'date': created.strftime('%Y-%m-%d'),
                'source': f"r/{sub}",
                'url': permalink,
                'score': score
            })
            print(f"  [Reddit] r/{sub}: {title[:60]}")

    print(f"  → {len(results)} Reddit posts found")
    return results

# ── NEWS RSS SCRAPER ──────────────────────────────────────────────────────────

NEWS_FEEDS = [
    # (name, rss_url, default_coords)
    ('BoiseDev',        'https://boisedev.com/feed/',                         (43.6150, -116.2023)),
    ('Idaho Press',     'https://www.idahopress.com/search/?q=homeless&template=rss', (43.5407, -116.5635)),
    ('Idaho Statesman', 'https://www.idahostatesman.com/news/?widgetName=rssfeed&widgetContentId=822843&getXmlFeed=true', (43.6150, -116.2023)),
    ('CdA Press',       'https://cdapress.com/feed/',                         (47.6741, -116.7800)),
    ('Post Register',   'https://www.postregister.com/search/?q=homeless&template=rss', (43.4917, -112.0408)),
    ('Twin Falls Times-News', 'https://magicvalley.com/search/?q=homeless&template=rss', (42.5630, -114.4618)),
    ('Idaho State Journal',   'https://www.idahostatejournal.com/search/?q=homeless&template=rss', (42.8713, -112.4455)),
    ('Lewiston Tribune', 'https://lmtribune.com/search/?q=homeless&template=rss', (46.4165, -117.0177)),
]

def extract_rss_items(xml, source_name, default_coords):
    """Parse RSS XML and extract homeless-related items."""
    results = []
    # Simple regex-based RSS parse (no lxml needed)
    items = re.findall(r'<item>(.*?)</item>', xml, re.DOTALL)
    for item in items[:20]:
        title_m = re.search(r'<title[^>]*>(.*?)</title>', item, re.DOTALL)
        desc_m  = re.search(r'<description[^>]*>(.*?)</description>', item, re.DOTALL)
        date_m  = re.search(r'<pubDate>(.*?)</pubDate>', item)
        link_m  = re.search(r'<link>(.*?)</link>', item)

        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ''
        desc  = re.sub(r'<[^>]+>', '', desc_m.group(1)).strip()[:300] if desc_m else ''
        date_str = date_m.group(1).strip() if date_m else ''
        link  = link_m.group(1).strip() if link_m else ''

        # Remove CDATA wrappers
        for s in ['<![CDATA[', ']]>']:
            title = title.replace(s, '').strip()
            desc  = desc.replace(s, '').strip()

        text_lower = (title + ' ' + desc).lower()
        if not any(kw in text_lower for kw in HOMELESS_KEYWORDS):
            continue

        # Parse date
        try:
            pub_date = datetime.strptime(date_str[:25], '%a, %d %b %Y %H:%M:%S')
            if pub_date < datetime.now() - timedelta(days=45):
                continue
            date_out = pub_date.strftime('%Y-%m-%d')
        except:
            date_out = datetime.now().strftime('%Y-%m-%d')

        # Classify incident type
        itype = 'news'
        if any(w in text_lower for w in ['arrest', 'cited', 'removed', 'cleared', 'enforcement']):
            itype = 'arrest'
        elif any(w in text_lower for w in ['camp', 'encampment', 'tent']):
            itype = 'camp'

        import random
        coords = default_coords
        jlat = coords[0] + random.uniform(-0.03, 0.03)
        jlng = coords[1] + random.uniform(-0.03, 0.03)

        results.append({
            'type': itype,
            'lat': round(jlat, 4),
            'lng': round(jlng, 4),
            'title': title[:100],
            'desc': desc[:200],
            'date': date_out,
            'source': source_name,
            'url': link
        })
        print(f"  [News] {source_name}: {title[:60]}")
    return results

def scrape_news():
    print("Scraping news RSS feeds...")
    results = []
    for name, url, coords in NEWS_FEEDS:
        print(f"  Fetching {name}...")
        xml = fetch(url, delay=2)
        if xml:
            items = extract_rss_items(xml, name, coords)
            results.extend(items)
    print(f"  → {len(results)} news items found")
    return results

# ── IDAHO HOUSING DATA ────────────────────────────────────────────────────────

def scrape_idaho_housing():
    """
    Fetch latest PIT count page from Idaho Housing.
    Data is in PDFs so we return a stub with the known 2024 totals.
    For full automation, integrate a PDF-to-text parser (pdfminer, pypdf2).
    """
    print("Checking Idaho Housing for updates...")
    # TODO: Fetch and parse https://www.idahohousing.com/homelessness-services-programs/idaho-homelessness-community-report/
    # The PDFs require extraction — implement with: pip install pypdf2
    # For now return static marker so the pipeline is ready
    return {
        "source": "Idaho Housing and Finance Association",
        "year": 2024,
        "total_pit": 1756,
        "note": "Manual update required — fetch PDF from idahohousing.com annually"
    }

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n=== Idaho Homeless Tracker Scraper — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    incidents = []
    incidents.extend(scrape_reddit())
    incidents.extend(scrape_news())

    # Sort by date desc
    incidents.sort(key=lambda x: x['date'], reverse=True)

    # Deduplicate by title similarity (simple)
    seen_titles = set()
    deduped = []
    for inc in incidents:
        key = inc['title'][:40].lower()
        if key not in seen_titles:
            seen_titles.add(key)
            deduped.append(inc)

    out_path = os.path.join(OUTPUT_DIR, 'incidents.json')
    with open(out_path, 'w') as f:
        json.dump({
            'updated': datetime.now().isoformat(),
            'count': len(deduped),
            'incidents': deduped
        }, f, indent=2)

    housing_data = scrape_idaho_housing()
    housing_path = os.path.join(OUTPUT_DIR, 'housing_meta.json')
    with open(housing_path, 'w') as f:
        json.dump(housing_data, f, indent=2)

    print(f"\n✓ Wrote {len(deduped)} incidents to {out_path}")
    print(f"✓ Wrote housing meta to {housing_path}")
    print("\nNext step: copy data/ folder to your Netlify repo and push.\n")

if __name__ == '__main__':
    main()
