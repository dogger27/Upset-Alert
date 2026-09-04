# Lock Screen card — render a SwiftUI piece on the Mac, no build needed

Jupiter has no Swift toolchain and the Mac has no iOS SDK, so the widget's
pure-SwiftUI subviews are rendered against the macOS SDK with `ImageRenderer`.
`seedpills.swift` carries a COPY of the shipping colour constants and
`SeedBadge` from `mobile/targets/activity/UpsetAlertActivity.swift` — regenerate
it from the source before trusting it (the python block in the session that
built it slices those two regions out of the file).

    scp run-on-mac.sh seedpills.swift ../../mobile/targets/activity/UpsetAlertActivity.swift vanmac375:/tmp/
    ssh vanmac375 bash /tmp/run-on-mac.sh
    scp vanmac375:/tmp/seedpills.png ../shots/

The Mac's login shell is tcsh: run scripts as `bash <file>`, never inline
quotes over ssh. The script also `swiftc -parse`s the shipping file.
