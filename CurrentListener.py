import os
import json
import time
import requests
import pandas as pd
import pytz
import xml.etree.ElementTree as ET
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Suppress insecure certificate warnings
from urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Configuration
TIMEZONE = pytz.timezone("America/Guayaquil")
DB_FILE = "radio_listeners_history.csv"

STATIONS = [
    {"id": 1, "name": "Rumba", "url": "https://radio.kapchosting.com:7052/status-json.xsl", "type": "icecast_json"},
    {"id": 2, "name": "88-5", "url": "https://radio.kapchosting.com:7055/status-json.xsl", "type": "icecast_json"},
    {"id": 3, "name": "Continental", "url": "https://radio.kapchosting.com:7056/status-json.xsl", "type": "icecast_json"},
    {"id": 4, "name": "Amor", "url": "https://rr5100.globalhost1.com:8168/stats", "type": "shoutcast_xml"},
    {"id": 5, "name": "Alegria", "url": "https://rr5100.globalhost1.com:8156/stats", "type": "shoutcast_xml"},
    {"id": 6, "name": "Caracol", "url": "https://rr5100.globalhost1.com:8122/stats", "type": "shoutcast_xml"},
    {"id": 7, "name": "Xtrema", "url": "https://radiostreaming.pro:7213/stats", "type": "shoutcast_xml"},
    {"id": 8, "name": "Centro", "url": "https://dattavolt.com/8080/stats", "type": "shoutcast_xml"},
    {"id": 9, "name": "Ambato", "url": "https://rr5100.globalhost1.com:8140/stats", "type": "shoutcast_xml"},
    {"id": 10, "name": "Retumba", "url": "https://panel.innovatestream.pe:10839/stats", "type": "shoutcast_xml"},
    {"id": 11, "name": "Turbo", "url": "https://streamingecuador.com/stream/radioturboambato", "type": "metadata_only"},
    {"id": 12, "name": "Bandida", "url": "https://sonicpanel.zonaradio.net:8294/stats", "type": "shoutcast_xml"},
    {"id": 13, "name": "Paz y Bien", "url": "https://s7.myradiostream.com:59906/stats", "type": "shoutcast_xml"},
    {"id": 14, "name": "Celeste", "url": "https://streamingecuador.com:9024/status-json.xsl", "type": "icecast_json"},
]

def build_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def parse_icecast_json(content):
    try:
        data = json.loads(content)
    except Exception:
        return None

    stats = data.get("icestats", {})
    sources = stats.get("source", [])

    if isinstance(sources, dict):
        sources = [sources]

    if not isinstance(sources, list):
        return None

    total = 0
    for src in sources:
        if not isinstance(src, dict):
            continue
        try:
            total += int(src.get("listeners", 0))
        except (TypeError, ValueError):
            continue

    return total

def parse_shoutcast_xml(content):
    try:
        root = ET.fromstring(content.strip())
    except ET.ParseError:
        return None

    for tag in ["CURRENTLISTENERS", "currentlisteners", "listeners", "LISTENERS"]:
        for elem in root.iter(tag):
            if elem.text is None:
                continue
            try:
                return int(str(elem.text).strip())
            except ValueError:
                continue

    return None

def parse_response(content, station_type):
    if station_type == "icecast_json":
        return parse_icecast_json(content)
    elif station_type == "shoutcast_xml":
        return parse_shoutcast_xml(content)
    else:
        return None

