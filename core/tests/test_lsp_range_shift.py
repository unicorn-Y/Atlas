"""Line-shift tests for atlas.lsp.range_shift (C6A LSP wave, subagent E).

Lines are 0-indexed (LSP convention).  ``None`` means "line deleted", which is
what lets the manager's delta filter drop baseline diagnostics whose anchor
line no longer exists.
"""
from __future__ import annotations

from atlas.lsp.range_shift import build_line_shift, shift_baseline


def _diag(line: int, message: str = "boom") -> dict:
    return {
        "range": {
            "start": {"line": line, "character": 4},
            "end": {"line": line, "character": 11},
        },
        "severity": 1,
        "code": "T999",
        "source": "fakeserver",
        "message": message,
    }


# ---- identity ----------------------------------------------------------------

def test_identical_text_is_identity_map():
    text = "a = 1\nb = 2\nc = 3\n"
    shift = build_line_shift(text, text)
    assert [shift(i) for i in range(3)] == [0, 1, 2]


# ---- inserted lines shift diagnostics down -----------------------------------

def test_lines_inserted_above_shift_everything_down():
    pre = "a\nb\nc\n"
    post = "x\ny\na\nb\nc\n"  # two lines inserted at the top
    shift = build_line_shift(pre, post)
    assert [shift(0), shift(1), shift(2)] == [2, 3, 4]


def test_line_inserted_in_middle_shifts_only_below():
    pre = "one\ntwo\nthree\n"
    post = "one\nnew\ntwo\nthree\n"
    shift = build_line_shift(pre, post)
    assert shift(0) == 0
    assert shift(1) == 2
    assert shift(2) == 3


# ---- deleted lines -----------------------------------------------------------

def test_deleted_line_maps_to_none_and_below_lines_move_up():
    pre = "a\nBUG\nb\n"
    post = "a\nb\n"
    shift = build_line_shift(pre, post)
    assert shift(1) is None  # deleted
    assert shift(0) == 0
    assert shift(2) == 1


def test_past_end_anchors_at_last_post_line():
    shift = build_line_shift("a\nb\n", "a\nb\nc\n")
    assert shift(5) == 2  # beyond the pre text: clamped to the last post line


def test_empty_pre_anchors_at_last_post_line():
    shift = build_line_shift("", "fresh\n")
    assert shift(0) == 0


# ---- intra-line edits --------------------------------------------------------

def test_intra_line_edit_drops_that_line_but_keeps_neighbours():
    # Same line count, first line edited: conservative mapping drops the edited
    # line (its diagnostics are re-reported fresh anyway) and keeps the rest.
    shift = build_line_shift("a = 1\nb = 2\n", "a = 2\nb = 2\n")
    assert shift(0) is None
    assert shift(1) == 1


# ---- shift_baseline ----------------------------------------------------------

def test_shift_baseline_drops_deleted_entries_and_shifts_ranges():
    baseline = [_diag(0, "keep"), _diag(1, "deleted-line"), _diag(2, "moves-up")]
    shift = build_line_shift("a\nBUG\nb\n", "a\nb\n")
    shifted = shift_baseline(baseline, shift)
    assert [d["message"] for d in shifted] == ["keep", "moves-up"]
    assert [d["range"]["start"]["line"] for d in shifted] == [0, 1]


def test_shift_baseline_preserves_all_other_fields():
    shifted = shift_baseline([_diag(0, "x")], build_line_shift("a\n", "p\nq\na\n"))
    assert len(shifted) == 1
    d = shifted[0]
    assert d["range"]["start"] == {"line": 2, "character": 4}
    assert d["range"]["end"]["line"] == 2
    assert d["code"] == "T999" and d["severity"] == 1 and d["source"] == "fakeserver"


def test_shift_baseline_skips_non_dict_entries():
    shifted = shift_baseline(["junk", None, _diag(0)], build_line_shift("a\n", "a\n"))
    assert len(shifted) == 1 and shifted[0]["message"] == "boom"
