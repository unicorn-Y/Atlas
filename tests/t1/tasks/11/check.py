import json
from pathlib import Path
import sys


def main():
    root = Path(sys.argv[1])
    fixture = Path(__file__).parent / "fixture"
    assert (root / "orders.json").read_bytes() == (fixture / "orders.json").read_bytes(), "input was changed"
    source = json.loads((root / "orders.json").read_text(encoding="utf-8"))
    rows = []
    for order in source:
        if order["cancelled"]:
            continue
        subtotal = max(0, order["subtotal_cents"] - 1000)
        shipping = 0 if subtotal >= 10000 else 800
        rows.append({"id": order["id"], "discount_cents": min(1000, order["subtotal_cents"]), "shipping_cents": shipping, "total_cents": subtotal + shipping, "note": "保留中文"})
    expected = {"currency": "CNY", "unit": "cents", "version": 2, "orders": rows, "grand_total_cents": sum(row["total_cents"] for row in rows)}
    actual = json.loads((root / "delivery.json").read_text(encoding="utf-8"))
    assert actual == expected, "lost conversation constraint"
    assert all(type(row[key]) is int for row in actual["orders"] for key in ("discount_cents", "shipping_cents", "total_cents")), "amount must be integer"
    print("eight-turn constraints: PASS")


if __name__ == "__main__":
    main()
