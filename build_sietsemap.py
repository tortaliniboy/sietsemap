import re
import html
import time
import json
import feedparser
import folium
import traceback
import io
from pathlib import Path
from bs4 import BeautifulSoup
from geopy.geocoders import Nominatim
import spacy

# Load spaCy English model (make sure to install as above)
nlp = spacy.load("en_core_web_sm")

RSS_URL = "https://robertsietsema.substack.com/feed"
CACHE_FILE = Path("restaurants.json")
OUTPUT_HTML = Path("public/index.html")
USER_AGENT = "sietsemap-bot/0.1 (github action)"

# Multiple regex patterns for flexible address extraction
ADDRESS_PATTERNS = [
    re.compile(r"\d{1,5}[A-Z]?\s+[\w\s.,'&/-]+,\s*(Brooklyn|Bronx|Queens|Manhattan|Staten Island|New York|NYC)[^,]*\d{5}", re.I),
    re.compile(r"\d{1,5}[A-Z]?\s+[\w\s.,'&/-]+,\s*(Brooklyn|Bronx|Queens|Manhattan|Staten Island|New York|NYC)", re.I),
    re.compile(r"[\w\s.'/-]+&[\w\s.'/-]+,\s*(Brooklyn|Bronx|Queens|Manhattan|Staten Island|New York|NYC)", re.I),
    re.compile(r"\d{1,5}[A-Z]?\s+[\w\s.,'&/-]+", re.I),
]

def fetch_feed():
    return feedparser.parse(RSS_URL)

def pull_posts(feed):
    for entry in feed.entries:
        yield {
            "title": entry.get("title", "Untitled"),
            "date": entry.get("published", ""),
            "content": entry.get("content", [{}])[0].get("value", "")
        }

def extract_restaurants_flexible(post):
    soup = BeautifulSoup(post["content"], "html.parser")
    text = soup.get_text("\n")
    found = []

    # Regex extraction
    for pattern in ADDRESS_PATTERNS:
        for match in pattern.finditer(text):
            address = match.group().strip()
            before = text[:match.start()].splitlines()
            name_line = before[-1].strip() if before else "Unnamed"
            blurb = "…".join(text[match.start(): match.end()+140].splitlines())[:260]
            found.append({"name": name_line, "address": address, "blurb": blurb})

    # spaCy NER fallback
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ in ("ORG", "FAC", "GPE", "LOC"):
            if re.search(r'\d{1,5}', ent.text) or any(b in ent.text for b in ["Brooklyn","Bronx","Queens","Manhattan","Staten Island","New York","NYC"]):
                found.append({"name": ent.text, "address": ent.text, "blurb": ""})

    # Remove duplicates by address
    seen = set()
    unique = []
    for r in found:
        if r["address"] not in seen:
            unique.append(r)
            seen.add(r["address"])
    return unique

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

def main():
    geocoder = Nominatim(user_agent=USER_AGENT)
    known = load_cache()
    seen_addrs = {r["address"] for r in known}

    feed = fetch_feed()
    new_found = 0

    for post in pull_posts(feed):
        try:
            extracted = extract_restaurants_flexible(post)
        except Exception:
            print(f"Error extracting restaurants from post: {post['title']}")
            traceback.print_exc()
            continue

        for r in extracted:
            if r["address"] in seen_addrs:
                continue
            coords = geocode(r["address"], geocoder)
            if not coords:
                continue
            r["lat"], r["lon"] = coords
            r["date_added"] = post["date"] or ""
            known.append(r)
            seen_addrs.add(r["address"])
            new_found += 1
            time.sleep(1)  # be gentle on geocoder

    print(f"Found {new_found} new restaurants.")

    save_cache(known)

    # Build map
    m = folium.Map(location=[40.73, -73.94], zoom_start=11, tiles="CartoDB positron")

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
    print(f"Map saved ➜ {OUTPUT_HTML}")

if __name__ == "__main__":
    main()
