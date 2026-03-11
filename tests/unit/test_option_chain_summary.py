from option_chain_summary import build_option_chain_summary_payload


def test_summary_payload_includes_expiry_warning_and_premium_check():
    payload = build_option_chain_summary_payload(
        spot=22020,
        atm=22000,
        pcr=1.12,
        max_pain=22000,
        dte=0,
        expected_move=236,
        total_call_oi=120000,
        total_put_oi=135000,
        expiry_strip=[
            {"expiry": "2026-03-26", "atm_iv": 0.28, "expected_move": 236.0},
            {"expiry": "2026-04-02", "atm_iv": 0.22, "expected_move": 280.0},
        ],
    )
    assert payload["show_expiry_warning"] is True
    assert payload["premium_check"]["is_elevated"] is True
    assert payload["cards"][2]["delta"] == "Bullish"


def test_summary_payload_handles_missing_spot_and_single_expiry():
    payload = build_option_chain_summary_payload(
        spot=0,
        atm=22000,
        pcr=0.92,
        max_pain=22000,
        dte=5,
        expected_move=0,
        total_call_oi=1000,
        total_put_oi=900,
        expiry_strip=[{"expiry": "2026-03-26", "atm_iv": 0.18, "expected_move": 236.0}],
    )
    assert payload["cards"][0]["value"] == "—"
    assert payload["premium_check"] is None
    assert payload["show_expiry_warning"] is False
