/* THE RELEASE BUILD DROPS WHAT ONLY DEVELOPMENT NEEDS (App Store prep,
   2026-09-26). app.json lets the app load plain http from the local network
   and from Jupiter's tailnet name: that is how the dev client reaches metro.
   A store build loads its bundled JS and talks https to the API only, so it
   ships without those holes. A build is a release when EAS runs the
   production profile, or when APP_VARIANT=production is set for a local
   archive; every other build (phonebuild included) keeps them. */
const RELEASE = process.env.EAS_BUILD_PROFILE === 'production' || process.env.APP_VARIANT === 'production'

module.exports = ({ config }) => {
  if (!RELEASE) return config
  const { NSAppTransportSecurity, ...infoPlist } = config.ios.infoPlist
  return { ...config, ios: { ...config.ios, infoPlist } }
}
