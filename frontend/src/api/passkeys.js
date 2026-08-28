import client from './client'

/* Passkeys: the browser signs a challenge with a key it will only use after
   the person proves they are there (Face ID, a fingerprint, a PIN).

   WebAuthn speaks ArrayBuffers and our API speaks JSON, so everything crossing
   between them is base64url — NOT plain base64. The '+/' characters are '-_'
   here and the padding is dropped; decoding one as the other yields bytes that
   look almost right and fail verification with no useful error. */
const b64uToBuf = (s) => {
  const pad = s.replace(/-/g, '+').replace(/_/g, '/')
  const bin = atob(pad + '='.repeat((4 - pad.length % 4) % 4))
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out.buffer
}

const bufToB64u = (buf) => {
  const bytes = new Uint8Array(buf)
  let bin = ''
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i])
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/* Not every browser or device has an authenticator. Everything passkey-shaped
   in the UI hangs off this, so an unsupported browser is never offered a
   button that cannot work. */
export const passkeysSupported = () =>
  typeof window !== 'undefined' &&
  typeof window.PublicKeyCredential !== 'undefined' &&
  typeof navigator?.credentials?.create === 'function'

/* Whether the browser can offer a passkey from inside the sign-in field
   itself, rather than behind a button. Safari and Chrome both do; the check is
   feature detection, never a browser sniff. */
export const conditionalUIAvailable = async () => {
  try {
    return passkeysSupported() &&
      typeof window.PublicKeyCredential.isConditionalMediationAvailable === 'function' &&
      await window.PublicKeyCredential.isConditionalMediationAvailable()
  } catch {
    return false
  }
}

export const listPasskeys = () => client.get('/auth/passkeys').then(r => r.data)
export const deletePasskey = (id) =>
  client.delete(`/auth/passkeys/${id}`).then(r => r.data)
export const renamePasskey = (id, name) =>
  client.patch(`/auth/passkeys/${id}`, { name }).then(r => r.data)

export async function enrolPasskey(name) {
  const { options } = await client.post('/auth/passkeys/register/options')
    .then(r => r.data)
  const publicKey = JSON.parse(options)
  publicKey.challenge = b64uToBuf(publicKey.challenge)
  publicKey.user.id = b64uToBuf(publicKey.user.id)
  publicKey.excludeCredentials = (publicKey.excludeCredentials || [])
    .map(c => ({ ...c, id: b64uToBuf(c.id) }))

  const cred = await navigator.credentials.create({ publicKey })
  if (!cred) throw new Error('No passkey was created.')
  await client.post('/auth/passkeys/register/verify', {
    name,
    credential: {
      id: cred.id,
      rawId: bufToB64u(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: bufToB64u(cred.response.clientDataJSON),
        attestationObject: bufToB64u(cred.response.attestationObject),
        transports: cred.response.getTransports?.() ?? [],
      },
      clientExtensionResults: cred.getClientExtensionResults?.() ?? {},
    },
  })
}

/* Returns an access token, or null if the person dismissed the sheet.
   `signal` lets the caller abort a conditional (autofill) request — a browser
   allows only one outstanding, so the button press has to cancel it first. */
export async function signInWithPasskey({ conditional = false, signal } = {}) {
  const { options } = await client.post('/auth/passkeys/login/options')
    .then(r => r.data)
  const publicKey = JSON.parse(options)
  publicKey.challenge = b64uToBuf(publicKey.challenge)
  publicKey.allowCredentials = (publicKey.allowCredentials || [])
    .map(c => ({ ...c, id: b64uToBuf(c.id) }))

  const cred = await navigator.credentials.get({
    publicKey,
    ...(conditional ? { mediation: 'conditional' } : {}),
    ...(signal ? { signal } : {}),
  })
  if (!cred) return null
  const { access_token } = await client.post('/auth/passkeys/login/verify', {
    credential: {
      id: cred.id,
      rawId: bufToB64u(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: bufToB64u(cred.response.clientDataJSON),
        authenticatorData: bufToB64u(cred.response.authenticatorData),
        signature: bufToB64u(cred.response.signature),
        userHandle: cred.response.userHandle
          ? bufToB64u(cred.response.userHandle) : null,
      },
      clientExtensionResults: cred.getClientExtensionResults?.() ?? {},
    },
  }).then(r => r.data)
  return access_token
}
