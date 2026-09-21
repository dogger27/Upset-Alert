"""A draw staged in `Draft:` is still the draw.

2026-09-21: Hangzhou and Chengdu started in two days with no mainspace article,
so neither could go Active — while both sat complete in Wikipedia's `Draft:`
namespace. `Draft:2026 Chengdu Open – Singles` (page 84283819) was 11,499 bytes
with `| draw = 28 (4 Q / 3 WC)`, 40 named RD1 slots and seed cells reading
1-8 / Q / WC / NG, in the same {{16TeamBracket-Compact-Tennis3-Byes}} template
the parser already handles. One editor has staged there since ~2026-07-28.

Verified against live Wikipedia when this was written: the fallback reads both
draws, finds 4 byes at slots 2 and 10 — which the official ATP draw sheet also
marks `Bye` — and releases the draw, while storing NO page id, because a
draft's id belongs to a page that will be redirected or deleted.

Async tests here follow the repo's convention: a plain test driving an inner
coroutine with asyncio.run, since pytest-asyncio is not configured.
"""
import asyncio

import pytest

from app.services import scraper
from app.services.scraper import WikiPageNotFound, _DRAFT_PREFIX

MAIN = "2026 Hangzhou Open – Singles"
GENDERED_DRAFT = f"{_DRAFT_PREFIX}2026 Hangzhou Open – Men's singles"

# The smallest wikitext that parses as a 32-slot bracket.
BRACKET = """
{{16TeamBracket-Compact-Tennis3-Byes
| RD1-team01=Player One | RD1-seed01=1
| RD1-team03=Player Two | RD1-seed03=WC
}}
{{16TeamBracket-Compact-Tennis3-Byes
| RD1-team01=Player Three | RD1-seed01=2
}}
"""


@pytest.fixture
def fetches(monkeypatch):
    """Serve only the titles a test allows, and record every title asked for."""
    asked: list = []

    def install(available: dict):
        async def fake(page_title, page_id=None, force_refresh=False):
            asked.append(page_title)
            if page_title in available:
                return available[page_title], 12345
            # The general tournament article is fetched for dates; an empty
            # body is the ordinary "nothing to read" case and not this
            # suite's subject.
            if "–" not in page_title:
                return "", 0
            raise WikiPageNotFound(f"Page not found: {page_title!r}")
        monkeypatch.setattr(scraper, "fetch_wikitext", fake)
        return asked
    return install


def test_a_draft_page_is_read_when_mainspace_is_missing(fetches):
    asked = fetches({f"{_DRAFT_PREFIX}{MAIN}": BRACKET})

    async def go():
        return await scraper.scrape_tournament(MAIN, year=2026, gender="M")

    parsed = asyncio.run(go())
    assert parsed.draw_size == 32
    assert any(t.startswith(_DRAFT_PREFIX) for t in asked)


def test_the_draft_page_id_is_never_stored(fetches):
    """draws.wiki_page_id is unique and a draft's id belongs to a page that
    will be redirected or deleted; pinning it would leave the draw pointed at
    a corpse. `parsed.wiki_page_id = resolved_id or None` makes 0 the answer."""
    fetches({f"{_DRAFT_PREFIX}{MAIN}": BRACKET})

    async def go():
        return await scraper.scrape_tournament(MAIN, year=2026, gender="M")

    assert asyncio.run(go()).wiki_page_id is None


def test_mainspace_always_wins_over_a_draft_of_it(fetches):
    """A live article beats a draft of the same event, and the draft is not
    even asked for."""
    asked = fetches({MAIN: BRACKET, f"{_DRAFT_PREFIX}{MAIN}": BRACKET})

    async def go():
        return await scraper.scrape_tournament(MAIN, year=2026, gender="M")

    parsed = asyncio.run(go())
    assert parsed.wiki_page_id == 12345
    assert not any(t.startswith(_DRAFT_PREFIX) for t in asked)


def test_every_mainspace_variant_is_tried_before_any_draft(fetches):
    """The gendered suffix is a mainspace question; exhausting it first keeps a
    combined event's real article ahead of a single-tour draft of it."""
    asked = fetches({f"{_DRAFT_PREFIX}{MAIN}": BRACKET})

    async def go():
        return await scraper.scrape_tournament(MAIN, year=2026, gender="M")

    asyncio.run(go())
    first_draft = next(i for i, t in enumerate(asked)
                       if t.startswith(_DRAFT_PREFIX))
    before = asked[:first_draft]
    assert MAIN in before
    assert any("Men's singles" in t for t in before), before


def test_a_combined_events_gendered_draft_is_found_too(fetches):
    """`Draft:2026 China Open – Women's singles` was live when this was
    written, so the draft search must cover the gendered variants too."""
    fetches({GENDERED_DRAFT: BRACKET})

    async def go():
        return await scraper.scrape_tournament(MAIN, year=2026, gender="M")

    parsed = asyncio.run(go())
    assert parsed.draw_size == 32
    assert parsed.wiki_page_id is None


def test_nothing_anywhere_still_raises(fetches):
    """A missing draw stays missing: the fallback is a wider search, not a
    reason to invent a draw."""
    fetches({})

    async def go():
        return await scraper.scrape_tournament(MAIN, year=2026, gender="M")

    with pytest.raises(WikiPageNotFound):
        asyncio.run(go())


def test_no_title_is_draft_prefixed_twice(fetches):
    asked = fetches({})

    async def go():
        return await scraper.scrape_tournament(MAIN, year=2026, gender="M")

    with pytest.raises(WikiPageNotFound):
        asyncio.run(go())
    assert not any(t.count(_DRAFT_PREFIX) > 1 for t in asked), asked
