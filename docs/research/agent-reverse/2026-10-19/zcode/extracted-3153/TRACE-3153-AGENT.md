# ZCode 3.15.3 Agent/tool/background trace (static)

**Input:** verified runtime CJS SHA-256 `31965ce1d5d4a808ef156784f67996de42ccab335591d2386a61ea8f6f506a54`. Byte offsets are UTF-8. The desktop host/UI attachment to this runtime remains unknown.

```text
model tool call closure
  -> scheduleTools
  -> persist pending tool part [zcode.cjs 13,192,839..13,193,404; persistPendingToolPart token 13,193,022]
  -> state transition + emit tool_queued [qwt 13,205,979..13,210,657; event near 13,207,831]
  -> executeTools [call near 13,208,003]
  -> tool execution/result event/state [UNKNOWN in this closed slice]

spawn child agent [runner region starts ~12,715,173]
  -> emit SubagentSpawned(parent/child IDs) [12,715,173]
  -> on backgrounded: detachParent(), retain child async completion callbacks [12,716,232]
  -> task-port backgroundTask requests registry backgrounding [12,719,281]
  -> completion notification/requeue to parent model context [UNKNOWN from these same-version anchors]

host/renderer subscribes to tool_queued and displays pending part [UNKNOWN]
```

The exact ranges and interpretation are indexed in `CJS-MODULE-INDEX.tsv`, `CJS-STRING-OFFSETS.tsv`, and `CJS-SLICES.md`. Static package presence only; no CJS execution or live UI state observed.
