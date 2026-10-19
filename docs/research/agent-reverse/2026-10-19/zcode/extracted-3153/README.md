# ZCode 3.15.3 package evidence (checkpoint)

Host: Windows / PowerShell. The desktop installer was downloaded from the Atlas archive release with gh and was not executed. The embedded CJS was read and parsed as data only.

## Verified inputs

See ASSET-HASHES.txt. Three Release assets match the manifest byte-for-byte by size and SHA-256: desktop EXE, extracted runtime CJS, and upstream source ZIP. The source ZIP is commit aac4755666d09fdcd70272fcf063c077a639015f and repository version 3.15.1; it is not the Desktop 3.15.3 source.

## Work completed in this checkpoint

- Static PE resource inventory of the exact EXE, no execution.
- Reused the existing full NSIS extraction because its embedded CJS digest matches the verified Release asset.
- Acorn 8.16.0 parsed the full 15 MB runtime with no syntax failure.
- Captured byte-offset anchors for tool scheduling, background child agents, in-memory task registry, workflow journal/replay data, and SDK Retry-After parsing.
- REA scanned the resources/glm directory and found a partial semantic graph. It also verified the exact CJS artifact identity.
- Strict integrity analysis of the full application extraction reported one mismatch in an unpacked node-pty native companion. The record-and-continue whole-app analysis exceeded the MCP wait limit. Keep that companion untrusted and the ASAR coverage partial.

## Outputs and limits

Current outputs are an evidence checkpoint, not a complete inventory. CJS-MODULE-INDEX.tsv, CJS-STRING-OFFSETS.tsv, CJS-SLICES.md, CJS-FAMILY-HITS.json, RUNTIME-DIFF-ANCHORS.md, ASSET-HASHES.txt, RELEASE-METADATA.md, and EXTRACTION-LOG.md are present. Full FILETREE/PACKAGES inventory and the same-version desktop IPC/UI surfaces remain in progress. No source maps were found in the captured collection index. No R-level runtime result exists.

App ASAR semantic analysis is still pending after a long REA call. We have not verified that each desktop code path is reached in the installed app or that the workflow database is actually initialized.
