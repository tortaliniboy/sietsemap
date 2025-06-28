"""
Builds an interactive HTML map (“Sietsemap”) of every NYC restaurant
mentioned in Robert Sietsema’s Substack posts.

• Scrapes the RSS feed  →  pulls newest posts
• Heuristically extracts {name, address, blurb}
• Geocodes each address  →  latitude / longitude
• Builds a Folium map     →  public/index.html
"""

import re, os, json, datetime, html, time, feedparser
from pathlib import Path
from bs4 import BeautifulSoup
import folium
from geopy.geocoders import Nominatim

RSS_URL        = "https://robertsietsema.substack.com/feed"
CACHE_FILE     = Path("restaurants.json")           # stores all seen spots
OUTPUT_HTML    = Path("public/index.html")
USER_AGENT     = "sietsemap-bot/0.1 (github action)"

# ---------- helpers ---------------------------------------------------------
def fetch_feed():
    return feedparser.parse(RSS_URL)

def pull_posts(feed):
    for entry in feed.entries:
        yield {
            "title":   entry.get("title", "Untitled"),
            "date":    entry.get("published", ""),
            "content": entry.get("content", [{}])[0].get("value", "")
        }

ADDRESS_RX = re.compile(
    r"\b(\d{1,5}[A-Z]?\s+[\w\s.,'&/-]+?,\s*(?:Brooklyn|Bronx|Queens|Manhattan|"
    r"Staten Island|New York|NYC)[\w\s.,'-]*?(?:NY)?\s*\d{5})",
    re.I)

def extract_restaurants(post):
    soup = BeautifulSoup(post["content"], "html.parser")
    text = soup.get_text("\n")
    found = []
    for match in ADDRESS_RX.finditer(text):
        address = html.unescape(match.group(1)).strip()
        # crude name = line just above the address
        before   = text[:match.start()].splitlines()
        name_line= before[-1].strip() if before else "Unnamed"
        blurb    = "…".join(text[match.start(): match.end()+140].splitlines())[:260]
        found.append({"name": name_line, "address": address, "blurb": blurb})
    return found

def load_cache():
    if CACHE_FILE.exists():
        with CACHE_FILE.open() as f:
            return json.load(f)
    return []

def save_cache(data):
    with CACHE_FILE.open("w") as f:
        json.dump(data, f, indent=2)

def geocode(addr, geocoder):
    try:
        loc = geocoder.geocode(addr, exactly_one=True, timeout=15)
        if loc:
            return (loc.latitude, loc.longitude)
    except Exception:
        pass
    return None

# ---------- main workflow ---------------------------------------------------
def main():
    geocoder = Nominatim(user_agent=USER_AGENT)
    known    = load_cache()
    seen_addrs = {r["address"] for r in known}

    # 1. scrape new posts
    for post in pull_posts(fetch_feed()):
        for r in extract_restaurants(post):
            if r["address"] in seen_addrs:           # already stored
                continue
            coords = geocode(r["address"], geocoder)
            if not coords:
                continue                             # skip if geocoding fails
            r["lat"], r["lon"] = coords
            r["date_added"]   = datetime.date.today().isoformat()
            known.append(r)
            seen_addrs.add(r["address"])
            time.sleep(1)                            # gentle on Nominatim

    # 2. save updated cache
    save_cache(known)

    # 3. build map
    m = folium.Map(location=[40.73, -73.94], zoom_start=11,
                   tiles="CartoDB positron")

    for r in known:
        popup_html = (
            f"<b>{html.escape(r['name'])}</b><br>"
            f"{html.escape(r['address'])}<br><hr style='margin:4px'>"
            f"{html.escape(r['blurb'])}"
        )
        folium.Marker(
            location=[r["lat"], r["lon"]],
            popup=popup_html,
            tooltip=r["name"],
            icon=folium.Icon(color="darkblue", icon="cutlery", prefix="fa")
        ).add_to(m)

    OUTPUT_HTML.parent.mkdir(exist_ok=True)
    m.save(str(OUTPUT_HTML))
    print(f"Map rebuilt ➜ {OUTPUT_HTML}")

if __name__ == "__main__":
    main()
