from src.invoice import total_cents


def test_total_uses_integer_non_void_lines():
    assert total_cents([{"cents": 9}, {"cents": 7, "void": True}]) == 9
