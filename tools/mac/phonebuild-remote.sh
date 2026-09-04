#!/bin/bash
# From Jupiter: rebuild the dev client onto the phone with NO window on the Mac.
#   tools/mac/phonebuild-remote.sh quick|full
# Writes the trigger the Mac's login-session agent watches, then follows its log.
MODE="${1:-quick}"
ssh vanmac375 "bash -c 'rm -f /tmp/phonebuild.log ~/.phonebuild/log; echo $MODE > ~/.phonebuild/trigger'"
echo "triggered '$MODE' on the Mac; following ~/.phonebuild/log (Ctrl-C to stop following; the build carries on)"
ssh vanmac375 "bash -c 'for i in \$(seq 1 120); do [ -f ~/.phonebuild/log ] && grep -q PHONEBUILD_DONE ~/.phonebuild/log && break; sleep 10; done; grep -E \"Build Succeeded|Installing|installed|error|Error|CommandError|exit\" ~/.phonebuild/log | tail -6'"
