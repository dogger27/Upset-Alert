"""The market yardstick: prices turned into probabilities, and rows matched
to the record by names printed two different ways."""
import pytest

from app.services.history.odds import (devig, market_name, names_match, pick_price, record_name)


def test_devig_removes_the_bookmakers_cut():
    # 1.50 / 2.50 imply 0.667 + 0.400 = 1.067 — the 6.7% is the margin.
    p = devig(1.50, 2.50)
    assert p == pytest.approx(0.6667 / 1.0667, abs=1e-4)
    # A fair two-way market comes back unchanged.
    assert devig(2.0, 2.0) == pytest.approx(0.5)
    # Antisymmetric: the two sides sum to one.
    assert devig(1.4, 3.1) + devig(3.1, 1.4) == pytest.approx(1.0)


def test_devig_refuses_impossible_prices():
    for bad in ((None, 2.0), (2.0, None), (1.0, 2.0), (0, 5), ("x", 2.0), (2.0, 0.5)):
        assert devig(*bad) is None


def test_pick_price_prefers_the_best_supported_column():
    row = {"AvgW": 1.8, "AvgL": 2.1, "B365W": 1.75, "B365L": 2.2, "PSW": 1.83, "PSL": 2.05}
    assert pick_price(row) == (1.8, 2.1, "average across books")
    # The average missing: Bet365 next.
    assert pick_price({"B365W": 1.75, "B365L": 2.2})[2] == "Bet365"
    # Only Pinnacle: still usable.
    assert pick_price({"PSW": 1.83, "PSL": 2.05})[2] == "Pinnacle"
    # Nothing priced, or a nonsense price.
    assert pick_price({"MaxW": 2.0, "MaxL": 2.0}) == (None, None, None)
    assert pick_price({"AvgW": 1.0, "AvgL": 0}) == (None, None, None)


def test_the_initial_is_the_last_letter_not_the_first():
    """tennis-data prints "O Connell C." — three tokens, and the initial is C."""
    sur, ini = market_name("O Connell C.")
    assert ini == "c" and "connell" in sur
    assert market_name("Zverev A.") == (frozenset({"zverev"}), "a")
    assert market_name("Ugo Carabelli C.") == (frozenset({"ugo", "carabelli"}), "c")


def test_record_names_split_the_other_way_round():
    """TennisMyLife prints the given names first."""
    assert record_name("Alexander Zverev") == (frozenset({"zverev"}), "a")
    assert record_name("Camilo Ugo Carabelli") == (frozenset({"ugo", "carabelli"}), "c")
    assert record_name("") == (frozenset(), "")


def test_names_match_across_the_two_forms_including_compound_surnames():
    assert names_match(market_name("Zverev A."), record_name("Alexander Zverev"))
    # A compound surname the spreadsheet abbreviates differently.
    assert names_match(market_name("Mpetshi G."), record_name("Giovanni Mpetshi Perricard"))
    assert names_match(market_name("Ugo Carabelli C."), record_name("Camilo Ugo Carabelli"))
    assert names_match(market_name("O Connell C."), record_name("Christopher O Connell"))
    # Different people are not matched, even sharing an initial.
    assert not names_match(market_name("Zverev A."), record_name("Alexander Bublik"))
    # Same surname, contradicting initials — the two Cerundolos, or two Zverevs.
    assert not names_match(market_name("Cerundolo J."), record_name("Francisco Cerundolo"))
    # An unknown initial does not veto a surname match.
    assert names_match((frozenset({"sinner"}), ""), record_name("Jannik Sinner"))


