def available(products, locale):
    return [dict(item) for item in products if item.get("active") is True and item.get("locale") == locale]
