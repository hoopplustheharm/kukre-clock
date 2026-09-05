import os
import time
import asyncio
import requests
import discord

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
MOTD_ID   = 1317
MOTD_NAME = "Fur Seal"
MOTD_URL  = f"https://cp.arcadia-online.org/monster/view/?id={MOTD_ID}"

ZONES = [
    ("🌴", "Pacific",         "America/Los_Angeles",             "LA, Vancouver, Seattle, Portland"),
    ("🌵", "Mountain",        "America/Denver",                  "Denver, Phoenix, Calgary"),
    ("🌽", "Central",         "America/Chicago",                 "Chicago, Dallas, Mexico City"),
    ("🗽", "Eastern",         "America/New_York",                "NYC, Toronto, Atlanta, Miami"),
    ("🇧🇷", "Brazil",          "America/Sao_Paulo",               "São Paulo, Rio"),
    ("🇦🇷", "Argentina",       "America/Argentina/Buenos_Aires",  "Buenos Aires"),
    ("🇬🇧", "UK / Ireland",    "Europe/London",                   "London, Dublin, Lisbon"),
    ("🥖", "Central Europe",  "Europe/Berlin",                   "Berlin, Paris, Madrid, Rome"),
    ("🇬🇷", "Eastern Europe",  "Europe/Athens",                   "Athens, Helsinki, Bucharest"),
    ("🇹🇷", "Turkey",          "Europe/Istanbul",                 "Istanbul, Ankara"),
    ("🇷🇺", "Moscow",          "Europe/Moscow",                   "Moscow, St. Petersburg"),
    ("🇮🇳", "India",           "Asia/Kolkata",                    "Delhi, Mumbai, Bangalore"),
    ("🇸🇬", "SE Asia",         "Asia/Singapore",                  "Singapore, KL, Manila, HK"),
    ("🇨🇳", "China",           "Asia/Shanghai",                   "Beijing, Shanghai, Taipei"),
    ("🇰🇷", "Korea",           "Asia/Seoul",                      "Seoul, Busan"),
    ("🍣", "Japan",           "Asia/Tokyo",                      "Tokyo, Osaka"),
    ("🇦🇺", "East Australia",  "Australia/Sydney",                "Sydney, Melbourne, Brisbane"),
    ("🇳🇿", "New Zealand",     "Pacific/Auckland",                "Auckland, Wellington"),
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


MAX_NAME_LEN = 20  # truncate any single name longer than this


def truncate(s, limit):
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"

def format_name(user):
    """Return the user's best available name: server nickname > global display name > username."""
    nick = get_guild_nickname(user["id"])
    if nick:
        return truncate(nick, MAX_NAME_LEN)
    display = user.get("global_name") or user["username"]
    return truncate(display, MAX_NAME_LEN)


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

    # Sort chronologically by UTC offset (earliest local time first).
    active_zones.sort(key=lambda z: ZoneInfo(z[2]).utcoffset(now_utc))

    # Row 0 is server time itself.
    server_row = (
        now_utc.strftime("%a %b %d %H:%M"),
        "UTC+0",
        "SERVER →",
        "(Arcadia game time)",
        [],  # no players column entry
    )

    rows = [server_row]
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

    lines = [
        "",
        f"{'TIME':<{tw}}  {'UTC':<{uw}}  {'ZONE':<{zw}}  {'CITIES':<{cw}}  PLAYERS",
        f"{'─'*tw}  {'─'*uw}  {'─'*zw}  {'─'*cw}  {'─'*pw}",
    ]
    pad_empty = f"{'':<{tw}}  {'':<{uw}}  {'':<{zw}}  {'':<{cw}}  "

    for i, (time_s, off_s, zone_s, cities_s, names) in enumerate(rows):
        players_display = "—" if not names else wrap_names(names, pw)[0]
        chunks = wrap_names(names, pw) if names else [""]
        lines.append(f"{time_s:<{tw}}  {off_s:<{uw}}  {zone_s:<{zw}}  {cities_s:<{cw}}  {chunks[0]}")
        for cont in chunks[1:]:
            lines.append(f"{pad_empty}{cont}")

        # Add separator line right after the server row (row 0)
        if i == 0:
            lines.append(f"{'─'*tw}  {'─'*uw}  {'─'*zw}  {'─'*cw}  {'─'*pw}")

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
            remaining = next_midnight_utc - now
            hrs = int(remaining.total_seconds() // 3600)
            mins = int((remaining.total_seconds() % 3600) // 60)
            countdown = f"{hrs:02d}h {mins:02d}m left"
            lines += [
                f"## 🐉 Monster of the Day: [{MOTD_NAME}]({MOTD_URL})  _({countdown})_",
                "⠀",
            ]
    lines += [
        "## 🕒 Guildie Time Zones:",
        table,
        f"React to add yourself:  {legend}",
        "⠀",
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
        for attempt in range(4):
            r = requests.put(url, headers=HEADERS)
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", "1"))
                print(f"Rate limited seeding {emoji}; sleeping {wait:.1f}s")
                time.sleep(wait + 0.3)
                continue
            if not r.ok:
                print(f"Warning: couldn't seed {emoji}: {r.status_code} {r.text}")
            break
        time.sleep(0.3)  # small delay between seeds to stay under Discord's rate limit

# ============================================================
# REAL-TIME DISCORD BOT
# ============================================================

ZONE_EMOJIS = {emoji for emoji, *_ in ZONES}

CHANNEL_ID_INT = int(CHANNEL_ID)
GUILD_ID_INT = int(GUILD_ID)
MSG_ID_INT = int(MSG_ID) if MSG_ID else None


def collect_reactions():
    """
    Reads the current reactions from Discord and returns
    the users associated with every timezone emoji.
    """

    counts = get_message_reactions_summary()

    reactions = {}

    for emoji, *_ in ZONES:

        # get_users_for_reaction already removes bot users,
        # so we don't need the old > 1 check.
        if counts.get(emoji, 0) > 0:
            reactions[emoji] = get_users_for_reaction(emoji)
        else:
            reactions[emoji] = []

    return reactions


def refresh_clock(reason="unknown"):
    """
    Performs one full refresh of the Discord clock message.
    """

    try:
        reactions = collect_reactions()

        content = build_content(reactions)

        edit_message(content)

        now = datetime.now(timezone.utc)

        print(
            f"[{now.isoformat()}] "
            f"Clock updated ({reason})"
        )

    except Exception as exc:
        print(
            f"[ERROR] Failed to refresh clock "
            f"({reason}): {exc}"
        )


# ------------------------------------------------------------
# FIRST MESSAGE CREATION
# ------------------------------------------------------------

if not MSG_ID:

    msg = post_message(
        build_content(
            {emoji: [] for emoji, *_ in ZONES}
        )
    )

    seed_reactions(msg["id"])

    print("=" * 60)
    print(f"MESSAGE_ID = {msg['id']}")
    print(
        "Copy this ID into the "
        "DISCORD_MESSAGE_ID environment variable."
    )
    print("=" * 60)

    raise SystemExit(0)


# ------------------------------------------------------------
# DISCORD GATEWAY
# ------------------------------------------------------------

intents = discord.Intents.none()

intents.guilds = True
intents.guild_messages = True
intents.guild_reactions = True


client = discord.Client(
    intents=intents
)


refresh_lock = asyncio.Lock()

minute_task = None


async def refresh_async(reason):
    """
    Run the synchronous REST refresh without blocking
    the Discord Gateway connection.
    """

    async with refresh_lock:

        try:

            await asyncio.to_thread(
                refresh_clock,
                reason,
            )

        except Exception as exc:

            print(
                f"[ERROR] Async refresh failed "
                f"({reason}): {exc}"
            )


async def minute_worker():
    """
    Updates exactly at the beginning of every minute.

    Example:
        22:41:00
        22:42:00
        22:43:00
    """

    await client.wait_until_ready()

    while not client.is_closed():

        now = datetime.now(timezone.utc)

        seconds_until_next_minute = (
            60
            - now.second
            - now.microsecond / 1_000_000
        )

        await asyncio.sleep(
            seconds_until_next_minute
        )

        await refresh_async(
            "minute tick"
        )


def is_clock_reaction(payload):
    """
    Check whether a Discord reaction belongs to
    our clock message and one of our timezone emojis.
    """

    if payload.channel_id != CHANNEL_ID_INT:
        return False

    if payload.message_id != MSG_ID_INT:
        return False

    emoji = str(payload.emoji)

    if emoji not in ZONE_EMOJIS:
        return False

    return True


# ------------------------------------------------------------
# BOT READY
# ------------------------------------------------------------

@client.event
async def on_ready():

    global minute_task

    print(
        f"Logged in as "
        f"{client.user} ({client.user.id})"
    )

    print(
        f"Watching message {MSG_ID_INT}"
    )

    # Refresh immediately when the bot starts/reconnects.
    await refresh_async(
        "startup"
    )

    # Make sure only one timer exists,
    # because on_ready can run again after reconnects.
    if (
        minute_task is None
        or minute_task.done()
    ):

        minute_task = asyncio.create_task(
            minute_worker()
        )


# ------------------------------------------------------------
# REACTION ADDED
# ------------------------------------------------------------

@client.event
async def on_raw_reaction_add(payload):

    if not is_clock_reaction(payload):
        return

    # Ignore the bot's own seeded reactions.
    if (
        client.user
        and payload.user_id == client.user.id
    ):
        return

    print(
        f"Reaction added: "
        f"{payload.emoji} "
        f"by {payload.user_id}"
    )

    # Tiny delay so Discord REST state is fully consistent.
    await asyncio.sleep(0.15)

    await refresh_async(
        f"reaction added {payload.emoji}"
    )


# ------------------------------------------------------------
# REACTION REMOVED
# ------------------------------------------------------------

@client.event
async def on_raw_reaction_remove(payload):

    if not is_clock_reaction(payload):
        return

    # Ignore the bot's own seed.
    if (
        client.user
        and payload.user_id == client.user.id
    ):
        return

    print(
        f"Reaction removed: "
        f"{payload.emoji} "
        f"by {payload.user_id}"
    )

    await asyncio.sleep(0.15)

    await refresh_async(
        f"reaction removed {payload.emoji}"
    )


# ------------------------------------------------------------
# ALL REACTIONS CLEARED
# ------------------------------------------------------------

@client.event
async def on_raw_reaction_clear(payload):

    if payload.channel_id != CHANNEL_ID_INT:
        return

    if payload.message_id != MSG_ID_INT:
        return

    await asyncio.sleep(0.15)

    await refresh_async(
        "all reactions cleared"
    )


# ------------------------------------------------------------
# START BOT
# ------------------------------------------------------------

print("Starting Guildie Clock...")

client.run(BOT_TOKEN)
