"""Preview and install opt-in GitHub Actions workflow templates."""
from __future__ import annotations

from pathlib import Path


WORKFLOW_TEMPLATES: dict[str, dict[str, str]] = {
    "atlas-review": {
        "path": ".github/workflows/atlas-review.yml",
        "label": "Atlas full-repository parallel review",
        "permissions": "contents: read",
        "secret": "DEEPSEEK_API_KEY (repository or organization Actions secret)",
        "content": """name: Atlas repository review
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
          python-version: '3.14'
      - name: Install Atlas CLI
        run: python -m pip install -e ./core
      - name: Review repository
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
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
        "content": """name: Python checks
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
          python-version: '3.14'
      - name: Install project
        run: python -m pip install -e ./core
      - name: Compile Python sources
        run: python -m compileall -q core/atlas
      - name: Run tests
        run: python -m pytest -q core/tests
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
