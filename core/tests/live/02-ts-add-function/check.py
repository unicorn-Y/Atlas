"""Live scenario 02 checker: kebabCase added with tests; camelCase untouched; node run green."""
import pathlib
import re
import subprocess
import sys

WS = pathlib.Path(sys.argv[1])

problems = []
src = WS / "string_utils.ts"
test = WS / "string_utils.test.ts"
if not src.is_file() or not test.is_file():
    problems.append("string_utils.ts / string_utils.test.ts missing")
else:
    src_text = src.read_text(encoding="utf-8")
    test_text = test.read_text(encoding="utf-8")
    if "export function kebabCase" not in src_text:
        problems.append("kebabCase export missing in string_utils.ts")
    if "export function camelCase" not in src_text:
        problems.append("existing camelCase export was removed")
    kebab_tests = re.findall(r"assert\.\w+\([^;]*kebabCase\([^;]*\)[^;]*\)", test_text)
    if len(kebab_tests) < 3:
        problems.append(f"expected >=3 kebabCase assertions, found {len(kebab_tests)}")
    if 'camelCase("hello_world")' not in test_text and "camelCase('hello_world')" not in test_text:
        problems.append("original camelCase assertion was removed")
    proc = subprocess.run(
        ["node", "string_utils.test.ts"],
        cwd=WS, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if proc.returncode != 0 or "TS-TESTS-OK" not in proc.stdout:
        problems.append(
            f"node run rc={proc.returncode} stdout={proc.stdout[-500:]!r} stderr={proc.stderr[-500:]!r}"
        )
    else:
        # The documented conversions must actually hold.
        (WS / "__kebab_probe.mjs").write_text(
            "import { kebabCase } from './string_utils.ts';\n"
            "const cases = [['helloWorld', 'hello-world'],"
            " ['ParseHTTPResponse', 'parse-http-response'],"
            " ['already-kebab', 'already-kebab']];\n"
            "for (const [input, want] of cases) {\n"
            "  const got = kebabCase(input);\n"
            "  if (got !== want) { console.error(`FAIL ${input} -> ${got}, want ${want}`); process.exit(1); }\n"
            "}\nconsole.log('PROBE-OK');\n",
            encoding="utf-8",
        )
        proc2 = subprocess.run(
            ["node", "__kebab_probe.mjs"],
            cwd=WS, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        (WS / "__kebab_probe.mjs").unlink(missing_ok=True)
        if proc2.returncode != 0 or "PROBE-OK" not in proc2.stdout:
            problems.append(
                f"kebabCase behavior probe failed rc={proc2.returncode}: "
                f"{proc2.stdout[-300:]} {proc2.stderr[-300:]}"
            )

if problems:
    print("CHECK-FAIL")
    for item in problems:
        print("-", item)
    sys.exit(1)
print("CHECK-OK")
