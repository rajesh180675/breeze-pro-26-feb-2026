import ast
from pathlib import Path


def _get_function(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _is_attr_call(node: ast.AST, root_name: str, attr_name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == root_name
        and node.func.attr == attr_name
    )


def test_get_dashboard_metrics_uses_cache_and_live_sources():
    app_path = Path(__file__).resolve().parents[2] / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))
    fn = _get_function(tree, "get_dashboard_metrics")
    assert fn is not None, "get_dashboard_metrics() must exist in app.py"

    arg_names = [a.arg for a in fn.args.args]
    assert arg_names[:2] == ["client", "cache"], "get_dashboard_metrics signature must be (client, cache)"

    has_india_vix_call = False
    has_option_chain_call = False
    has_cache_get = False
    has_cache_set = False

    for node in ast.walk(fn):
        if _is_attr_call(node, "client", "get_india_vix"):
            has_india_vix_call = True
        if _is_attr_call(node, "client", "get_option_chain"):
            has_option_chain_call = True
        if _is_attr_call(node, "cache", "get"):
            has_cache_get = True
        if _is_attr_call(node, "cache", "set"):
            has_cache_set = True

    assert has_india_vix_call, "Dashboard metrics must fetch INDIA VIX via client.get_india_vix()"
    assert has_option_chain_call, "Dashboard metrics must compute NIFTY PCR/Max Pain from option chain"
    assert has_cache_get, "Dashboard metrics must read from cache"
    assert has_cache_set, "Dashboard metrics must populate cache on misses"


def test_page_dashboard_renders_seven_metric_columns():
    app_path = Path(__file__).resolve().parents[2] / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))
    fn = _get_function(tree, "page_dashboard")
    assert fn is not None, "page_dashboard() must exist in app.py"

    has_get_metrics_call = False
    has_columns_7 = False
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "get_dashboard_metrics":
            has_get_metrics_call = True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "st"
            and node.func.attr == "columns"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == 7
        ):
            has_columns_7 = True

    assert has_get_metrics_call, "page_dashboard() must call get_dashboard_metrics()"
    assert has_columns_7, "page_dashboard() must render top metrics in st.columns(7)"
