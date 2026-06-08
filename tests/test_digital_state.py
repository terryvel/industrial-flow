from industrial_flow.pi.digital_state import decode_negative_istat, unresolved_digital_state


def test_decode_negative_istat_preserves_digital_code():
    raw = (2 << 16) + 15
    decoded = decode_negative_istat(-raw)
    assert decoded is not None
    assert decoded.digital_code == -raw
    assert decoded.digital_set_id == 2
    assert decoded.digital_state_id == 15
    assert decoded.raw_istat == -raw


def test_decode_positive_istat_returns_none():
    assert decode_negative_istat(0) is None
    assert decode_negative_istat(10) is None


def test_unresolved_digital_state_preserves_semantic_reference():
    raw = (5 << 16) + 9
    decoded = decode_negative_istat(-raw)
    info = unresolved_digital_state(decoded)
    assert info.digital_code == -raw
    assert info.digital_set_id == 5
    assert info.digital_state_id == 9
    assert info.digital_state_name is None
    assert info.source == "unresolved"
