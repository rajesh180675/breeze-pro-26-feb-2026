import ast
from pathlib import Path


def _find_pages_assignment(tree):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PAGES":
                    if isinstance(node.value, ast.Dict):
                        return node.value
    return None


def test_pages_registry_wires_paper_trading_handler():
    app_path = Path(__file__).resolve().parents[2] / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))
    pages_dict = _find_pages_assignment(tree)
    assert pages_dict is not None, "PAGES dictionary assignment must exist in app.py"

    page_map = {}
    for key_node, value_node in zip(pages_dict.keys, pages_dict.values):
        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
            page_map[key_node.value] = value_node

    assert "📄 Paper Trading" in page_map
    value_node = page_map["📄 Paper Trading"]
    assert isinstance(value_node, ast.Name)
    assert value_node.id == "page_paper_trading"
