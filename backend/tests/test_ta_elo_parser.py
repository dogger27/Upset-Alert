"""The Tennis Abstract table parser: header-driven, and forgiving of the page."""
from app.services.rankings import parse_ta_elo_table

PAGE = """
<table><tr><td>Current Elo ratings for the ATP tour. Some prose, 64%, whatever.</td></tr>
<tr><th>Elo&nbsp;Rank</th><th>Player</th><th>Age</th><th>Elo</th><th></th>
    <th>hElo&nbsp;Rank</th><th>hElo</th><th>cElo&nbsp;Rank</th><th>cElo</th><th>gElo&nbsp;Rank</th><th>gElo</th>
    <th></th><th>Peak&nbsp;Elo</th><th>Peak&nbsp;Month</th><th></th><th>ATP&nbsp;Rank</th><th>Log&nbsp;diff</th></tr>
<tr><td>1</td><td><a href="x">Jannik&nbsp;Sinner</a></td><td>24.8</td><td>2321.9</td><td></td>
    <td>1</td><td>2259.3</td><td>1</td><td>2211.8</td><td>1</td><td>2125.5</td><td></td><td>2339.8</td><td>2026-05</td><td></td><td>1</td><td>0</td></tr>
<tr><td>2</td><td>Carlos&nbsp;Alcaraz</td><td>22.9</td><td>2146.8</td><td></td>
    <td>2</td><td>2073.3</td><td>2</td><td></td><td>2</td><td>2014.2</td><td></td><td>2308.5</td><td>2026-03</td><td></td><td>3</td><td>-0.41</td></tr>
<tr><td>3</td><td>Nobody&nbsp;Rated</td><td>30.0</td><td>-</td><td></td><td>3</td><td>1900</td></tr>
</table>
"""


def test_reads_every_column_by_its_header():
    t = parse_ta_elo_table(PAGE)
    assert t[frozenset({"jannik", "sinner"})] == {"elo": 2322, "elo_hard": 2259, "elo_clay": 2212, "elo_grass": 2126}


def test_a_blank_surface_cell_is_none_not_a_crash():
    t = parse_ta_elo_table(PAGE)
    assert t[frozenset({"carlos", "alcaraz"})]["elo_clay"] is None
    assert t[frozenset({"carlos", "alcaraz"})]["elo_hard"] == 2073


def test_a_row_without_an_overall_elo_is_skipped_and_the_prose_ignored():
    t = parse_ta_elo_table(PAGE)
    assert frozenset({"nobody", "rated"}) not in t
    assert len(t) == 2


def test_columns_are_found_by_name_not_position():
    # Drop the Age column entirely: a positional parser would read Elo as Age.
    page = PAGE.replace("<th>Age</th>", "").replace("<td>24.8</td>", "").replace("<td>22.9</td>", "").replace("<td>30.0</td>", "")
    t = parse_ta_elo_table(page)
    assert t[frozenset({"jannik", "sinner"})]["elo"] == 2322
    # And a page that stops printing a surface column reports it as absent.
    page2 = PAGE.replace("<th>gElo</th>", "<th>zElo</th>")
    assert parse_ta_elo_table(page2)[frozenset({"jannik", "sinner"})]["elo_grass"] is None
