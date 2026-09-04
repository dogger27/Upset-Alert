# Building the dev client onto the phone

`phonebuild` lives at `~/bin/phonebuild` on the Mac (copy here). `phonebuild`
= pull, clean prebuild, build+install; `phonebuild quick` skips the prebuild.
The phone is pinned by UDID and `--no-bundler` makes the command exit after
the install; the phone loads JS from Jupiter's Metro.

Headless from Jupiter: `tools/mac/phonebuild-remote.sh quick|full` writes
`~/.phonebuild/trigger` on the Mac; a LaunchAgent (`ca.upsetalert.phonebuild`,
plist + `agent.sh` in `~/.phonebuild/`) running INSIDE the login session —
where the keychain is unlocked, which plain ssh never is — runs the build and
logs to `~/.phonebuild/log`. It was bootstrapped from ssh with
`launchctl bootstrap gui/$(id -u) ~/.phonebuild/ca.upsetalert.phonebuild.plist`;
it lives outside `~/Library/LaunchAgents` (root-owned on this Mac), so after a
Mac reboot run that bootstrap line again.
