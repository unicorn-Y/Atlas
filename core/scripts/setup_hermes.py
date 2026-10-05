"""Install the pinned Hermes fork as an editable checkout.

Hermes is not a pip dependency of atlas-core: the fork refuses wheel/sdist builds, so
``pip install`` of a git URL fails. This script reads ``[tool.atlas.hermes]`` from
``core/pyproject.toml``, clones or updates a checkout (default: ``hermes-agent`` next to
the Atlas repository), moves it to the pinned commit and runs ``pip install -e`` on it.

It refuses to touch a checkout with uncommitted changes. When the checkout is already at
the pin and importable it does nothing, so it is cheap to run on every launch.

Usage: python core/scripts/setup_hermes.py [--dir PATH] [--python EXE] [--no-install]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
REPO = CORE.parent
# Hermes ships deeply nested docs; without long paths Windows checkouts fail.
GIT = ["git", "-c", "core.longpaths=true"]


def read_pin(pyproject: Path = CORE / "pyproject.toml") -> tuple[str, str]:
    hermes = tomllib.loads(pyproject.read_text(encoding="utf-8"))["tool"]["atlas"]["hermes"]
    return str(hermes["repository"]), str(hermes["commit"])


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    result = subprocess.run(
        [*GIT, *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    if check and result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def _installed_from(python: str) -> Path | None:
    result = subprocess.run(
        [python, "-c", "import importlib.util as u; s=u.find_spec('run_agent'); "
                       "print(s.origin if s and s.origin else '')"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    origin = result.stdout.strip()
    return Path(origin).resolve().parent if result.returncode == 0 and origin else None


def ensure_checkout(directory: Path, repository: str, commit: str) -> bool:
    """Put ``directory`` at ``commit``. Returns True when the checkout changed."""
    if not (directory / ".git").exists():
        directory.parent.mkdir(parents=True, exist_ok=True)
        print(f"[hermes] cloning {repository} -> {directory}")
        _git("clone", "--no-checkout", repository, str(directory))
    elif _git("status", "--porcelain", cwd=directory):
        raise SystemExit(
            f"[hermes] {directory} has uncommitted changes; commit or stash them, then rerun.",
        )
    if _git("rev-parse", "HEAD", cwd=directory, check=False) == commit:
        return False
    if not _git("cat-file", "-t", commit, cwd=directory, check=False) == "commit":
        print(f"[hermes] fetching {commit[:10]}")
        _git("fetch", "origin", cwd=directory, check=False)
        if _git("cat-file", "-t", commit, cwd=directory, check=False) != "commit":
            _git("fetch", "origin", commit, cwd=directory)
    print(f"[hermes] checking out {commit[:10]}")
    _git("checkout", "--detach", commit, cwd=directory)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=REPO.parent / "hermes-agent")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--pyproject", type=Path, default=CORE / "pyproject.toml")
    parser.add_argument("--no-install", action="store_true", help="only prepare the checkout")
    args = parser.parse_args(argv)

    repository, commit = read_pin(args.pyproject)
    directory = args.dir.resolve()
    changed = ensure_checkout(directory, repository, commit)
    if args.no_install:
        return 0
    if not changed and _installed_from(args.python) == directory:
        print(f"[hermes] up to date at {commit[:10]}")
        return 0
    print(f"[hermes] installing {directory} (editable)")
    return subprocess.run(
        [args.python, "-m", "pip", "install", "-e", str(directory)], check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
