"""Live scenario 03 checker: placeholder swapped in place; CRLF + BOM byte-exact."""
import pathlib
import sys

WS = pathlib.Path(sys.argv[1])
TARGET = WS / "配置目录" / "部署说明.md"

problems = []
if not TARGET.is_file():
    problems.append("配置目录/部署说明.md missing")
else:
    data = TARGET.read_bytes()
    # Exact expected bytes: the original fixture with the single substitution.
    fixture = pathlib.Path(__file__).parent / "workspace" / "配置目录" / "部署说明.md"
    original = fixture.read_bytes()
    expected = original.replace(b"VERSION-PLACEHOLDER", b"2.0.0")
    if b"VERSION-PLACEHOLDER" in data:
        problems.append("placeholder still present")
    if data == expected:
        pass
    else:
        # Diagnose which invariant broke for the evidence log.
        if data[:3] != b"\xef\xbb\xbf":
            problems.append("UTF-8 BOM lost")
        bare_lf = data.count(b"\n") - data.count(b"\r\n")
        if bare_lf:
            problems.append(f"{bare_lf} bare LF line ending(s) (CRLF broken)")
        if data != expected:
            problems.append(
                f"bytes differ from single-substitution expectation "
                f"(orig {len(original)} B, now {len(data)} B, expected {len(expected)} B)"
            )

if problems:
    print("CHECK-FAIL")
    for item in problems:
        print("-", item)
    sys.exit(1)
print("CHECK-OK")
