"""A software authenticator, so the passkey server logic is actually exercised.

There is no browser here, so this builds the two structures a real device sends
— an attestation with fmt "none" and a signed assertion — with a P-256 key we
control. If verification accepts these and rejects the tampered variants, the
server's half of WebAuthn is right; only the browser plumbing is left to try on
a phone.
"""
import sys, os, json, hashlib, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn import (base64url_to_bytes, verify_registration_response,
                      verify_authentication_response)
from webauthn.helpers import bytes_to_base64url

RP_ID = "upsetalert.ca"
ORIGIN = "https://upsetalert.ca"
CRED_ID = b"\x01\x02\x03\x04" * 4

key = ec.generate_private_key(ec.SECP256R1())


def cose_key():
    n = key.public_key().public_numbers()
    return cbor2.dumps({1: 2, 3: -7, -1: 1,
                        -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})


def auth_data(flags=0x45, sign_count=0, attested=True, rp_id=RP_ID):
    data = hashlib.sha256(rp_id.encode()).digest()
    data += bytes([flags]) + struct.pack(">I", sign_count)
    if attested:
        data += b"\x00" * 16 + struct.pack(">H", len(CRED_ID)) + CRED_ID + cose_key()
    return data


def client_data(typ, challenge, origin=ORIGIN):
    return json.dumps({"type": typ, "challenge": bytes_to_base64url(challenge),
                       "origin": origin, "crossOrigin": False}).encode()


def registration(challenge, origin=ORIGIN):
    cd = client_data("webauthn.create", challenge, origin)
    att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data()})
    return {"id": bytes_to_base64url(CRED_ID), "rawId": bytes_to_base64url(CRED_ID),
            "response": {"clientDataJSON": bytes_to_base64url(cd),
                         "attestationObject": bytes_to_base64url(att),
                         "transports": ["internal"]},
            "type": "public-key", "clientExtensionResults": {}}


def assertion(challenge, sign_count=1, origin=ORIGIN, tamper=False):
    cd = client_data("webauthn.get", challenge, origin)
    ad = auth_data(flags=0x05, sign_count=sign_count, attested=False)
    sig = key.sign(ad + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
    if tamper:
        sig = sig[:-1] + bytes([sig[-1] ^ 0xFF])
    return {"id": bytes_to_base64url(CRED_ID), "rawId": bytes_to_base64url(CRED_ID),
            "response": {"clientDataJSON": bytes_to_base64url(cd),
                         "authenticatorData": bytes_to_base64url(ad),
                         "signature": bytes_to_base64url(sig),
                         "userHandle": bytes_to_base64url(b"1")},
            "type": "public-key", "clientExtensionResults": {}}


PUBKEY = None

def test_registration_is_accepted():
    global PUBKEY
    ch = b"registration-challenge-0123456789"
    v = verify_registration_response(
        credential=registration(ch), expected_challenge=ch,
        expected_rp_id=RP_ID, expected_origin=[ORIGIN])
    assert v.credential_id == CRED_ID
    PUBKEY = v.credential_public_key
    assert PUBKEY

def test_registration_from_another_site_is_refused():
    ch = b"registration-challenge-0123456789"
    try:
        verify_registration_response(
            credential=registration(ch, origin="https://not-upsetalert.example"),
            expected_challenge=ch, expected_rp_id=RP_ID, expected_origin=[ORIGIN])
    except Exception:
        return
    raise AssertionError("a foreign origin was accepted")

def test_assertion_is_accepted():
    ch = b"authentication-challenge-012345678"
    v = verify_authentication_response(
        credential=assertion(ch), expected_challenge=ch, expected_rp_id=RP_ID,
        expected_origin=[ORIGIN], credential_public_key=PUBKEY,
        credential_current_sign_count=0)
    assert v.new_sign_count == 1

def test_wrong_challenge_is_refused():
    try:
        verify_authentication_response(
            credential=assertion(b"challenge-the-server-never-asked!"),
            expected_challenge=b"authentication-challenge-012345678",
            expected_rp_id=RP_ID, expected_origin=[ORIGIN],
            credential_public_key=PUBKEY, credential_current_sign_count=0)
    except Exception:
        return
    raise AssertionError("a replayed challenge was accepted")

def test_bad_signature_is_refused():
    ch = b"authentication-challenge-012345678"
    try:
        verify_authentication_response(
            credential=assertion(ch, tamper=True), expected_challenge=ch,
            expected_rp_id=RP_ID, expected_origin=[ORIGIN],
            credential_public_key=PUBKEY, credential_current_sign_count=0)
    except Exception:
        return
    raise AssertionError("a forged signature was accepted")

def test_phishing_origin_is_refused():
    ch = b"authentication-challenge-012345678"
    try:
        verify_authentication_response(
            credential=assertion(ch, origin="https://upsetalert.ca.evil.example"),
            expected_challenge=ch, expected_rp_id=RP_ID, expected_origin=[ORIGIN],
            credential_public_key=PUBKEY, credential_current_sign_count=0)
    except Exception:
        return
    raise AssertionError("a look-alike origin was accepted")

def test_staging_origin_is_accepted_when_listed():
    ch = b"authentication-challenge-012345678"
    v = verify_authentication_response(
        credential=assertion(ch, origin="https://staging.upsetalert.ca"),
        expected_challenge=ch, expected_rp_id=RP_ID,
        expected_origin=[ORIGIN, "https://staging.upsetalert.ca"],
        credential_public_key=PUBKEY, credential_current_sign_count=0)
    assert v.new_sign_count == 1

if __name__ == "__main__":
    import traceback
    order = ["test_registration_is_accepted", "test_registration_from_another_site_is_refused",
             "test_assertion_is_accepted", "test_wrong_challenge_is_refused",
             "test_bad_signature_is_refused", "test_phishing_origin_is_refused",
             "test_staging_origin_is_accepted_when_listed"]
    fails = 0
    for name in order:
        try:
            globals()[name](); print(f"  PASS {name}")
        except Exception:
            fails += 1; print(f"  FAIL {name}"); traceback.print_exc()
    print("ALL PASS" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
