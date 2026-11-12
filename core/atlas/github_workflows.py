"""Preview and install opt-in GitHub Actions workflow templates."""
from __future__ import annotations

from pathlib import Path


#: The Python the workflows ask for. Must satisfy ``requires-python`` in
#: core/pyproject.toml (>=3.11) *and* match the interpreter Atlas is developed and
#: tested against. These templates previously asked for '3.14', which was only ever
#: consistent with a pyproject floor that made `pip install -e ./core` fail on the
#: 3.11 interpreter that actually runs Atlas.
PYTHON_VERSION = "3.11"

#: Pinned so a new ruff release cannot turn a previously-passing job red.
RUFF_VERSION = "0.16.9"

#: Test modules that are green today and pin contracts that have already broken.
#: The full suite is deliberately not here: a clean checkout currently has ~198
#: failures, so running it in CI guarantees a permanently red badge, and a badge
#: that is always red carries no information.
CONTRACT_TESTS = (
    "tests/test_event_contract.py",
    "tests/test_introspect_providers.py",
)

#: ``python-checks`` and ``atlas-ci`` both run the contract tests. They used to
#: spell the two paths out separately, so adding a third test to ``CONTRACT_TESTS``
#: silently left one of the two templates behind. Formatting once from the tuple
#: keeps both honest.
_CONTRACT_TESTS_SH = " \\\n            ".join(CONTRACT_TESTS)

_LINT_TARGETS = (
    "atlas/introspect",
    "atlas/port_guard.py",
    "atlas/api/event_names.py",
    # Added with the §7.9 batch: all of these pass ruff today, so listing them
    # stops the debt from creeping back into code that was clean when written.
    "atlas/log_rotation.py",
    "atlas/telemetry.py",
    "atlas/tts_local.py",
    "atlas/libreoffice.py",
    "atlas/agent/capabilities.py",
    "tests/test_event_contract.py",
    "tests/test_introspect_providers.py",
    "tests/test_log_rotation_telemetry.py",
    "tests/test_office_pdf_and_hooks.py",
)


def _atlas_ci() -> str:
    """The repository's own gate: event contract + scoped lint."""
    lint_targets = " \\\n            ".join(_LINT_TARGETS)
    tests = _CONTRACT_TESTS_SH
    return f"""name: CI

# Two jobs, both fast, each pinning something that has already broken here:
#   contract  the three-source event-name agreement (Python <-> two TS files).
#             It broke silently once: 16 backend events were dropped by the
#             renderer with no error, no log, and no visible symptom.
#   lint      ruff over the paths that are clean today, so the debt stops growing.
#
# The full pytest suite is NOT run. It needs a live model and a warm state DB, and
# a clean checkout currently has ~198 failures. Wiring that in would give a badge
# that is always red, which teaches everyone to ignore it. Turn it on after those
# failures are triaged -- not before.
on:
  push:
    branches: [main, master]
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: ${{{{ github.workflow }}}}-${{{{ github.ref }}}}
  cancel-in-progress: true

jobs:
  contract:
    name: event contract
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '{PYTHON_VERSION}'
          cache: pip
          cache-dependency-path: core/pyproject.toml
      - name: Install
        working-directory: core
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e . pytest
      - name: Event contract and introspection surface
        working-directory: core
        env:
          PYTHONIOENCODING: utf-8
        run: |
          python -m pytest \\
            {tests} \\
            -q -p no:cacheprovider -p no:randomly

  lint:
    name: ruff
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '{PYTHON_VERSION}'
      - name: Install ruff
        run: python -m pip install ruff=={RUFF_VERSION}
      - name: Lint the paths that are clean
        working-directory: core
        run: |
          python -m ruff check \\
            {lint_targets}
"""


WORKFLOW_TEMPLATES: dict[str, dict[str, str]] = {
    "atlas-ci": {
        "path": ".github/workflows/ci.yml",
        "label": "Atlas contract gate (event contract + scoped ruff)",
        "permissions": "contents: read",
        "secret": "none",
        "content": _atlas_ci(),
    },
    "atlas-review": {
        "path": ".github/workflows/atlas-review.yml",
        "label": "Atlas full-repository parallel review",
        "permissions": "contents: read",
        "secret": "DEEPSEEK_API_KEY (repository or organization Actions secret)",
        "content": f"""name: Atlas repository review
on:
  pull_request:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: '{PYTHON_VERSION}'
      - name: Install Atlas CLI
        run: python -m pip install -e ./core
      - name: Review repository
        env:
          DEEPSEEK_API_KEY: ${{{{ secrets.DEEPSEEK_API_KEY }}}}
        run: atlas review --ci --model deepseek-v4.1-flash --output atlas-review.json
      - name: Upload review report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: atlas-review
          path: atlas-review.json
          if-no-files-found: ignore
""",
    },
    "python-checks": {
        "path": ".github/workflows/python-checks.yml",
        "label": "Python lint and test checks",
        "permissions": "contents: read",
        "secret": "none",
        "content": f"""name: Python checks
on:
  push:
  pull_request:
permissions:
  contents: read
jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '{PYTHON_VERSION}'
      - name: Install project
        run: python -m pip install -e ./core
      - name: Compile Python sources
        # Catches syntax errors and bad imports across all 600+ modules in seconds.
        # This is the widest check that is reliably green.
        run: python -m compileall -q core/atlas
      - name: Run contract tests
        working-directory: core
        env:
          PYTHONIOENCODING: utf-8
        run: |
          python -m pytest \\
            {_CONTRACT_TESTS_SH} \\
            -q -p no:cacheprovider -p no:randomly
""",
    },
}


def workflow_preview(workspace: str | Path, template: str) -> dict[str, object]:
    if template not in WORKFLOW_TEMPLATES:
        raise ValueError(f"Unknown workflow template: {template}")
    root = Path(workspace).resolve()
    if not (root / ".git").exists():
        raise ValueError("Select a Git repository before installing a workflow.")
    selected = WORKFLOW_TEMPLATES[template]
    destination = root / str(selected["path"])
    exists = destination.exists()
    existing = destination.read_text(encoding="utf-8", errors="replace") if exists else ""
    return {**selected, "template": template, "destination": str(destination), "exists": exists,
            "existing_content": existing, "content": str(selected["content"])}


def install_workflow(workspace: str | Path, template: str, *, overwrite: bool = False) -> Path:
    preview = workflow_preview(workspace, template)
    destination = Path(str(preview["destination"]))
    if preview["exists"] and not overwrite:
        raise FileExistsError(f"Workflow already exists: {destination}; use --overwrite after reviewing it.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(str(preview["content"]), encoding="utf-8", newline="\n")
    temporary.replace(destination)
    return destination
