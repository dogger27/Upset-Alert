"""One finished match, timed — the raw material for how long tennis takes.

WHY A TABLE OF ITS OWN, rather than more columns on `matches`. Doubles and
qualifying have no rows in `matches` at all — doubles has no bracket, which is
the whole reason it is absent — so anything keyed there can only ever describe
main-draw singles. That is exactly the gap that left doubles estimated by a
constant while singles was measured.

Each row is one Sofascore event, carrying its own classification so an
aggregate never needs a join to a draw we may not track: tour, level, surface,
discipline, stage, and how many sets were played. The last of those matters
more than it looks — a best-of-three that went to a decider is a different
animal from a straight-sets win, and conditioning on it cuts more variance than
any amount of curve-fitting on the total.

`duration_min` is Sofascore's PLAYING time (the sum of its per-set clocks), so
a rain delay between sets is outside it by construction.
"""

from typing import Optional

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MatchDurationSample(Base):
    __tablename__ = "match_duration_samples"
    __table_args__ = (UniqueConstraint("sofa_event_id", name="uq_duration_event"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # The natural key. Unique, so a re-run of the backfill is idempotent and
    # can be stopped and resumed at any point without double-counting.
    sofa_event_id: Mapped[int] = mapped_column(Integer, index=True)

    season_year: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    tour: Mapped[Optional[str]] = mapped_column(String(8))        # ATP / WTA
    # uniqueTournament.tennisPoints: 2000 Slam, 1000, 500, 250. NULL for the
    # events that award none — the Finals, exhibitions, team competitions.
    level: Mapped[Optional[int]] = mapped_column(Integer)
    surface: Mapped[Optional[str]] = mapped_column(String(32))    # incl. indoor/outdoor
    discipline: Mapped[Optional[str]] = mapped_column(String(16))  # singles / doubles
    stage: Mapped[Optional[str]] = mapped_column(String(16))      # main / qualifying
    sets_played: Mapped[Optional[int]] = mapped_column(Integer)
    duration_min: Mapped[Optional[int]] = mapped_column(Integer)
