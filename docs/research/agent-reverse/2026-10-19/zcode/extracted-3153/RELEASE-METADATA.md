# Release and package metadata

## Desktop installer

- Verified asset: zcode-desktop-v3.15.3-bc8100ba43.exe, 181,367,144 bytes, SHA-256 bc8100ba4377256fbe1531d549b4775f18e3ba21768b6294ca50751cd461faca.
- PE static resource evidence: REA ev_0d6e943812a8cf8f6c73c8824ac8f0668d808de57b7f4cc85c852757fd82f759; complete bounded table, 61 entries examined / 28 leaf resources. No Authenticode verification was performed.
- REA binary overview: ev_711f8e6d9a5a21e984b06cd0da188d083ad3c6819aa6c451cfbda0bfb7f7a854; format PE, architecture x86 (installer), 7 segments, 269 procedures, 239 strings. Static overview only.
- Collection reports an inner NSIS app-64.7z and extracted application tree; reuse was checked against the exact embedded CJS digest. The EXE was not launched, installed, or dynamically observed.

## Electron application

- Manifest path: resources/app.asar.extracted/package.json, 1,785 bytes in the retained ASAR index.
- name @zcode/desktop; version 3.15.3; type module; main out/main/index.js; productName ZCode; production flavor.
- Dependencies identify Electron host/service/provider, @zcode/client, @zcode/rpc, @zcode/server, @zcode/ui, MCP client/core/ext-apps 2.0.0, React 19.2.4, Playwright Core 1.59.1, node-pty, ws, ssh2, and undici.
- Source maps: collection index reports zero. Actual source-map coverage is pending full ASAR inventory.

## Embedded Agent runtime

- Original package path resources/glm/zcode.cjs; 15,127,039 bytes; SHA-256 31965ce1d5d4a808ef156784f67996de42ccab335591d2386a61ea8f6f506a54.
- resources/glm/.node-bundle-meta.json: runtime electron-node; entry zcode.cjs; platform win32-x64; source apps/zcode-cli/packages/cli/dist/zcode.cjs.
- Bundle metadata attributes the source path; it does not prove the internal npm package version or that this file alone is the actual process entry on every launch path.
