import os, requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
MSG_ID  = os.environ.get("DISCORD_MESSAGE_ID", "").strip()

# Edit this dict to whatever zones you want.
# Full list of valid zone names: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
ZONES = {
    "Server (UTC)":  "UTC",
    "PST / PDT":     "America/Los_Angeles",
    "EST / EDT":     "America/New_York",
    "KST (Korea)":   "Asia/Seoul",
}

now_utc = datetime.now(timezone.utc)
lines = ["## 🕒 Current Times", ""]
for label, tz in ZONES.items():
    t = now_utc.astimezone(ZoneInfo(tz))
    lines.append(f"**{label}** — {t.strftime('%a %b %d  %H:%M')} ({t.strftime('%Z')})")
lines += ["", f"_Last refresh: <t:{int(now_utc.timestamp())}:R>_"]
content = "\n".join(lines)

if not MSG_ID:
    r = requests.post(f"{WEBHOOK}?wait=true", json={"content": content})
    r.raise_for_status()
    print("=" * 60)
    print(f"MESSAGE_ID = {r.json()['id']}")
    print("Copy the number above and add it as a secret named DISCORD_MESSAGE_ID")
    print("=" * 60)
else:
    r = requests.patch(f"{WEBHOOK}/messages/{MSG_ID}", json={"content": content})
    r.raise_for_status()
    print(f"Updated message {MSG_ID}")
