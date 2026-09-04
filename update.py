import os
import time
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote

BOT_TOKEN  = os.environ["DISCORD_BOT_TOKEN"]
CHANNEL_ID = os.environ["DISCORD_CHANNEL_ID"]
GUILD_ID   = os.environ["DISCORD_GUILD_ID"]
MSG_ID     = os.environ.get("DISCORD_MESSAGE_ID", "").strip()

API = "https://discord.com/api/v10"
HEADERS = {
    "Authorization": f"Bot {BOT_TOKEN}",
    "Content-Type":  "application/json",
}

GITHUB_REPO = "hoopplustheharm/kukre-clock"
GITHUB_FILE = "update.py"

# ---- Monster of the Day (edit both when a new monster is announced, then commit) ----
MOTD_ID   = 1405
MOTD_NAME = "Tengu"
MOTD_URL  = f"https://cp.arcadia-online.org/monster/view/?id={MOTD_ID}"

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

PLAYERS_COL_WIDTH = 32   # wider now to accommodate "Nick (@handle)"


def discord_get(url, params=None, max_retries=3):
    for attempt in range(max_retries):
        r = requests.get(url, headers=HEADERS, params=params)
        if r.status_code == 429:
            wait = float(r.headers.get("Retry-After", "1"))
            print(f"Rate limited; sleeping {wait:.1f}s then retrying")
            time.sleep(wait + 0.5)
            continue
        return r
    return r


def get_message_reactions_summary():
    url = f"{API}/channels/{CHANNEL_ID}/messages/{MSG_ID}"
    r = discord_get(url)
    r.raise_for_status()
    msg = r.json()
    return {reaction["emoji"]["name"]: reaction["count"] for reaction in msg.get("reactions", [])}


def get_users_for_reaction(emoji):
    encoded = quote(emoji, safe="")
    url = f"{API}/channels/{CHANNEL_ID}/messages/{MSG_ID}/reactions/{encoded}"
    users, after = [], None
    while True:
        params = {"limit": 100}
        if after:
            params["after"] = after
        r = discord_get(url, params=params)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        batch = r.json()
        users.extend(u for u in batch if not u.get("bot"))
        if len(batch) < 100:
            break
        after = batch[-1]["id"]
    return users


def get_guild_nickname(user_id):
    """Return the user's server nickname, or None if unset / not in guild."""
    url = f"{API}/guilds/{GUILD_ID}/members/{user_id}"
    r = discord_get(url)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json().get("nick")  # None if no nickname set


def format_name(user):
    """Return 'Nickname (@handle)' if a server nickname exists, else just the display name."""
    handle = user["username"]
    nick = get_guild_nickname(user["id"])
    if nick:
        return f"{nick} (@{handle})"
    display = user.get("global_name") or handle
    return display


def wrap_names(names, max_width):
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
    
def utc_offset_str(dt):
    """Format a timezone-aware datetime's UTC offset as 'UTC+9' or 'UTC-4:30'."""
    offset = dt.utcoffset()
    total_min = int(offset.total_seconds() / 60)
    sign = "+" if total_min >= 0 else "-"
    hours, mins = divmod(abs(total_min), 60)
    if mins:
        return f"UTC{sign}{hours}:{mins:02d}"
    return f"UTC{sign}{hours}"

