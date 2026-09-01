"""Send one push to one token and print exactly what Apple said.

The point of this script is that nearly every way APNs can be misconfigured is
answerable from the SERVER SIDE ALONE, before any app exists beyond a
development build that can print its device token. Run it first; if it cannot
reach Apple, nothing else in the Live Activity stack can either.

What it proves, in the order worth checking:

  1. Outbound HTTP/2 from inside this container to Apple works at all. This is
     a home server behind a Cloudflare Tunnel, but the tunnel is INBOUND ONLY
     and is not involved — if the ISP, container DNS or the h2 package is
     wrong, everything else is noise.
  2. The .p8, team id, key id and ES256 signing are right. Any answer other
     than 403 proves it.
  3. The topic, including the mandatory .push-type.liveactivity suffix —
     400 BadTopic versus 200.
  4. Sandbox versus production routing. Send the same token to both: exactly
     one returns 200 and the other 400 BadDeviceToken. Two lines, and it
     answers the question that otherwise costs an evening.

What it CANNOT prove: that content-state decodes into the Swift struct. APNs
returns 200 for a payload the app cannot decode — the activity simply stops
moving. Apple's Push Notifications Console is the only external source of
truth for that.

    docker compose exec -T backend python -m scripts.apns_probe <token> --both
    docker compose exec -T backend python -m scripts.apns_probe <token> \
        --type liveactivity --env sandbox
"""

import argparse
import asyncio
import sys
import time

sys.path.insert(0, "/app")

from app.core.config import settings          # noqa: E402
from app.services import apns                 # noqa: E402


def sample(push_type: str) -> dict:
    if push_type == "liveactivity":
        return {
            "aps": {
                "timestamp": int(time.time()),
                "event": "update",
                "relevance-score": 100,
                "content-state": {
                    "v": 1,
                    "games": [["6", "3"], ["4", "2"]],
                    "point": ["40", "30"],
                    "tiebreak": False, "match_tiebreak": False,
                    "serving": 1, "sets_won": [1, 0],
                    "status": "in_progress", "winner": None, "final_line": None,
                    "pick": {"side": 1, "correct": None},
                },
            }
        }
    return {"aps": {"alert": {"title": "Upset Alert",
                              "body": "APNs probe — you can ignore this."},
                    "sound": "default"}}


async def one(token: str, env: str, push_type: str) -> None:
    r = await apns.send(token=token, payload=sample(push_type),
                        push_type=push_type, env=env, priority=10,
                        expiration=int(time.time()) + 300,
                        collapse_id="probe")
    verdict = "OK" if r.ok else (r.reason or f"http_{r.status}")
    print(f"  {env:<10} {push_type:<13} status={str(r.status):<5} {verdict}"
          + (f"  apns-id={r.apns_id}" if r.apns_id else ""))
    if r.reason == "BadTopic":
        print("    -> the topic is wrong. A Live Activity needs the bundle id "
              "PLUS '.push-type.liveactivity'.")
    if r.reason in ("BadDeviceToken", "DeviceTokenNotForTopic"):
        print("    -> right key, wrong environment for this token, or the token "
              "belongs to another bundle id. Try the other --env.")
    if r.status == 403:
        print("    -> the provider token was rejected: check APNS_KEY_ID, "
              "APNS_TEAM_ID and that the .p8 matches the key id.")
    if r.reason == "not_configured":
        print("    -> APNS_KEY_ID / APNS_TEAM_ID / APNS_BUNDLE_ID must be set "
              f"and the key readable at {settings.apns_key_path}.")
    if r.reason == "blocked":
        print("    -> outbound_notifications=false on this instance.")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("token", help="the hex device token, or a Live Activity push token")
    ap.add_argument("--env", choices=("sandbox", "production"))
    ap.add_argument("--type", dest="push_type",
                    choices=("alert", "liveactivity"), default="alert")
    ap.add_argument("--both", action="store_true",
                    help="try both environments — the fastest way to learn which "
                         "one this token belongs to")
    args = ap.parse_args()

    print(f"  bundle={settings.apns_bundle_id or '(unset)'} "
          f"key={settings.apns_key_id or '(unset)'} "
          f"team={settings.apns_team_id or '(unset)'} "
          f"configured={apns.apns_enabled()}")

    envs = ("sandbox", "production") if args.both else (
        args.env or settings.apns_default_env,)
    for env in envs:
        await one(args.token, env, args.push_type)
    await apns.aclose()


if __name__ == "__main__":
    asyncio.run(main())
