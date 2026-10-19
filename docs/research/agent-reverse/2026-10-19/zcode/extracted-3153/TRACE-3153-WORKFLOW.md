# ZCode 3.15.3 workflow journal/replay trace (static)

**Input:** verified runtime CJS SHA-256 `31965ce1d5d4a808ef156784f67996de42ccab335591d2386a61ea8f6f506a54`. Byte offsets are UTF-8.

```text
workflow journal migration SQL region [zcode.cjs 1,515,023..1,543,238]
  -> migration marker 0019_dwf_journal [1,540,263]
  -> dwf_run schema [1,540,320] + input_hash column [1,523,765]
  -> database open / migration application in a running release [UNKNOWN]

workflow replay helper region [12,513,514..12,524,192]
  -> canonical JSON/hash helper and inputHash generation
  -> compare imported/cached actor input hash
  -> throw InputHashMismatch [token 12,524,144] on mismatch
  -> require pure/replay-safe cached result / apply completed node to workflow state [see CJS-SLICES.md; full parent driver call site not closed]
```

Schema strings and helper functions establish bundled mechanisms, not initialized SQLite tables or crash-recovery success. Parent scheduler/transaction driver, child script transport, and live replay remain unknown.
