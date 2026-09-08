---
description: Rebuild the iOS dev client onto the user's iPhone from Jupiter, headless (needed after any NATIVE change — Swift, the Lock Screen widget, app.json, native modules)
---

# phonebuild — put a native change on the phone

**When:** anything under `mobile/targets/`, `mobile/modules/*/ios/`, `mobile/app.json`,
or a new native dependency. Plain JavaScript/JSX changes do NOT need this — the
phone's dev client loads JS live from Jupiter's Metro (tmux `expo`, port 8081,
`REACT_NATIVE_PACKAGER_HOSTNAME=jupiter.tail600879.ts.net`).

**Rule:** the phone must be unlocked and on the same Wi‑Fi as the Mac (Xcode installs
over the LAN; Tailscale alone is not enough for the install step). USB also works.

## The one command (from Jupiter)

```bash
tools/mac/phonebuild-remote.sh quick     # Swift / widget / module source changed
tools/mac/phonebuild-remote.sh full      # app.json, Info.plist, a NEW target, or "quick" failed
```

`quick` = git pull + `expo run:ios --device <UDID> --no-bundler` (~3–5 min).
`full` adds `npx expo prebuild --platform ios --clean` first (+3 min): regenerates
`ios/` and the widget target. When in doubt, `full`.

It writes `~/.phonebuild/trigger` on the Mac; a LaunchAgent running INSIDE the
user's login session runs `~/bin/phonebuild` and logs to `~/.phonebuild/log`
(mirrored to `/tmp/phonebuild.log`, ending with `PHONEBUILD_DONE`). The helper
follows the log and prints the verdict. Success looks like:

```
› Build Succeeded
› Installing /Users/pwiens/Library/Developer/Xcode/DerivedData/.../UpsetAlert.app
=== <date> exit 0
```

The app launches on the phone by itself. If it shows the dev launcher, the user
taps the Jupiter server in the recent list once.

## Why it is shaped this way (do not "simplify" it)

- **Plain ssh cannot code-sign.** Outside the GUI login session the keychain is
  locked: `codesign` fails with `errSecInternalComponent`, `security` says
  "User interaction is not allowed". Unlocking needs the user's password every
  time — never ask for or store it. `launchctl asuser` needs root. Hence the agent.
- **The agent plist lives in `~/.phonebuild/`**, not `~/Library/LaunchAgents/`
  (root-owned on this Mac, an old installer's doing). So it does NOT auto-load
  at login. **After a Mac reboot**, load it once (from ssh is fine):
  `launchctl bootstrap gui/$(id -u) ~/.phonebuild/ca.upsetalert.phonebuild.plist`
  Check: `launchctl print gui/$(id -u)/ca.upsetalert.phonebuild | grep state`.
- **The phone is pinned by UDID** (`00008140-000C0DC41A88801C`) because a run whose
  output is piped cannot answer Expo's "Select a device" prompt.
- **`--no-bundler`** makes `expo run:ios` exit after the install. Without it the
  command sits on a Metro of its own, the log never ends, and the phone gets
  pointed at the Mac's Metro instead of Jupiter's.
- **Provisioning** was done once with `xcodebuild … -allowProvisioningUpdates`;
  if a build ever says "No profiles for 'ca.upsetalert.app'", see memory
  `local-ios-build-on-mac` for that one-off.

## Two failures that are not the code (2026-09-08)

- **`pod install` dies with "Unicode Normalization not appropriate for ASCII-8BIT"**
  (and Expo says "Couldn't install Pods"): CocoaPods under Ruby 4 needs a UTF-8
  locale and a LaunchAgent has none — the crash is in CocoaPods' own error
  reporter, so the log never shows the real reason. `~/bin/phonebuild` and the
  agent now export `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8`; any manual `pod
  install` over ssh needs the same.
- **"The developer disk image could not be mounted on this device" / "Timed out
  waiting for all destinations"**: the phone is reachable but LOCKED (or, rarely,
  its iOS is newer than Xcode's). The pods and the plan succeeded; unlock the
  phone and run `quick` again. To make that rerun short, a compile can be warmed
  without the phone or the keychain: from `mobile/ios`,
  `xcodebuild -workspace UpsetAlert.xcworkspace -scheme UpsetAlert -configuration
  Debug -destination generic/platform=iOS CODE_SIGNING_ALLOWED=NO
  CODE_SIGNING_REQUIRED=NO build` (over plain ssh, ~6 min).

## Fallbacks, in order

1. Agent not loaded (log never appears): run the bootstrap line above, retry.
2. Still nothing: open a Terminal window on the Mac from Jupiter and run it there
   (the keychain is available in that session; a window pops):
   `osascript -e 'tell application "Terminal" to do script "bash -c '\''~/bin/phonebuild quick 2>&1 | tee /tmp/phonebuild.log; echo PHONEBUILD_DONE >> /tmp/phonebuild.log'\''"'`
   — wrapped in `bash -c` because the Mac's shell is tcsh (`2>&1` is "Ambiguous
   output redirect" there).
3. Ask the user to run `phonebuild quick` in their own Terminal.

## Verify what the phone runs (before blaming the code)

From ssh on the Mac: the checkout's HEAD (`git -C ~/Projects/TennisFantasyLeague log -1`),
whether `mobile/targets/activity/UpsetAlertActivity.swift` has the change, and the
newest `~/Library/Developer/Xcode/DerivedData` mtime. A Lock Screen card that still
shows the OLD layout after a push almost always means no build ran since.

Sources: `tools/mac/` holds `phonebuild`, the agent script, the plist, the remote
helper and a README. To SEE a SwiftUI piece without building, use
`tools/lockscreen-render/` (memory `swiftui-render-on-mac`).
