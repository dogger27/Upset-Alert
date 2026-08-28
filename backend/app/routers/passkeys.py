"""Signing in with a passkey instead of a password.

The browser holds a private key it will only use after the person proves they
are there — Face ID, a fingerprint, a PIN. The site holds the public half and
checks a signature. Nothing worth stealing crosses the wire or sits in this
database, and a signature is bound to the site that asked for it, so a
convincing copy of Upset Alert cannot collect anything reusable.

Two flows, four endpoints. Enrolment happens INSIDE a session (you prove who
you are the old way, once) and sign-in happens outside one. Sign-in is
deliberately usernameless: the browser knows which passkeys it holds for this
site, so it offers them and we recognise the account from the credential.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.security import create_access_token
from app.database import get_db
from app.models.passkey import UserPasskey, WebAuthnChallenge
from app.models.user import User
from app.schemas.user import Token
from app.services.system_log import app_log

router = APIRouter(prefix="/auth/passkeys", tags=["passkeys"])

# Long enough for someone to find their phone, short enough that a challenge
# left on a screen is not a standing invitation.
CHALLENGE_TTL = timedelta(minutes=5)

# WHO IS HOLDING THE KEY. The AAGUID names the authenticator's make, which is
# the only way to tell a passkey saved in the browser from one saved in the
# system password manager on the same phone. These identifiers are published by
# their vendors for exactly this purpose (the FIDO/passkeys.dev community list).
# An unknown or zeroed value simply falls through to the device name — several
# browsers zero it deliberately, and a wrong guess is worse than a plain one.
_AAGUID_NAMES = {
    "fbfc3007-154e-4ecc-8c0b-6e020557d7bd": "iCloud Passwords",
    "adce0002-35bc-c60a-648b-0b25f1f05503": "Chrome",
    "b5397666-4885-aa6b-cebf-e52262a439a2": "Chromium",
    "ea9b8d66-4d01-1d21-3ce4-b6b48cb575d4": "Google Password Manager",
    "08987058-cadc-4b81-b6e1-30de50dcbe96": "Windows Hello",
    "9ddd1817-af5a-4672-a2b9-3e3dd95000a9": "Windows Hello",
    "6028b017-b1d4-4c02-b4b3-afcdafc96bb2": "Windows Hello",
    "bada5566-a7aa-401f-bd96-45619a55120d": "1Password",
    "d548826e-79b4-db40-a3d8-11116f7e8349": "Bitwarden",
    "531126d6-e717-415c-9320-3d9aa6981239": "Dashlane",
    "0ea242b4-43c4-4a1b-8b17-dd6d0b6baec6": "Keeper",
    "f3809540-7f14-49c1-a8b3-8f813b225541": "Enpass",
    "b84e4048-15dc-4dd0-8640-f4f60813c8af": "NordPass",
    "22248c4c-7a12-46e2-9a41-44291b373a4d": "LastPass",
    "de1e552d-db1d-4423-a619-566b625cdc84": "Proton Pass",
}
_ZERO_AAGUID = "00000000-0000-0000-0000-000000000000"


def _describe(aaguid: Optional[str], device: str) -> str:
    """The best name we can produce without asking.

    A site cannot read a phone's name — no web API exposes it — so "Paul's
    iPhone" is out of reach. What IS knowable is which password manager saved
    the key and, from the browser, what kind of machine it was saved on:
    "iCloud Passwords on iPhone" answers the question the device name was
    standing in for.
    """
    provider = _AAGUID_NAMES.get((aaguid or "").lower()) if aaguid and \
        aaguid.lower() != _ZERO_AAGUID else None
    device = (device or "").strip()[:40]
    if provider and device:
        return f"{provider} on {device}"
    return provider or device or "Passkey"


def _origins() -> list[str]:
    return [o.strip() for o in settings.webauthn_origins.split(",") if o.strip()]


async def _issue_challenge(db: AsyncSession, raw: bytes, kind: str,
                           user_id: Optional[int]) -> None:
    """Remember what we asked, and sweep whatever has gone stale."""
    now = datetime.now(timezone.utc)
    await db.execute(delete(WebAuthnChallenge).where(
        WebAuthnChallenge.expires_at < now))
    db.add(WebAuthnChallenge(challenge=bytes_to_base64url(raw), kind=kind,
                             user_id=user_id, expires_at=now + CHALLENGE_TTL))
    await db.commit()


async def _spend_challenge(db: AsyncSession, raw_b64: str, kind: str) -> bool:
    """True if we asked this exact question and are still waiting on it.

    The row is deleted whether or not it had expired, so one challenge can
    never answer twice — a replayed assertion finds nothing to match.
    """
    row = (await db.execute(select(WebAuthnChallenge).where(
        WebAuthnChallenge.challenge == raw_b64,
        WebAuthnChallenge.kind == kind))).scalars().first()
    if not row:
        return False
    expires = row.expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    fresh = bool(expires and expires > datetime.now(timezone.utc))
    await db.execute(delete(WebAuthnChallenge).where(
        WebAuthnChallenge.id == row.id))
    await db.commit()
    return fresh


# ── Enrolment (inside a session) ────────────────────────────────────────────
@router.post("/register/options")
async def register_options(current_user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(select(UserPasskey).where(
        UserPasskey.user_id == current_user.id))).scalars().all()
    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        user_id=str(current_user.id).encode(),
        user_name=current_user.email,
        user_display_name=current_user.display_name or current_user.username,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # DISCOVERABLE, or sign-in would have to start by asking who you
            # are — which is the friction this feature exists to remove.
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        # Offering to enrol a key the account already holds just produces a
        # confusing error on the device; the browser greys it out instead.
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credential_id))
            for p in existing],
    )
    await _issue_challenge(db, options.challenge, "register", current_user.id)
    return {"options": options_to_json(options)}


@router.post("/register/verify")
async def register_verify(body: dict,
                          current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    credential = body.get("credential")
    if not credential:
        raise HTTPException(400, "No credential was supplied.")
    try:
        client_data = credential.get("response", {}).get("clientDataJSON", "")
        import json as _json
        challenge_b64 = _json.loads(
            base64url_to_bytes(client_data).decode())["challenge"]
    except Exception:
        raise HTTPException(400, "That credential could not be read.")
    if not await _spend_challenge(db, challenge_b64, "register"):
        raise HTTPException(400, "This enrolment expired. Please try again.")

    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge_b64),
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=_origins(),
        )
    except Exception as exc:
        await app_log("warning", "auth",
                      f"Passkey enrolment rejected for {current_user.username}",
                      {"error": str(exc)})
        raise HTTPException(400, "That passkey could not be verified.")

    cred_id = bytes_to_base64url(verified.credential_id)
    if (await db.execute(select(UserPasskey).where(
            UserPasskey.credential_id == cred_id))).scalars().first():
        raise HTTPException(400, "That passkey is already registered.")
    db.add(UserPasskey(
        user_id=current_user.id,
        credential_id=cred_id,
        public_key=bytes_to_base64url(verified.credential_public_key),
        sign_count=verified.sign_count or 0,
        transports=",".join(
            (credential.get("response", {}).get("transports") or [])) or None,
        aaguid=str(verified.aaguid) if verified.aaguid else None,
        # An explicit name always wins; otherwise say who is holding it and
        # where, which is what the owner was trying to tell the two apart by.
        name=await _unique_name(db, current_user.id,
                                str(body.get("name") or "").strip()[:60]
                                or _describe(str(verified.aaguid or ""),
                                             str(body.get("device") or ""))),
    ))
    await db.commit()
    await app_log("info", "auth", f"Passkey added for {current_user.username}")
    return {"ok": True}


async def _unique_name(db: AsyncSession, user_id: int, wanted: str) -> str:
    """A name that is not already in this account's list.

    Two passkeys on the same phone — one in the browser, one in the system
    password manager — are genuinely different keys, and the server cannot tell
    them apart: attestation is deliberately "none", so there is no authenticator
    identity to read. Rather than show two identical rows, the second gets a
    number and the owner can rename it to whatever it actually is.
    """
    taken = set((await db.execute(
        select(UserPasskey.name).where(UserPasskey.user_id == user_id))).scalars().all())
    if wanted not in taken:
        return wanted
    for n in range(2, 100):
        candidate = f"{wanted} {n}"
        if candidate not in taken:
            return candidate
    return wanted


@router.patch("/{passkey_id}")
async def rename_passkey(passkey_id: int, body: dict,
                         current_user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    """The owner knows where the key actually lives; the server never can."""
    name = str(body.get("name") or "").strip()[:60]
    if not name:
        raise HTTPException(400, "A passkey needs a name.")
    row = (await db.execute(select(UserPasskey).where(
        UserPasskey.id == passkey_id,
        UserPasskey.user_id == current_user.id))).scalars().first()
    if not row:
        raise HTTPException(404, "No such passkey.")
    row.name = name
    await db.commit()
    return {"id": row.id, "name": row.name}


@router.get("")
async def list_passkeys(current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(UserPasskey).where(
        UserPasskey.user_id == current_user.id)
        .order_by(UserPasskey.created_at))).scalars().all()
    return [{"id": p.id, "name": p.name, "created_at": p.created_at,
             "last_used_at": p.last_used_at} for p in rows]


@router.delete("/{passkey_id}")
async def delete_passkey(passkey_id: int,
                         current_user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(UserPasskey).where(
        UserPasskey.id == passkey_id,
        UserPasskey.user_id == current_user.id))).scalars().first()
    if not row:
        raise HTTPException(404, "No such passkey.")
    await db.delete(row)
    await db.commit()
    await app_log("info", "auth", f"Passkey removed for {current_user.username}")
    return {"ok": True}


# ── Sign-in (outside a session) ─────────────────────────────────────────────
@router.post("/login/options")
async def login_options(db: AsyncSession = Depends(get_db)):
    """Deliberately says nothing about who is signing in.

    No allow_credentials, so the browser offers whichever passkeys it holds for
    this site and this endpoint leaks nothing about which accounts exist.
    """
    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    await _issue_challenge(db, options.challenge, "login", None)
    return {"options": options_to_json(options)}


@router.post("/login/verify", response_model=Token)
async def login_verify(body: dict, db: AsyncSession = Depends(get_db)):
    credential = body.get("credential")
    if not credential:
        raise HTTPException(400, "No credential was supplied.")
    try:
        import json as _json
        challenge_b64 = _json.loads(base64url_to_bytes(
            credential["response"]["clientDataJSON"]).decode())["challenge"]
    except Exception:
        raise HTTPException(400, "That credential could not be read.")
    if not await _spend_challenge(db, challenge_b64, "login"):
        raise HTTPException(401, "This sign-in expired. Please try again.")

    stored = (await db.execute(select(UserPasskey).where(
        UserPasskey.credential_id == credential.get("id")))).scalars().first()
    if not stored:
        raise HTTPException(401, "That passkey is not registered here.")
    user = await db.get(User, stored.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "That account is not available.")

    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge_b64),
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=_origins(),
            credential_public_key=base64url_to_bytes(stored.public_key),
            credential_current_sign_count=stored.sign_count or 0,
        )
    except Exception as exc:
        await app_log("warning", "auth", "Passkey sign-in rejected",
                      {"user": user.username, "error": str(exc)})
        raise HTTPException(401, "That passkey could not be verified.")

    # A counter that goes BACKWARDS means a cloned authenticator — but plenty
    # of platform keys never count at all and report 0 every time, which must
    # not be read as a clone. Only a device that actually counts is judged.
    if verified.new_sign_count and stored.sign_count and \
            verified.new_sign_count <= stored.sign_count:
        await app_log("error", "auth", "Passkey sign counter went backwards",
                      {"user": user.username, "stored": stored.sign_count,
                       "seen": verified.new_sign_count})
        raise HTTPException(401, "That passkey could not be verified.")
    stored.sign_count = verified.new_sign_count or stored.sign_count
    stored.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    # A passkey proves possession AND presence, which is strictly more than a
    # password does, so it stands on its own — including for an account that
    # has never verified its email, where the password path would stop.
    return Token(access_token=create_access_token(str(user.id)))
