import ast
from pathlib import Path


def _get_method(tree: ast.Module, class_name: str, method_name: str):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return child
    return None


def test_get_india_vix_method_calls_get_quotes_with_nse_cash_params():
    api_path = Path(__file__).resolve().parents[2] / "breeze_api.py"
    tree = ast.parse(api_path.read_text(encoding="utf-8"))
    method = _get_method(tree, "BreezeAPIClient", "get_india_vix")
    assert method is not None, "BreezeAPIClient.get_india_vix() must exist"

    found_quotes_call = False
    found_stock_code = False
    found_exchange = False
    found_product_type = False
    for node in ast.walk(method):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
            and node.func.attr == "get_quotes"
        ):
            found_quotes_call = True
            kw_map = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            if isinstance(kw_map.get("stock_code"), ast.Constant) and kw_map["stock_code"].value == "INDIAVIX":
                found_stock_code = True
            if isinstance(kw_map.get("exchange_code"), ast.Constant) and kw_map["exchange_code"].value == "NSE":
                found_exchange = True
            if isinstance(kw_map.get("product_type"), ast.Constant) and kw_map["product_type"].value == "cash":
                found_product_type = True

    assert found_quotes_call, "get_india_vix() must call self.get_quotes(...)"
    assert found_stock_code, "get_india_vix() must use stock_code='INDIAVIX'"
    assert found_exchange, "get_india_vix() must use exchange_code='NSE'"
    assert found_product_type, "get_india_vix() must use product_type='cash'"