def test_a_past_season_is_fetched_once_and_the_current_one_always(tmp_path, monkeypatch):
    """The steady state is two requests a night, not six."""
    import sqlite3
    from datetime import date
    from app.services.history import odds as mod

    from app.services.history import db as hdb
    conn = sqlite3.connect(":memory:")
    conn.executescript(hdb.SCHEMA)     # sync() stamps history_meta at the end
    mod.ensure_schema(conn)
    year = date.today().year
    conn.execute("""INSERT INTO market_odds (tour, season, match_date, winner_name, loser_name, p_market)
                    VALUES ('atp', ?, '2024-05-01', 'A', 'B', 0.6)""", (year - 2,))
    conn.commit()

    asked = []
    monkeypatch.setattr(mod, "load_season",
                        lambda c, season, tour, client=None, links=None: (asked.append((season, tour)) or
                                                              {"season": season, "tour": tour, "rows": 0, "source": None}))
    monkeypatch.setattr(mod, "link_to_record", lambda c, since: {"linked": 0, "considered": 0, "ambiguous": 0, "unmatched": 0})
    monkeypatch.setattr(mod, "discover_links", lambda client: {})
    out = mod.sync(conn, seasons=[year - 2, year - 1, year], tours=("atp",))
    # The season already held is skipped; the empty one and the live one are not.
    assert (year - 2, "atp") not in asked
    assert (year - 1, "atp") in asked and (year, "atp") in asked
    assert out["skipped"] == [f"atp{year - 2}"]


def test_reloading_a_season_keeps_the_linkage_it_already_has():
    """The nightly re-read of the live season must not erase its own work.

    A REPLACE rewrites the whole row and the two linkage columns are not in
    the insert, so the store used to come back unlinked every night and look
    broken until the linker caught up.
    """
    import sqlite3
    from app.services.history import db as hdb, odds as mod

    conn = sqlite3.connect(":memory:")
    conn.executescript(hdb.SCHEMA)
    mod.ensure_schema(conn)
    row = ("atp", 2026, "2026-07-01", "Wimbledon", "1st Round", 5, "Grass", "Sinner J.", "Nadal R.",
           1.2, 4.5, "average across books", 0.79, "web.archive.org", "Completed")
    ins = """INSERT INTO market_odds
        (tour, season, match_date, tourney, round, best_of, surface, winner_name, loser_name,
         odds_w, odds_l, book, p_market, source, comment)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(tour, match_date, winner_name, loser_name) DO UPDATE SET
            odds_w=excluded.odds_w, odds_l=excluded.odds_l, p_market=excluded.p_market"""
    with conn:
        conn.execute(ins, row)
        conn.execute("UPDATE market_odds SET tml_winner_id='S0AG', tml_loser_id='N409'")
    # The same match comes back with a moved price, as it would a week later.
    with conn:
        conn.execute(ins, row[:9] + (1.15, 5.2, row[11], 0.82) + row[13:])
    got = conn.execute("SELECT odds_w, p_market, tml_winner_id, tml_loser_id FROM market_odds").fetchone()
    assert got[0] == 1.15 and got[1] == 0.82          # the price moved
    assert got[2] == "S0AG" and got[3] == "N409"      # the identity did not
    assert conn.execute("SELECT count(*) FROM market_odds").fetchone()[0] == 1


class _Resp:
    def __init__(self, status, content=b"", text="", url=""):
        self.status_code, self.content, self.text, self.url = status, content, text, url


class _Client:
    """Answers by URL; anything unlisted is a 404."""
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def get(self, url):
        self.asked.append(url)
        return self.pages.get(url) or _Resp(404, b"x" * 1271, url=url)


