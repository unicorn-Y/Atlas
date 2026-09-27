# CODEX-ATLAS-P18B-FIX1-REAL-MOUSE-INJECTION-AND-E2E-CLOSEOUT Result

STATUS: PARTIAL — primitive live mouse acceptance is implemented; the P18B-FIX1 Acceptance Gate remains open.
BASE_HEAD: 3976b33df3953e1d68f1fecfaccd328fe8de5aba

## Completed and uploaded

- Reproduced the prior same-process Tk click failure before changing the acceptance test.
- Captured Win32 diagnostics: x64 `MOUSEINPUT` size 32 and `INPUT` size 40; per-monitor DPI awareness; physical virtual-desktop bounds; target HWND/class and focus; cursor coordinates; `SendInput` return count 1 for move/down/up; zero last error after successful calls; low-level mouse hook observed injected move/down/up events.
- The original test created Tk in the same process/thread as the injector. Atlas and that target shared the same PID and integrity token. A separate-process Tk target accepted the unchanged canonical `SendInput` click and invoked its real button callback.
- Reworked `core/tests/test_computer_use.py` so its live Tk target runs in a separate process with an active message loop. The test asserts real click and double-click callbacks, vertical scroll position, right-click behavior, down/up events, drag selection, Unicode keyboard input, clipboard round-trip, screenshot coordinate alignment, window enumeration/focus, and observation output.

## Verification completed

- Before the test correction, the old same-thread Windows test reproduced the reported failure: button callback remained 0.
- A separate-process real-click diagnostic passed: injector PID 58852, target PID 58848, callback count 1.
- `python -m pytest tests/test_computer_use.py -q -s -p no:cacheprovider --basetemp <temp>`: 2 passed on Windows.
- `git diff --check`: passed before commit.

## Acceptance still open

- No production mouse-injection code was changed. The diagnosis indicates the previous live test's same-thread Tk/message-pump setup caused the false negative; the unchanged SendInput path passed against a separate live desktop process. A production change was not justified by the evidence collected so far.
- The Notepad save/read Agent workflow, two-application Agent workflow, observation-conditioned Agent reasoning rounds, mixed P18A/P18B run, packaged/installed GUI workflow, process-residue checks, and taskbook-wide regression suite were not completed.
- Existing move/resize/minimize/maximize/restore live-window assertions were not rerun after the test harness change.
- An exploratory Agent E2E test draft did not save the marker and was removed rather than uploaded as a passing test.

P18B remains unaccepted. P18C remains blocked. No later task was started.
