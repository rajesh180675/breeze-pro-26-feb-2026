import ast
from pathlib import Path

from strategies import generate_strategy_legs


def test_generate_strategy_legs_snaps_to_nearest_available_strikes():
    legs = generate_strategy_legs(
        strategy_name="Short Strangle",
        atm_strike=19555,
        strike_gap=50,
        lot_size=25,
        lots=1,
        available_strikes=[19400, 19450, 19500, 19600, 19650],
    )
    strikes = [leg.strike for leg in legs]
    assert strikes == [19650, 19450]


def test_generate_strategy_legs_keeps_gap_offsets_without_available_strikes():
    legs = generate_strategy_legs(
        strategy_name="Bull Call Spread",
        atm_strike=19550,
        strike_gap=50,
        lot_size=25,
        lots=1,
    )
    strikes = [leg.strike for leg in legs]
    assert strikes == [19500, 19600]


def _get_function(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def test_page_strategy_builder_passes_available_strikes_to_generator():
    app_path = Path(__file__).resolve().parents[2] / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))
    fn = _get_function(tree, "page_strategy_builder")
    assert fn is not None, "page_strategy_builder() must exist in app.py"

    keyword_found = False
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "generate_strategy_legs":
            for keyword in node.keywords:
                if keyword.arg == "available_strikes":
                    keyword_found = True
                    break
        if keyword_found:
            break

    assert keyword_found, "page_strategy_builder() must pass available_strikes to generate_strategy_legs()"
