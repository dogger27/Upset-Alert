# Without this file CocoaPods has nothing to compile, and the module is missing
# from the binary even though the build succeeds and the Swift is right there.
#
# expo-modules-autolinking has two stages and they disagreed:
#   search  -> found the module (it reads expo-module.config.json)
#   resolve -> dropped it (it needs a podspec)
# So the build was green, the app ran, and requireOptionalNativeModule returned
# null with no error anywhere.

Pod::Spec.new do |s|
  s.name           = 'LiveActivity'
  s.version        = '1.0.0'
  s.summary        = 'ActivityKit bridge for Upset Alert'
  s.description    = 'Hands the server push-to-start and per-activity tokens.'
  s.license        = 'MIT'
  s.author         = 'Upset Alert'
  s.homepage       = 'https://upsetalert.ca'
  # Matches the app rather than ActivityKit's 16.2. Raising a pod above the
  # app's own minimum breaks the build for every other target; the Swift guards
  # every ActivityKit call with `if #available(iOS 16.2, *)` instead, which is
  # also what makes the module load harmlessly on older phones.
  s.platforms      = { :ios => '15.1' }
  s.swift_version  = '5.9'
  s.source         = { git: '' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'

  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule'
  }

  s.source_files = "**/*.{h,m,swift}"
end
