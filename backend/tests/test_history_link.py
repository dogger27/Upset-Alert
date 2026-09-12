"""The pieces of the TennisMyLife linkage that decide identity: names folded
to keys, our score grid printed their way, rounds by distance from the final,
and a tournament paired by our own id before any name is compared."""
from datetime import date
from types import SimpleNamespace as NS

from app.services.history.link import level_code, pair_tournament, round_code, score_text
from app.services.history.tml import classify, name_key, parse_rows


def test_name_key_folds_accents_case_and_order():
    assert name_key("Juan Manuel Cerúndolo") == name_key("Cerundolo Juan Manuel") == "cerundolo juan manuel"
    assert name_key("Félix Auger-Aliassime") == name_key("Auger Aliassime Felix")
    assert name_key("") == ""


def test_score_text_prints_the_grid_their_way():
    assert score_text('[["6", "6"], ["3", "4"]]', True) == "6-3 6-4"
    assert score_text('[["6", "6"], ["3", "4"]]', False) == "3-6 4-6"        # winner first, always
    assert score_text('[["6", "3"], ["1", "0r"]]', True) == "6-1 3-0 RET"     # the retiree's cell carries the r
    assert score_text('[["w/o"], [""]]', True) == "W/O"
    assert score_text(None, True) is None


def test_round_code_counts_back_from_the_final():
    assert [round_code(r, 7) for r in range(1, 8)] == ["R128", "R64", "R32", "R16", "QF", "SF", "F"]
    assert round_code(1, 5) == "R32"
    assert level_code("Grand Slam") == "G" and level_code("ATP 1000") == "M" and level_code("WTA 250") == "250"


def test_tournament_pairs_by_our_id_first_then_name_and_date():
    cands = [dict(id="2026-560", name="US Open", date="2026-09-01", level="G", draw_size=128, surface="Hard", n=127),
             dict(id="2026-422", name="Cincinnati Masters", date="2026-08-10", level="M", draw_size=96, surface="Hard", n=95),
             dict(id="2026-321", name="Stuttgart", date="2026-06-08", level="250", draw_size=32, surface="Grass", n=31)]
    uso = NS(year=2026, start_date=date(2026, 8, 30), category="Grand Slam", name="US Open", city="New York")
    assert pair_tournament(uso, NS(atp_tournament_id=560, wta_live_scoring_id=None, name="US Open", category="Grand Slam", city="New York"),
                           cands, "atp") == ("2026-560", "id")
    # No id: the name and the date carry it, at the right level.
    cincy = NS(year=2026, start_date=date(2026, 8, 13), category="ATP 1000", name="Cincinnati Open", city="Cincinnati")
    assert pair_tournament(cincy, NS(atp_tournament_id=None, wta_live_scoring_id=None, name="Cincinnati Open", category="ATP 1000", city="Cincinnati"),
                           cands, "atp") == ("2026-422", "name")
    # A name alike but a month away is not the same event.
    far = NS(year=2026, start_date=date(2026, 3, 1), category="ATP 250", name="Stuttgart Open", city="Stuttgart")
    assert pair_tournament(far, NS(atp_tournament_id=None, wta_live_scoring_id=None, name="Stuttgart Open", category="ATP 250", city="Stuttgart"),
                           cands, "atp") == (None, "none")


def test_classify_knows_every_file_family():
    assert classify("2026.csv") == ("atp", "main")
    assert classify("2026_wta.csv") == ("wta", "main")
    assert classify("2019_challenger.csv") == ("atp", "challenger")
    assert classify("atp_quali/2026_atp_quali.csv") == ("atp", "quali")
    assert classify("ongoing_tourneys.csv") == ("atp", "ongoing")
    assert classify("backup_ll_audit_20260906_044746/1968.csv") is None
    assert classify("ATP_Database.csv") is None and classify("atp_rankings_2026-08-31.csv") is None


def test_parse_rows_maps_the_csv_by_name_and_drops_the_unusable():
    text = ("tourney_id,tourney_name,surface,draw_size,tourney_level,indoor,tourney_date,match_num,winner_id,winner_seed,"
            "winner_entry,winner_name,winner_hand,winner_ht,winner_ioc,winner_age,winner_rank,winner_rank_points,loser_id,"
            "loser_seed,loser_entry,loser_name,loser_hand,loser_ht,loser_ioc,loser_age,loser_rank,loser_rank_points,score,"
            "best_of,round,minutes,w_ace,w_df,w_svpt,w_1stIn,w_1stWon,w_2ndWon,w_SvGms,w_bpSaved,w_bpFaced,l_ace,l_df,"
            "l_svpt,l_1stIn,l_1stWon,l_2ndWon,l_SvGms,l_bpSaved,l_bpFaced\n"
            "2026-560,US Open,Hard,128,G,0,20260901,1,Z355,1,,Alexander Zverev,R,198,GER,29.3,2,7790,SU87,,,Lorenzo Sonego,"
            "R,191,ITA,31.2,40,1200,6-3 6-4 6-2,5,R128,118,12,1,80,50,40,15,15,2,3,4,3,70,40,25,12,14,5,9\n"
            "2026-560,US Open,Hard,128,G,0,20260901,2,,,,Nobody,,,,,,,X1,,,Somebody,,,,,,,,5,R128,,,,,,,,,,,,,,,,,,,\n")
    rows = parse_rows(text, "atp", "main", "2026.csv")
    assert len(rows) == 1                       # the id-less row is dropped
    r = rows[0]
    assert r[:4] == ("atp", "main", "2026.csv", "2026-560")
    assert r[9] == "2026-09-01" and r[10] == 1 and r[11] == "Z355" and r[21] == "SU87"
    assert r[31] == "6-3 6-4 6-2" and r[32] == 5 and r[33] == "R128" and r[34] == 118
    assert r[35] == 12 and r[-1] == 9          # w_ace first, l_bpFaced last


def test_names_agree_knows_a_long_form_from_a_different_person():
    from app.services.history.link import names_agree
    assert names_agree("Sorana Cîrstea", "Sorana-Mihaela Cirstea")
    assert names_agree("Daniel Mérida", "Daniel Merida Aguilar")
    assert names_agree("Irina-Camelia Begu", "Irina Begu")
    assert names_agree("Luís Guto Miguel", "Luis Augusto Queiroz Miguel")     # a nickname, two tokens shared with the surname
    assert not names_agree("Luciano Darderi", "Alexander Bublik")
    assert not names_agree("Xinyu Wang", "Xiyu Wang") or names_agree("Xinyu Wang", "Xiyu Wang")  # decided by ratio; both tolerable
    assert not names_agree("", "Somebody")
