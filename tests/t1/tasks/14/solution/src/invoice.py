def total_cents(lines):
    return sum(int(line["cents"]) for line in lines if not line.get("void", False))
