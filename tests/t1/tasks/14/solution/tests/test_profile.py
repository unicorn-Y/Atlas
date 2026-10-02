from src.profile import normalize_name


def test_normalize_name():
    assert normalize_name("  ada   lovelace ") == "Ada Lovelace"