def fetch_station_stats(station, session):
    timestamp = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ListenerMonitor/1.0"
    }

    if station["type"] == "metadata_only":
        return {
            "Timestamp": timestamp,
            "Station ID": station["id"],
            "Radio Station": station["name"],
            "Current Listeners": None,
            "Stream Status": "Unavailable",
            "Collection Error": "Direct stream URL lacks stats endpoint"
        }

    try:
        response = session.get(
            station["url"],
            headers=headers,
            timeout=12,
            verify=False
        )

        if response.status_code != 200:
            return {
                "Timestamp": timestamp,
                "Station ID": station["id"],
                "Radio Station": station["name"],
                "Current Listeners": None,
                "Stream Status": "Unavailable",
                "Collection Error": f"HTTP {response.status_code}"
            }

        listeners = parse_response(response.text, station["type"])
        if listeners is None:
            return {
                "Timestamp": timestamp,
                "Station ID": station["id"],
                "Radio Station": station["name"],
                "Current Listeners": None,
                "Stream Status": "Unavailable",
                "Collection Error": "Could not parse listener value"
            }

        return {
            "Timestamp": timestamp,
            "Station ID": station["id"],
            "Radio Station": station["name"],
            "Current Listeners": int(listeners),
            "Stream Status": "Online",
            "Collection Error": ""
        }

    except requests.RequestException as exc:
        return {
            "Timestamp": timestamp,
            "Station ID": station["id"],
            "Radio Station": station["name"],
            "Current Listeners": None,
            "Stream Status": "Unavailable",
            "Collection Error": str(exc)
        }

def save_history(df):
    os.makedirs(os.path.dirname(DB_FILE) or ".", exist_ok=True)
    if not os.path.exists(DB_FILE):
        df.to_csv(DB_FILE, index=False)
    else:
        df.to_csv(DB_FILE, mode="a", header=False, index=False)

def print_report(df):
    df = df.copy()
    df["Current Listeners"] = pd.to_numeric(df["Current Listeners"], errors="coerce")

    valid = df.dropna(subset=["Current Listeners"]).copy()
    total_listeners = int(valid["Current Listeners"].sum()) if not valid.empty else 0
    avg_listeners = round(float(valid["Current Listeners"].mean()), 2) if not valid.empty else 0

    online_count = int((df["Stream Status"] == "Online").sum())
    unavailable_count = int((df["Stream Status"] == "Unavailable").sum())

    if not valid.empty:
        highest_row = valid.loc[valid["Current Listeners"].idxmax()]
        lowest_row = valid.loc[valid["Current Listeners"].idxmin()]
        highest_station = highest_row["Radio Station"]
        highest_listeners = int(highest_row["Current Listeners"])
        lowest_station = lowest_row["Radio Station"]
        lowest_listeners = int(lowest_row["Current Listeners"])
    else:
        highest_station = "N/A"
        highest_listeners = "N/A"
        lowest_station = "N/A"
        lowest_listeners = "N/A"

    display_df = df.sort_values(
        by="Current Listeners",
        ascending=False,
        na_position="last"
    )

    now_local = datetime.now(TIMEZONE)
    date_str = now_local.strftime("%Y-%m-%d")
    time_str = now_local.strftime("%H:%M")

    print("HOURLY RADIO LISTENER REPORT (Sorted by Audience)\n")
    print(f"Date: {date_str}")
    print(f"Time: {time_str}")
    print(f"Time Zone: America/Guayaquil\n")

    print(f"{'Radio Station':<20} {'Current Listeners':<20} {'Status':<15} {'Contribution':<15}")
    print("-" * 75)

    for _, row in display_df.iterrows():
        listeners = row["Current Listeners"]
        status = row["Stream Status"]

        if pd.isna(listeners):
            contribution = "N/A"
        elif total_listeners > 0:
            contribution = f"{(listeners / total_listeners) * 100:.2f}%"
        else:
            contribution = "N/A"

        print(f"{row['Radio Station']:<20} {str(listeners):<20} {status:<15} {contribution:<15}")

    print("-" * 75)
    print(f"{'TOTAL':<20} {total_listeners:<20}\n")

    print("METRICS SUMMARY")
    print(f"- Average listeners (active stations): {avg_listeners}")
    print(f"- Highest Listener Station: {highest_station} ({highest_listeners})")
    print(f"- Lowest Listener Station: {lowest_station} ({lowest_listeners})")
    print(f"- Stations Online: {online_count} / Stations Unavailable: {unavailable_count}")

def main():
    session = build_session()
    results = []

    for station in STATIONS:
        results.append(fetch_station_stats(station, session))
        time.sleep(0.2)  # small pacing to avoid hammering endpoints

    df = pd.DataFrame(results)
    save_history(df)

    print_report(df)

if __name__ == "__main__":
    main()
