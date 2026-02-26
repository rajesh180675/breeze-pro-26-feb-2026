from unittest.mock import MagicMock

import pandas as pd

from helpers import optimize_dataframe_dtypes
from session_manager import AppWarmupManager


def test_optimize_dataframe_dtypes_downcasts_and_categories():
    df = pd.DataFrame(
        {
            "f": [1.0 + i for i in range(20)],
            "i": list(range(20)),
            "obj": ["NIFTY"] * 20,
        }
    )
    optimized = optimize_dataframe_dtypes(df)
    assert str(optimized["f"].dtype).startswith("float")
    assert str(optimized["i"].dtype).startswith(("int", "uint"))
    assert str(optimized["obj"].dtype) == "category"


def test_app_warmup_manager_collects_results():
    client = MagicMock()
    client.get_funds.return_value = {"success": True}
    client.get_positions.return_value = {"success": True}
    client.get_order_list.return_value = {"success": True}

    warmup = AppWarmupManager(client)
    warmup.start()

    assert warmup.wait(timeout=2.0)
    assert warmup.get_result("funds") == {"success": True}
    assert warmup.get_result("positions") == {"success": True}
    assert warmup.get_result("orders") == {"success": True}
    assert warmup.errors == {}