def build_table(now_utc, reactions):
    active_zones = [(e, l, tz, c) for (e, l, tz, c) in ZONES if reactions.get(e)]

    if not active_zones:
        return "```\n(No zones yet — react below to add yourself.)\n```"

    rows = []
    for emoji, label, tz, cities in active_zones:
        t = now_utc.astimezone(ZoneInfo(tz))
        time_s = t.strftime("%a %b %d %H:%M")
        offset_s = utc_offset_str(t)
        users = reactions.get(emoji, [])
        names = [format_name(u) for u in users]
        rows.append((time_s, offset_s, label, cities, names))

    tw = max(len("TIME"),   max(len(r[0]) for r in rows))
    uw = max(len("UTC"),    max(len(r[1]) for r in rows))
    zw = max(len("ZONE"),   max(len(r[2]) for r in rows))
    cw = max(len("CITIES"), max(len(r[3]) for r in rows))
    pw = PLAYERS_COL_WIDTH

    # Server time banner row — a full-width single-cell row above the header.
    server_time_str = now_utc.strftime("%a %b %d %H:%M") + ", UTC+0"
    total_width = tw + uw + zw + cw + pw + 8  # 4 gaps of 2 spaces = 8
    banner_text = f">>> SERVER TIME: {server_time_str} <<<"
    banner = banner_text.center(total_width)

    lines = [
        banner,
        "─" * total_width,
        f"{'TIME':<{tw}}  {'UTC':<{uw}}  {'ZONE':<{zw}}  {'CITIES':<{cw}}  PLAYERS",
        f"{'─'*tw}  {'─'*uw}  {'─'*zw}  {'─'*cw}  {'─'*pw}",
    ]
    pad_empty = f"{'':<{tw}}  {'':<{uw}}  {'':<{zw}}  {'':<{cw}}  "
    for time_s, off_s, zone_s, cities_s, names in rows:
        chunks = wrap_names(names, pw)
        lines.append(f"{time_s:<{tw}}  {off_s:<{uw}}  {zone_s:<{zw}}  {cities_s:<{cw}}  {chunks[0]}")
        for cont in chunks[1:]:
            lines.append(f"{pad_empty}{cont}")
    return "```\n" + "\n".join(lines) + "\n```"


def get_last_commit_time():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/commits"
    params = {"path": GITHUB_FILE, "sha": "main", "per_page": 1}
    headers = {}
    token = os.environ.get("GITHUB_API_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(url, params=params, headers=headers, timeout=10)
    r.raise_for_status()
    commits = r.json()
    if not commits:
        return None
    iso = commits[0]["commit"]["committer"]["date"]
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def build_content(reactions):
    now = datetime.now(timezone.utc)
    table = build_table(now, reactions)
    legend = " · ".join(f"{e} {l}" for e, l, *_ in ZONES)

    lines = ["⠀"]  # braille blank U+2800 = leading gap

    try:
        set_at = get_last_commit_time()
    except Exception as e:
        print(f"Warning: couldn't fetch last commit time: {e}")
        set_at = None

    if set_at is not None:
        next_midnight_utc = (set_at + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if now < next_midnight_utc:
            lines += [
                f"## 🐉 Monster of the Day: [{MOTD_NAME}]({MOTD_URL})",
                "",
            ]

    lines += [
        table,
        f"React to add yourself:  {legend}",
        f"_Last refresh: <t:{int(now.timestamp())}:R>_",
    ]
    return "\n".join(lines)


def post_message(content):
    r = requests.post(f"{API}/channels/{CHANNEL_ID}/messages",
                      headers=HEADERS, json={"content": content})
    r.raise_for_status()
    return r.json()


def edit_message(content):
    r = requests.patch(f"{API}/channels/{CHANNEL_ID}/messages/{MSG_ID}",
                       headers=HEADERS, json={"content": content})
    r.raise_for_status()


def seed_reactions(message_id):
    for emoji, *_ in ZONES:
        encoded = quote(emoji, safe="")
        url = f"{API}/channels/{CHANNEL_ID}/messages/{message_id}/reactions/{encoded}/@me"
        r = requests.put(url, headers=HEADERS)
        if not r.ok:
            print(f"Warning: couldn't seed {emoji}: {r.status_code} {r.text}")


if not MSG_ID:
    msg = post_message(build_content({e: [] for e, *_ in ZONES}))
    seed_reactions(msg["id"])
    print("=" * 60)
    print(f"MESSAGE_ID = {msg['id']}")
    print("Copy this ID into the DISCORD_MESSAGE_ID secret, then pin the message.")
    print("=" * 60)
else:
    counts = get_message_reactions_summary()
    reactions = {}
    for emoji, *_ in ZONES:
        if counts.get(emoji, 0) > 1:  # >1 because bot's own seed counts as 1
            reactions[emoji] = get_users_for_reaction(emoji)
        else:
            reactions[emoji] = []
    edit_message(build_content(reactions))
    print(f"Updated message {MSG_ID}")
