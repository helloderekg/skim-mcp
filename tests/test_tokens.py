from skim import count_tokens, token_basis


def test_count_positive_and_monotone():
    assert count_tokens("hello world, this is some text") > 0
    assert count_tokens("x " * 1000) > count_tokens("x")


def test_basis_is_string():
    assert isinstance(token_basis(), str) and token_basis()
