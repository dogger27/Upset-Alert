# Expo HAS CHANGED

Read the exact versioned docs at https://docs.expo.dev/versions/v54.0.0/ before writing any code.

## Why SDK 54 and not the newest

Pinned to **SDK 54** deliberately, on 2026-09-01. The scaffold started on SDK 57,
but the iPhone this is developed against runs Expo Go 54.0.6 and its App Store
offers no update — so a 57 project answers every scan with "Project is
incompatible with this version of Expo Go" and nothing can be tested at all.

Expo Go supports exactly ONE SDK, so the project version is not a free choice
while Expo Go is the only client. Check what the phone actually reports before
changing it — the dev server sees it on every scan:

    curl -s http://127.0.0.1:4040/api/requests/http | grep -o 'Exponent/[0-9.]*'

Once there is a **development build** (which bundles its own runtime), this
constraint disappears and the SDK can move forward independently of the App
Store. Upgrade then, not before.
