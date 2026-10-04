"""Live scenario 04 checker: config.ini environment= matches the script's real output."""
import pathlib
import subprocess
import sys

WS = pathlib.Path(sys.argv[1])

problems = []
ini = WS / "config.ini"
if not ini.is_file():
    problems.append("config.ini missing")
else:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(WS / "check_env.ps1")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    env_name = ""
    for line in proc.stdout.splitlines():
        if line.startswith("ENV-NAME="):
            env_name = line.split("=", 1)[1].strip()
    if not env_name:
        problems.append(f"could not read ENV-NAME from script output: {proc.stdout!r} {proc.stderr[-200:]!r}")
    text = ini.read_text(encoding="utf-8")
    wanted = f"environment={env_name}"
    if wanted not in text:
        problems.append(f"config.ini lacks line {wanted!r}; actual:\n{text}")
    if "environment=UNKNOWN" in text:
        problems.append("environment= still UNKNOWN")
    # Every other line must be untouched.
    fixture = pathlib.Path(__file__).parent / "workspace" / "config.ini"
    expected = fixture.read_text(encoding="utf-8").replace(
        "environment=UNKNOWN", f"environment={env_name}")
    if text.replace("\r\n", "\n") != expected.replace("\r\n", "\n"):
        problems.append("other lines were modified")

if problems:
    print("CHECK-FAIL")
    for item in problems:
        print("-", item)
    sys.exit(1)
print("CHECK-OK")
