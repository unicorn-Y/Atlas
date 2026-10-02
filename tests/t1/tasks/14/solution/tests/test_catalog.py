from src.catalog import available


def test_available_filters_locale_and_inactive():
    assert available([{"id": "a", "locale": "zh-HK", "active": True}], "zh-HK") == [{"id": "a", "locale": "zh-HK", "active": True}]
