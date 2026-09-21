from support.contracts import TOKEN, _capabilities


def test_client_support_facade_preserves_contract_helper_owner() -> None:
    assert _capabilities.__module__ == "test_client_contract"
    assert isinstance(TOKEN, str)
