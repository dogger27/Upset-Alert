/** @type {import('@bacons/apple-targets').Config} */
module.exports = {
  type: 'widget',
  name: 'UpsetAlertActivity',
  // Live Activities need 16.2. 16.1 shipped ActivityKit but not the push
  // updates this whole feature is built on.
  deploymentTarget: '16.2',
  colors: {
    // Matches the app's dark palette (theme.js) so the Lock Screen does not
    // look like a different product.
    $accent: '#c9783a',
    $background: '#101a16',
  },
}