def test_the_published_link_is_followed_wherever_the_site_moved_the_files(monkeypatch):
    """September 2026: the files moved under an opaque directory and the old
    /2026/2026.xlsx went 404. The index page is the authority for the path."""
    from app.services.history import odds as mod
    index = ('<A HREF="hrjk-85HytOjkhth76j_ygh4jf7/2026/2026.xlsx">2026</A>'
             '<A HREF="hrjk-85HytOjkhth76j_ygh4jf7/2026w/2026.xlsx">2026</A>'
             '<A HREF="hrjk-85HytOjkhth76j_ygh4jf7/2012/2012.xls">2012</A>')
    new = "https://www.tennis-data.co.uk/hrjk-85HytOjkhth76j_ygh4jf7/2026w/2026.xlsx"
    client = _Client({mod.INDEX_PAGES[0]: _Resp(200, text=index, url=mod.INDEX_PAGES[0]),
                      new: _Resp(200, b"x" * 20_000, url=new)})
    links = mod.discover_links(client)
    assert links["2026w/2026.xlsx"] == new
    assert links["2012/2012.xls"].endswith("/hrjk-85HytOjkhth76j_ygh4jf7/2012/2012.xls")
    monkeypatch.setattr(mod, "parse_workbook", lambda content: [{"Winner": "A", "Loser": "B", "Date": "2026-01-01"}])
    rows, source, tried = mod.fetch_workbook(2026, "wta", client, links)
    assert rows and source == "tennis-data.co.uk" and tried == []
    assert client.asked[-1] == new


def test_a_night_with_no_source_says_what_each_one_answered_and_names_an_archive_copys_age(monkeypatch):
    from app.services.history import odds as mod
    monkeypatch.setattr(mod, "parse_workbook", lambda content: [{"Winner": "A", "Loser": "B", "Date": "2026-01-01"}])
    rows, source, tried = mod.fetch_workbook(2026, "atp", _Client({}), {})
    assert rows == [] and source is None
    assert len(tried) == 2 and all("HTTP 404" in t for t in tried)
    wb = mod.WAYBACK.format(path="2026/2026.xlsx")
    client = _Client({wb: _Resp(200, b"x" * 20_000,
                                url="https://web.archive.org/web/20260803192930id_/http://www.tennis-data.co.uk/2026/2026.xlsx")})
    rows, source, tried = mod.fetch_workbook(2026, "atp", client, {})
    assert rows and source == "web.archive.org (captured 2026-08-03)"


def test_a_quiet_night_is_not_an_alarm_but_a_stale_yardstick_is():
    """2026-09-24: both hosts failed for one night with 13,849 rows held and
    the alarm fired as if the yardstick had gone. That is a state the fetcher
    passes through; only staleness or an empty store is a fault."""
    from datetime import date
    from app.services.history.odds import _health
    today = date(2026, 9, 24)
    assert _health({"held": 13849, "last_fresh_read": "2026-09-23"}, today)[0] == "info"
    assert _health({"held": 13849, "last_fresh_read": "2026-09-01"}, today)[0] == "warning"
    assert _health({"held": 13849, "last_fresh_read": None}, today)[0] == "warning"
    assert _health({"held": 0, "last_fresh_read": "2026-09-23"}, today)[0] == "warning"


def test_only_a_direct_read_of_the_live_season_counts_as_fresh(monkeypatch):
    import sqlite3
    from datetime import date
    from app.services.history import db as hdb, odds as mod
    conn = sqlite3.connect(":memory:")
    conn.executescript(hdb.SCHEMA)
    mod.ensure_schema(conn)
    monkeypatch.setattr(mod, "discover_links", lambda client: {})
    monkeypatch.setattr(mod, "link_to_record", lambda c, since: {"linked": 0, "considered": 0, "ambiguous": 0, "unmatched": 0})
    year = date.today().year
    monkeypatch.setattr(mod, "load_season", lambda c, season, tour, client=None, links=None:
                        {"season": season, "tour": tour, "rows": 5, "source": "web.archive.org (captured 2026-08-03)"})
    assert mod.sync(conn, seasons=[year], tours=("atp",))["last_fresh_read"] is None
    monkeypatch.setattr(mod, "load_season", lambda c, season, tour, client=None, links=None:
                        {"season": season, "tour": tour, "rows": 5, "source": "tennis-data.co.uk"})
    assert mod.sync(conn, seasons=[year], tours=("atp",))["last_fresh_read"] == date.today().isoformat()
