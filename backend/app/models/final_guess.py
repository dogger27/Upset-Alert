"""A user's two guesses about the singles final — the tiebreak (owner, 2026-09-18).

Asked when a user enters a draw: how many aces the champion will hit in the
final, and how many minutes it will last. Once the final is played, ties on
points are broken by whoever came closest on aces, then on minutes (see
scoring.tiebreak_key). One row per user per draw, editable until the picks
lock; a walkover final is 0 aces and 0 minutes, which is why 0 is a valid
answer and the slider's floor.
"""
from datetime import datetime, timezone

from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DrawFinalGuess(Base):
    __tablename__ = "draw_final_guesses"
    __table_args__ = (UniqueConstraint("user_id", "draw_id", name="uq_final_guess_user_draw"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    draw_id: Mapped[int] = mapped_column(ForeignKey("draws.id"), nullable=False, index=True)
    # NULLABLE, unlike the other two: this question was added on 2026-09-19
    # and every guess stored before it has no answer here. Null means "never
    # answered", which holds the default exactly as an untouched slider does.
    final_sets: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    final_aces: Mapped[int] = mapped_column(Integer, nullable=False)
    final_duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    # WHICH FINAL THIS ANSWERS (owner, 2026-09-22). The questions are about two
    # named players — how many aces THE CHAMPION hits — so an answer given for
    # one predicted final says nothing about another. Changing a pick that
    # reaches the final quietly invalidated the answers, and nothing said so.
    #
    # Stamped from predicted_finalists at save time, in CHAMPION then
    # RUNNER-UP order: swapping who wins the final changes who the aces
    # question is about, so the order is part of the fact.
    #
    # Nullable because every row saved before this date has no answer here.
    # Null means "we do not know what it was answered against", which reads as
    # NOT stale — a bar turned red for every legacy row would be crying wolf
    # on rows nobody has touched.
    final_a_entry_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("draw_entries.id"), nullable=True)
    final_b_entry_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("draw_entries.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc),
                                                 onupdate=lambda: datetime.now(timezone.utc))


def answers_are_stale(guess, champion_id, runner_up_id, *, locked: bool) -> bool:
    """Whether a guess was answered for a DIFFERENT final than the one picked.

    The tiebreak questions are about two named players — how many aces the
    CHAMPION hits, how long the final lasts — so a pick that changes who
    reaches the final invalidates the answers. Nothing used to say so: the
    reader's numbers silently stopped describing their bracket.

    False unless it can be PROVEN true, because the consequence is a warning
    on somebody's screen:

      * no guess — there is nothing to be stale;
      * a row saved before the finalists were stamped (null) — we do not know
        what it answered, and reddening every legacy row is crying wolf;
      * a locked draw — nothing can be done about it now, so saying so is
        only noise.

    ORDER IS PART OF THE FACT. Swapping who wins the final keeps the same two
    players and changes who the aces question is about, so (champion, runner-up)
    is compared as a pair in that order, not as a set.
    """
    if guess is None or locked:
        return False
    if guess.final_a_entry_id is None:
        return False
    return (guess.final_a_entry_id, guess.final_b_entry_id) != (champion_id, runner_up_id)
