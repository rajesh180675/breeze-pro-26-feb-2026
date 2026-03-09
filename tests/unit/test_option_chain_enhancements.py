import ast
from pathlib import Path


def _get_function(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def test_option_chain_has_toggleable_chain_options_and_metrics_widgets():
    app_path = Path(__file__).resolve().parents[2] / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))
    fn = _get_function(tree, "page_option_chain")
    assert fn is not None, "page_option_chain() must exist in app.py"

    constants = [n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert "⛓️ Chain Options" in constants
    assert "OI Change % Heatmap" in constants
    assert "PCR Gauge" in constants
    assert "Max Pain Marker" in constants
    assert "Export Chain CSV" in constants
    assert any("OI Change %" in c for c in constants), "OI Change % column must be added for heatmap"
    assert any("🎯" in c for c in constants), "Max pain strike marker must use 🎯 marker"

    has_progress_call = False
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "st"
            and node.func.attr == "progress"
        ):
            has_progress_call = True
            break

    assert has_progress_call, "PCR gauge must be rendered using st.progress()"


def test_option_chain_export_respects_toggle():
    app_path = Path(__file__).resolve().parents[2] / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))
    fn = _get_function(tree, "page_option_chain")
    assert fn is not None

    has_toggle_guarded_export = False
    for node in ast.walk(fn):
        if isinstance(node, ast.If):
            names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            if "show_export_chain" not in names:
                continue
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == "export_to_csv"
                ):
                    has_toggle_guarded_export = True
                    break
    assert has_toggle_guarded_export, "CSV export must be guarded by show_export_chain toggle"
