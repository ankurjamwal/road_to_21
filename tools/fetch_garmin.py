"""Download your running activities from Garmin's Personal API.

Usage:
  python fetch_garmin.py probe                 show which fields Garmin offers (names only, no values)
  python fetch_garmin.py [YYYY-MM-DD] [--details N] [--no-weather]

The second form saves garmin_runs.json. For your newest N runs (default 30) it also fetches the
route, and it looks up the weather at the start of each run on Open-Meteo, a free weather service.
That lookup sends the run's start coordinates and date to Open-Meteo; use --no-weather to skip it.

The Garmin key is read from the GARMIN_PERSONAL_API_KEY environment variable and is never written
to disk. Not yet tested against a live Garmin account beyond the probe.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:  # use the operating system's certificate store when the optional package is installed
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

BASE = "https://personal.connectapi.garmin.com"
TOKEN_URL = BASE + "/personalapitoken-service/personal-api/personal-api-key/token"
LIST_PATH = "/activitylist-service/activities/search/activities"
PAGE_SIZE = 100
MAX_ACTIVITIES = 1000
DEFAULT_DETAILS = 30
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_WORDS = ((0, "Clear"), (3, "Partly cloudy"), (48, "Fog"), (57, "Drizzle"), (67, "Rain"),
                 (77, "Snow"), (82, "Showers"), (86, "Snow showers"), (99, "Thunderstorm"))


def request(url, headers, method="GET"):
    """Send one request. Returns (status, body text); status 0 means Garmin could not be reached."""
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8", "replace")
    except urllib.error.URLError as err:
        return 0, str(err.reason)


def call(url, headers, method="GET"):
    """Like request(), but stops the script with a readable message unless Garmin answers 200."""
    status, body = request(url, headers, method)
    if status == 0:
        sys.exit(f"Could not reach Garmin: {body}")
    if status != 200:
        sys.exit(f"Garmin answered HTTP {status} for {url.split('?')[0]}: {body[:300]}")
    return body


def get_token(api_key):
    """Swap the long-lived key for a 24-hour access token."""
    body = call(TOKEN_URL, {"Authorization": f"ApiKey {api_key}"}, method="POST")
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()  # the token came back as plain text
    if isinstance(data, dict):
        for name in ("access_token", "accessToken", "token"):
            if data.get(name):
                return data[name]
        sys.exit("The token reply had no access token. Fields: " + ", ".join(data))
    return str(data)


def list_page(headers, start, limit, start_date=None):
    """Fetch one page of the activity list, newest first."""
    params = {"start": start, "limit": limit}
    if start_date:
        params["startDate"] = start_date
    url = BASE + LIST_PATH + "?" + urllib.parse.urlencode(params)
    batch = json.loads(call(url, headers) or "[]")
    if not isinstance(batch, list):
        sys.exit("Expected a list of activities but got something else.")
    return batch


def fetch_activities(headers, start_date=None):
    """Page through the whole activity list."""
    items, start = [], 0
    while len(items) < MAX_ACTIVITIES:
        batch = list_page(headers, start, PAGE_SIZE, start_date)
        items.extend(batch)
        print(f"Fetched {len(items)} activities")
        if len(batch) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    return items


def is_run(activity):
    """True when the activity's type mentions running (covers trail running and treadmill)."""
    return "run" in json.dumps(activity.get("activityType", "")).lower()


