"""Live scenario 10 checker: the mid-run steer changed the requirement and it was followed."""
import pathlib
import sys

WS = pathlib.Path(sys.argv[1])

problems = []
done = WS / "done.txt"
if not done.is_file():
    problems.append("done.txt missing")
else:
    content = done.read_text(encoding="utf-8").strip()
    if content != "V2-STEERED":
        problems.append(
            f"done.txt={content!r}; expected the steered requirement V2-STEERED "
            f"(old requirement V1 must be replaced)"
        )

if problems:
    print("CHECK-FAIL")
    for item in problems:
        print("-", item)
    sys.exit(1)
print("CHECK-OK")
