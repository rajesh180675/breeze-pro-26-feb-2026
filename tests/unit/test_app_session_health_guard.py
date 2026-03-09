import ast
from pathlib import Path


def _get_function(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def test_get_client_contains_throttled_session_health_check():
    app_path = Path(__file__).resolve().parents[2] / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))
    fn = _get_function(tree, "get_client")
    assert fn is not None, "get_client() must exist in app.py"

    check_call_found = False
    session_key_found = False
    interval_found = False

    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "check_session_health":
            check_call_found = True
        if isinstance(node, ast.Constant) and node.value == "session_health_last_check_ts":
            session_key_found = True
        if isinstance(node, ast.Constant) and node.value == 300:
            interval_found = True

    assert check_call_found, "get_client() must call check_session_health()"
    assert session_key_found, "get_client() must persist session_health_last_check_ts in session_state"
    assert interval_found, "get_client() must use 300-second throttling"