def extract_route(details, max_points=250):
    """Pull the GPS track out of the details reply as [[lat, lon], ...], thinned to max_points."""
    geo = details.get("geoPolylineDTO") if isinstance(details, dict) else None
    points = (geo or {}).get("polyline") or []
    route = [[p["lat"], p["lon"]] for p in points if isinstance(p, dict) and "lat" in p and "lon" in p]
    if len(route) > max_points:
        step = -(-len(route) // max_points)
        route = route[::step] + [route[-1]]
    return route


def describe_weather(code):
    """Turn an Open-Meteo weather code into a short word."""
    for limit, word in WEATHER_WORDS:
        if code <= limit:
            return word
    return "Mixed"


def fetch_weather(lat, lon, start_local):
    """Temperature and conditions at the run's start hour, or None if Open-Meteo has nothing."""
    day, hour = start_local[:10], start_local[:13].replace(" ", "T") + ":00"
    base = {"latitude": round(lat, 3), "longitude": round(lon, 3),
            "hourly": "temperature_2m,weather_code", "timezone": "auto"}
    for url, extra in ((ARCHIVE_URL, {"start_date": day, "end_date": day}),
                       (FORECAST_URL, {"past_days": 7, "forecast_days": 1})):
        status, body = request(url + "?" + urllib.parse.urlencode({**base, **extra}), {})
        if status != 200:
            continue
        try:
            hourly = json.loads(body)["hourly"]
            i = hourly["time"].index(hour)
            temp, code = hourly["temperature_2m"][i], hourly["weather_code"][i]
        except (ValueError, KeyError, IndexError, json.JSONDecodeError):
            continue
        if temp is not None and code is not None:
            return {"tempC": round(temp), "summary": f"{describe_weather(code)}, {round(temp)}\u00b0C"}
    return None


def enrich(headers, activities, details_count, with_weather):
    """Add _route and _weather to the newest runs. Reports what it found."""
    runs = [a for a in activities if is_run(a)][:details_count]
    routes = weathers = 0
    for number, activity in enumerate(runs, 1):
        status, body = request(f"{BASE}/activity-service/activity/{activity.get('activityId')}/details", headers)
        if status == 200:
            try:
                route = extract_route(json.loads(body))
            except json.JSONDecodeError:
                route = []
            if route:
                activity["_route"] = route
                routes += 1
        lat, lon, start = activity.get("startLatitude"), activity.get("startLongitude"), activity.get("startTimeLocal")
        if with_weather and lat is not None and lon is not None and start:
            weather = fetch_weather(lat, lon, start)
            if weather:
                activity["_weather"] = weather
                weathers += 1
            time.sleep(0.3)  # be polite to the free weather service
        print(f"Enriched {number}/{len(runs)} runs")
    print(f"Routes found for {routes} runs, weather for {weathers} runs.")
    if runs and not routes:
        print("No route was found. Run the probe and send me the output so I can adjust the route reader.")


def key_paths(value, prefix="", depth=0):
    """List every field name with its type, never the values."""
    out = []
    if isinstance(value, dict):
        for key, val in value.items():
            path = f"{prefix}.{key}" if prefix else key
            out.append(f"{path} ({type(val).__name__})")
            if depth < 3:
                out += key_paths(val, path, depth + 1)
    elif isinstance(value, list) and value:
        out += key_paths(value[0], prefix + "[]", depth + 1)
    return out


def probe(headers):
    """Show which fields and per-run endpoints Garmin offers. Prints names and status codes only."""
    batch = list_page(headers, 0, 20)
    print(f"The list returned {len(batch)} activities.")
    if not batch:
        return
    print("\nFields of the newest activity (names and types only):")
    for line in key_paths(batch[0]):
        print("  " + line)
    runs = [a for a in batch if "run" in json.dumps(a.get("activityType", "")).lower()]
    activity_id = (runs or batch)[0].get("activityId")
    if activity_id is None:
        print("\nNo activityId field found, so the per-run checks were skipped.")
        return
    print("\nPer-run endpoints (HTTP status; {id} stands for the activity id):")
    for path in ("/activity-service/activity/{id}", "/activity-service/activity/{id}/splits",
                 "/activity-service/activity/{id}/details", "/activity-service/activity/{id}/weather",
                 "/download-service/files/activity/{id}"):
        status, body = request(BASE + path.replace("{id}", str(activity_id)), headers)
        print(f"  {status}  {path}")
        if status == 200 and body[:1] in "{[":
            try:
                data = json.loads(body)
                for line in key_paths(data)[:200]:
                    print("      " + line)
                names = [d.get("key") for d in data.get("metricDescriptors", []) if isinstance(d, dict)]
                if names:
                    print("      per-second metric names: " + ", ".join(str(n) for n in names))
            except (json.JSONDecodeError, AttributeError):
                print("      (not JSON)")
        elif status == 200:
            print(f"      ({len(body)} characters of non-JSON data, probably a file)")


def main():
    api_key = os.environ.get("GARMIN_PERSONAL_API_KEY")
    if not api_key:
        sys.exit("Set GARMIN_PERSONAL_API_KEY first.")
    args = sys.argv[1:]
    headers = {"Authorization": f"Bearer {get_token(api_key)}", "Accept": "application/json"}
    if args[:1] == ["probe"]:
        probe(headers)
        return
    with_weather = "--no-weather" not in args
    details_count = DEFAULT_DETAILS
    if "--details" in args:
        try:
            details_count = int(args[args.index("--details") + 1])
        except (IndexError, ValueError):
            sys.exit("Use --details followed by a number, for example --details 10.")
    start_date = next((a for a in args if len(a) == 10 and a[4] == "-" and a[7] == "-"), None)
    activities = fetch_activities(headers, start_date)
    enrich(headers, activities, details_count, with_weather)
    with open("garmin_runs.json", "w", encoding="utf-8") as out:
        json.dump(activities, out, indent=1)
    print(f"Saved {len(activities)} activities to garmin_runs.json")


if __name__ == "__main__":
    main()
