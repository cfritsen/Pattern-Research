import math
import pandas as pd
from patternlab.regime import year_breakdown


def test_concentration_when_few_years_dominate():
    thin = pd.DataFrame({"year": [2020] * 6 + [2021] * 2 + [2022] * 2,
                         "fwd_ret_5": [0.05] * 6 + [0.01] * 2 + [0.01] * 2})
    top3_share, mean_excl = year_breakdown(thin, 5)
    assert top3_share == 1.0
    assert math.isnan(mean_excl)


def test_even_spread_across_many_years():
    thin = pd.DataFrame({"year": list(range(2000, 2010)), "fwd_ret_5": [0.01] * 10})
    top3_share, mean_excl = year_breakdown(thin, 5)
    assert abs(top3_share - 0.3) < 1e-9
    assert abs(mean_excl - 0.01) < 1e-9