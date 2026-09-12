"""Single entry point: uses Elo when both ratings are given, otherwise ranks."""
from .rank import rank_win_prob
from .elo import elo_win_prob

def predict(rank_x=None, rank_y=None, elo_x=None, elo_y=None,
            surface="Hard", best_of=3, elo_table=None, name_x=None, name_y=None) -> dict:
    """Returns {"p": P(X wins), "model": "elo"|"rank"}.
    If elo_table (an EloTable) and player names are given, surface Elo is looked up."""
    if elo_table is not None and name_x and name_y and elo_x is None and elo_y is None:
        elo_x = elo_table.get(name_x, surface)
        elo_y = elo_table.get(name_y, surface)
    if elo_x is not None and elo_y is not None:
        return {"p": elo_win_prob(elo_x, elo_y, best_of), "model": "elo"}
    if rank_x is None and rank_y is None:
        raise ValueError("need ranks or Elo ratings for both players")
    return {"p": rank_win_prob(rank_x, rank_y, surface, best_of), "model": "rank"}
