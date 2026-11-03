import pandas as pd

from portfolio_optimizer.formatting import num, pct, ratio, styled


def test_german_number_formats():
    assert pct(0.0734) == "7,3 %"
    assert pct(-0.0125, 2) == "-1,25 %"
    assert pct(0.05, 0, signed=True) == "+5 %"
    assert pct(12.5, 0) == "1.250 %"
    assert num(1234567.891) == "1.234.568"
    assert num(1234.5, 1) == "1.234,5"
    assert ratio(0.3721) == "0,37"
    assert pct(None) == num(float("nan")) == "–"


def test_styled_formats_columns():
    df = pd.DataFrame({"Rendite": [0.071], "Sharpe": [0.4567], "Wert": [12345.0]})
    html = styled(df, pct_cols=("Rendite",), ratio_cols=("Sharpe",), num_cols=("Wert",)).to_html()
    assert "7,1 %" in html and "0,46" in html and "12.345" in html
