"""Passkeys — public-key credentials that replace the password entirely.

The private half never leaves the phone's secure enclave, so a leak of this
table gives an attacker nothing to sign in with: public keys are public by
construction. That is the whole point of the exchange, and it is why these rows
carry no secret and need no encryption, unlike a shared TOTP seed would.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserPasskey(Base):
    __tablename__ = "user_passkeys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # Base64url, exactly as the browser reports it — this is the lookup key on
    # a usernameless sign-in, where the credential is all we are given.
    credential_id: Mapped[str] = mapped_column(String, nullable=False,
                                               unique=True, index=True)
    public_key: Mapped[str] = mapped_column(String, nullable=False)
    # Some authenticators count signatures and some always report 0. A COUNT
    # THAT GOES BACKWARDS means a cloned key, but only for the ones that count
    # at all — see the verify path, which refuses to read a regression into a
    # zero it was given twice.
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    transports: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # What the owner will recognise in a list: "iPhone", "MacBook". Supplied by
    # the client at enrolment, because the server cannot see the device.
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)


class WebAuthnChallenge(Base):
    """One challenge, good once.

    The server must remember what it asked so the answer cannot be a recording
    of an older one. Rows are deleted the moment they are spent and swept on
    age, so this table stays a few rows deep rather than growing forever.
    """

    __tablename__ = "webauthn_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    challenge: Mapped[str] = mapped_column(String, nullable=False,
                                           unique=True, index=True)
    # Null for a sign-in: at that point nobody has said who they are yet, which
    # is exactly what makes a usernameless passkey login possible.
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 nullable=False)
