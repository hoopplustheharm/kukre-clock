import os
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote

BOT_TOKEN  = os.environ["DISCORD_BOT_TOKEN"]
CHANNEL_ID = os.environ["DISCORD_CHANNEL_ID"]
MSG_ID     = os.environ.get("DISCORD_MESSAGE_ID", "").strip()

API = "https://discord.com/api/v10"
HEADERS = {
    "Authorization": f"Bot {BOT_TOKEN}",
    "Content-Type":  "application/json",
}

# Used to fetch when this file was last modified — that timestamp becomes the "MotD set at" moment.
GITHUB_REPO = "hoopplustheharm/kukre-clock"
GITHUB_FILE = "update.py"   # change to "main.py" if you renamed the file

# ---- Monster of the Day (edit both when a new monster is announced, then commit) ----
MOTD_ID   = 1405
MOTD_NAME = "Tengu"
MOTD_URL  = f"https://cp.arcadia-online.org/monster/view/?id={MOTD_ID}"

# (emoji, label, IANA timezone, major cities)
ZONES = [
    ("🌴", "PST / PDT",   "America/Los_Angeles", "LA, Vancouver, Seattle"),
    ("🌵", "MST / MDT",   "America/Denver",      "Denver, Phoenix, Calgary"),
    ("🌽", "CST / CDT",   "America/Chicago",     "Chicago, Dallas, Mexico"),
    ("🗽", "EST / EDT",   "America/New_York",    "NYC, Toronto, Atlanta"),
    ("🇬🇧", "UTC / GMT",   "Etc/UTC",             "London (winter), Reykjavik"),
    ("🥖", "CET / CEST",  "Europe/Berlin",       "Berlin, Paris, Madrid"),
    ("🇰🇷", "KST",         "Asia/Seoul",          "Seoul, Busan"),
    ("🍣", "JST",         "Asia/Tokyo",          "Tokyo, Osaka"),
    ("🦘", "AEST / AEDT", "Australia/Sydney",    "Sydney, Melbourne"),
]

PLAYERS_COL_WIDTH = 24


def get_users_for_reaction(emoji):
    encoded = quote(emoji, safe="")
    url = f"{API}/channels/{CHANNEL_ID}/messages/{MSG_ID}/reactions/{encoded}"
    users, after = [], None
    while True:
        params = {"limit": 100}
        if after:
            params["after"] = after
        r = requests.get(url, headers=HEADERS, params=params)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        batch = r.json()
        users.extend(u for u in batch if not u.get("bot"))
        if len(batch) < 100:
            break
        after = batch[-1]["id"]
    return users


def wrap_names(names, max_width):
    """Pack names into lines no wider than `max_width` chars."""
    if not names:
        return ["—"]
    lines, current = [], ""
    for i, name in enumerate(names):
        token = name + ("," if i < len(names) - 1 else "")
        candidate = f"{current} {token}".strip()
        if current and len(candidate) > max_width:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def build_table(now_utc, reactions):
    rows = []
    for emoji, label, tz, cities in ZONES:
        t = now_utc.astimezone(ZoneInfo(tz))
        time_s = t.strftime("%a %b %d %H:%M")
        users = reactions.get(emoji, [])
        names = [u.get("global_name") or u["username"] for u in users]
        rows.append((time_s, label, cities, names))

    tw = max(len("TIME"),   max(len(r[0]) for r in rows))
    zw = max(len("ZONE"),   max(len(r[1]) for r in rows))
    cw = max(len("CITIES"), max(len(r[2]) for r in rows))
    pw = PLAYERS_COL_WIDTH

    lines = [
        f"{'TIME':<{tw}}  {'ZONE':<{zw}}  {'CITIES':<{cw}}  PLAYERS",
        f"{'─'*tw}  {'─'*zw}  {'─'*cw}  {'─'*pw}",
    ]
    pad_empty = f"{'':<{tw}}  {'':<{zw}}  {'':<{cw}}  "
    for time_s, zone_s, cities_s, names in rows:
        chunks = wrap_names(names, pw)
        lines.append(f"{time_s:<{tw}}  {zone_s:<{zw}}  {cities_s:<{cw}}  {chunks[0]}")
        for cont in chunks[1:]:
            lines.append(f"{pad_empty}{cont}")
    return "```\n" + "\n".join(lines) + "\n```"


def get_last_commit_time():
    """Return the UTC datetime of the most recent commit that touched this file on main."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/commits"
    params = {"path": GITHUB_FILE, "sha": "main", "per_page": 1}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    commits = r.json()
    if not commits:
        return None
    iso = commits[0]["commit"]["committer"]["date"]  # e.g. "2026-09-04T00:03:12Z"
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def build_content(reactions):
    now = datetime.now(timezone.utc)
    table = build_table(now, reactions)
    legend = " · ".join(f"{e} {l.split(' / ')[0]}" for e, l, *_ in ZONES)
    server_time = now.strftime("%a %b %d, %H:%M UTC")

    lines = []
    try:
        set_at = get_last_commit_time()
    except Exception as e:
        print(f"Warning: couldn't fetch last
