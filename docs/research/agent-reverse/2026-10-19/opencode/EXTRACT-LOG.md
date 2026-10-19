# OpenCode lane extraction log

- Input cache: D:\agent-client-staging\opencode-zcode\OpenCode; validated each raw asset by SHA256 and byte count against the dispatch manifest before use. Exact results: [evidence-extracted/PACKAGE-ARTIFACTS.md](evidence-extracted/PACKAGE-ARTIFACTS.md).
- v2.0.32 desktop installer: extracted to D:\agent-client-staging\opencode-zcode\OpenCode\desktop\v2.0.32\extracted-installer\application; inspected PE product/file version, ASAR tree/package.json, main/preload/renderer bundles, and unpacked native resources.
- v2.0.32 CLI TGZ and wrapper TGZ: inspected package contents and executable metadata; ran version/help command set in an isolated temporary HOME/data/config/cache/state root. Commands and scope are listed in PACKAGE-ARTIFACTS.md.
- v2.0.32/v1.19.3 source ZIPs: compared exact inventories and SHA256 for TS/TSX relative paths; used version-pinned source files/line anchors for implementation tracing. Counts are exact-path/hash inventory, not semantic diff.
- REA: attempted analyze_javascript_application on actual app.asar. Strict integrity mode stopped at observed OpenConsole.exe mismatch; record-and-continue attempt timed out at 300 seconds. No successful REA output claimed.
- Dynamic boundary: isolated local server started but no API operation succeeded; server output was discarded and process/port closed. No account credentials or user data were used. Desktop UI/browser runtime remains unobserved.
