#!/bin/bash
# Runs inside the user's login session (LaunchAgent), where the keychain is
# unlocked. Fired when ~/.phonebuild/trigger changes; the trigger's content is
# the mode ("quick" or "full"). Logs to ~/.phonebuild/log (and /tmp/phonebuild.log).
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
export HOME=/Users/pwiens
export CI=1
D=$HOME/.phonebuild
[ -f "$D/trigger" ] || exit 0
MODE=$(tr -d '[:space:]' < "$D/trigger"); rm -f "$D/trigger"
{
  echo "=== $(date) phonebuild agent: mode=${MODE:-quick}"
  if [ "$MODE" = "full" ]; then "$HOME/bin/phonebuild"; else "$HOME/bin/phonebuild" quick; fi
  echo "=== $(date) exit $?"
  echo PHONEBUILD_DONE
} > "$D/log" 2>&1
cp "$D/log" /tmp/phonebuild.log
