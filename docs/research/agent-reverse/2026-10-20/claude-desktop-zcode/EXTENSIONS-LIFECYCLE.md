# EXTENSIONS-LIFECYCLE.md — DXT/MCPB install / update / verify / remove

Terminology in this build: a **desktop extension** is `.dxt` (legacy name) or `.mcpb` (current).
Both are ZIPs with a `manifest.json` at the root (`manifest_version` or deprecated `dxt_version`).
Package identity is `local.dxt` / `local.mcpb` for sideloaded files
(`Nlt(d, r.endsWith(".mcpb") ? "local.mcpb" : "local.dxt")`, `index.chunk-lzaSYO3Q.js@4512700`-ish).

The whole chain lives in `index.chunk-lzaSYO3Q.js` unless noted.

---

## 0. Feature gates (checked before everything)

| gate | function | offset | effect |
|---|---|---|---|
| `extensions.enabled` + `features.isDxtEnabled` | `GHt()` | `@2068040` | global off → `getInstalledExtensions` returns `[]` |
| org policy backend | `KHt()` | `@2068119` | `localExtensionInstallAllowed = hasOrgPolicyBackend() && extensionsEnabled` |
| developer mode | `UHt()` | `@2067735` | `unpackedExtensionInstallAllowed = localExtensionInstallAllowed && developerModeEnabled!==false` |
| signature required | `rri()` | `@4518443` | `K().extensions.signatureRequired` → refuses unsigned |
| directory | `nri()` / `ari()` | `@4518294` / `@4518569` | directory URL `${pO()}/api/organizations/${org}/dxt` |
| auto-update | `isDxtAutoUpdatesEnabled` (default `!0`) | `@1571861` | periodic 21600000 ms (6 h) update sweep |

`isExtensionsEnabled:()=>qy` at `@2067973` is the `Extensions` eipc entry point for all of this.

---

## 1. INSTALL

### 1a. From a local file (drag/drop or file picker)
`Extensions.installDxt(extensionId, dxtFilePath)` → `bJ()` `@4511967`

```
guard: extensions enabled (`Jy()`)             → null + "extensions are disabled; refusing"
UNC check  Pr(r)                                → throw "UNC path not allowed: <path>"
copy to     <userData>/dxt-install-<rand>/package.dxt|.mcpb   (chmod 0600, @4512100)
verify      Tcn(e) = heavy-work "dxtPreview"    → {verified, manifestBytes, iconBytes}
manifest    yy(u)  (manifest.json parse)
consent     bni(manifest) `@4494696` → native message box "Install Extension?"  (skippable with confirm:false)
policy      if extensions.signatureRequired && verified.status!=="signed" → throw unsigned error
identity    source!=="registry" → id must equal Nlt(manifest, "local.mcpb"|"local.dxt")  else
            "Extension identity mismatch: package is \"<x>\", requested install slot is \"<y>\""
blocklist   ani(id, hash, manifest, verified, source) = can_install API   → {blocked:true, reason}
extract     wcn(e, g, {requireSigned:f})  = heavy-work "dxtExtract"      → unzip + zip-slip guards
install     uJ(id, () => Ini(id, manifest, moveDirFrom(g), isInternalDxt))   (per-id async mutex)
record      mJ({id, version, hash, installedAt, certificateFingerprint, manifest, signatureInfo,
                source})  → <userData>/extensions-installations.json  (@4496284)
reload      Lni(id, manifest, internal) → reloadMcpConfiguration + UI events
```

Failure → native error dialog "Couldn't install extension" (`@4512900`-ish) and returns `null`;
temp dir removed in `finally`.

### 1b. From the directory (registry)
`Extensions.installDxtFromDirectory(extensionId, version?)` → `Yni()` `@4514715`

```
getExtension({id}) → manifest, is_internal
consent bni()
URL: `${await getUrlWithDirectoryBase()}/extensions/${encodeURIComponent(id)}/download[/${version}]`
     (@4515187)
download to <temp>/dxt-download-<uuid>.mcpb  (progress events: dispatchExtensionDownloadProgress,
     stage "downloading" → "complete", @4516400)
→ bJ({extensionId, dxtFilePath, confirm:false, isInternalDxt, source:"registry"})
```

### 1c. Unpacked folder (developer mode)
`Extensions.installDxtUnpacked(folderPath)` → `Hni()` `@4507309`

### 1d. Preview flow (UI before install)
`Extensions.installExtensionFromPreview(extensionId, path)` → `bJ({..., source:"local"})`;
the renderer first receives event `previewExtensionInstallation(manifest, path, extensionId, signatureInfo)`
(service event table, `@1596145` area).

---

## 2. VERIFY (signature)

Two verifiers, both in the heavy-work worker:

### 2a. `dxtPreview` / `dxtExtract` (`Wt` `@52842` / `Vt` `@52214`, heavyWorkWorker.js; `Bt` `@51963`, `Kt` `@53397`)
`Bt(path)` (`@51963`) → `require("./dist-CI9lzb1v.js").verifyMcpbFile(path)` → `{status, publisher, issuer, valid_from, valid_to, fingerprint}`.

`dist-CI9lzb1v.js` `Lt()` (`@357067`), trailer tags `MCPB_SIG_V1`/`MCPB_SIG_END` at `@357005`/`@357022`:

```
find trailer "MCPB_SIG_END" (Ft)             → last occurrence
scan back for "MCPB_SIG_V1"  (Pt)            → header
read uint32LE length + PKCS#7 DER signature  (Rt @357000-ish)
asn1.fromDer → pkcs7.messageFromAsn1 → must be signedData, ≥1 certificate
verify({authenticatedAttributes:true}); recompute sha256 of the *unsigned* bytes and
compare to the messageDigest authenticated attribute   → mismatch ⇒ "unsigned"
chain validation:
  darwin : `security verify-cert -c chain.pem -p codeSign`
  win32  : PowerShell X509Chain, RevocationMode=Online, EKU 1.3.6.1.5.5.7.3.3 (code signing)
  else   : `openssl verify -purpose codesigning -CApath /etc/ssl/certs`
status = (leaf CN == issuer CN) ? "self-signed" : "signed"   (+ publisher=CN, issuer=CN,
         valid_from/valid_to, fingerprint=sha256 of cert DER)
```

`Vt()` enforces `requireSigned`: `Extension archive is not signed and a valid signature is required`
→ error text `Extension archive is not signed and a valid signature is required` with code `"DXT_SIGNATURE_REQUIRED"` (heavyWorkWorker.js `Nt` @51910-ish / lza `@2642031`).

Trailer format (recovered from code, `Rt`): `…unsigned zip bytes… || "MCPB_SIG_V1" || uint32LE sigLen || sigBytes || "MCPB_SIG_END"`.

### 2b. Allowlist / blocklist — `can_install`
`ani()` `@4487323` → `checkCanInstall` → `fHa()` `@6510524`

```
POST ${pO()}/api/organizations/${orgId}/dxt/can_install      (uHa @6509996)
body {extensions: {<id>: {extension_id, file_hash, manifest, signature_info, source}}}
→ {results: {<id>: {can_install, reason}}}
batched 100/request, 15 s timeout (eHa)
cache: encrypted via safeStorage under `dxt:allowlistCache:<org>` (cHa/lHa @6509000)
org allowlist switch: GET /api/organizations/<org> → settings.is_desktop_extension_allowlist_enabled
no org / no policy backend ⇒ canInstall=false ("No organization policy service available…")
```

Also `sni()` `@4487729` (sweep) re-checks **every installed** extension from stored metadata
(`extensions-installations.json`), and blocks `dxt_unrecorded` (installed but no record) —
"Unpacked or unregistered extensions are disabled by your organization's policy."
(`@4488400`-ish). Blocked extensions get their pooled/ch-at-lane MCP servers shut down
(`pni`, `dni`, `fni`).

---

## 3. UPDATE

`applyPendingUpdates` / `startDxtUpdateChecks` live in `index.chunk-DaEcYOkw.js`
(5 601 B; `startDxtUpdateChecks` @5529, `isDxtAutoUpdatesEnabled` @942).

```
every 21_600_000 ms, if isDxtAutoUpdatesEnabled:
  getInstalledExtensions(forceReload)
  skip ids starting with  local.dxt / local.mcpb / local.unpacked
  for each: d(id, manifest)
      Uv(id, manifest) = getIsUpdateAvailable   (lza @4516500)
          GET getExtensionVersions({id}) → pick highest version > current (semver gt), 30 min memo
      getCachedUpdate(id)  → skip if cached >= available
      cacheExtensionUpdate(id, version, isInternalDxt)   (index.chunk-2_Kpgj9v.js@~1946)
          download → verify (QH = dxtPreview) → signatureRequired check
          → checkCanInstall(...) must be canInstall
          → extract + write <userData>/Extensions Update Cache/<id>/_update_metadata.json
applyPendingUpdates (on every getInstalledExtensions):
   for each cached update: skip if extension gone / lock held
   → swap directory, record metadata (addExtensionMetadata), rollback on failure
```

`index.chunk-2_Kpgj9v.js` exports `cacheExtensionUpdate`, `getCachedUpdate`, `getCachedUpdates`,
`removeCachedUpdate`; download URL is the same `/extensions/<id>/download/<version>`
(`@4515200`).

Deletion of cached updates also happens when the policy sweep blocks an extension
(`removeCachedUpdate` called from `mni`).

---

## 4. ENABLE / SETTINGS

| method | params | storage |
|---|---|---|
| `Extensions.getExtensionSettings(extensionId)` | — | `<userData>/Claude Extensions Settings/<id>.json` (`Gy`, `@2067900`) |
| `Extensions.setExtensionSettings(extensionId, settings)` | `{isEnabled, …}` | same file; emits `extensionSettingsChanged(extensionId, settings)` |
| `Extensions.getInstalledExtensionsWithState` | — | merges dir listing + settings (`ori` `@4518870`) |
| `Extensions.getAvailableExtensionRuntimes` | — | runtime capability list (`vut`) |
| `Extensions.getManifestCompatibilityResult(manifest)` | manifest | compat check (`sut`) |
| `Extensions.isDirectoryEnabled` / `isDesktopExtensionDirectoryEnabled` / `isDesktopExtensionSignatureRequired` | — | policy mirrors |
| `Extensions.refreshAllowlistCheck` | — | forces `updateAndCheckBlockedExtensions` |
| `Extensions.getExtension(request)` / `getExtensionVersions(request)` | `{id}` | directory API |
| `Extensions.getDirectoryUrl` | — | `${pO()}/api/organizations/<org>/dxt` |
| `Extensions.openExtensionsFolder` / `openExtensionSettingsFolder` | — | `shell.openPath` |
| `Extensions.handleDxtFile(dxtPath)` | path | OS "open with" entry (`TPa`) |
| `Extensions.showInstallDxtDialog` | — | file picker (`Pni`) |

Enabling is not just a flag: `Dni()` shuts down that extension's MCP servers when deleted, and
`Oni()` fires `dispatchExtensionsChanged()` + `McpServerAutoReconnect` for the affected servers.

---

## 5. REMOVE

`Extensions.deleteExtension(extensionId)` → `jni()` `@4498894`

```
withExtensionLock(id)                       (uJ / yni, @4496900)
delete metadata row (Eni) → extensions-installations.json
rm -rf <userData>/Extensions/<id>           (Uy(id))
clearInstalledExtensionsCache()
Dni(id): close pooled servers, shutdown chat-lane MCP servers mapped to extensionId
Oni(): dispatchExtensionsChanged + McpServerAutoReconnect per server
```

Cached update is also removed (`removeCachedUpdate`).

---

## 6. `CustomPlugins` / `LocalPlugins` / `PluginBridgeMcp` eipc → lifecycle stage

Plugin = Claude Code plugin (`.claude-plugin/plugin.json`, may contain skills/agents/commands/
hooks and MCPB servers). Different subsystem from desktop extensions.

### `CustomPlugins` (marketplace-backed plugins) — service table `@1972475`

| method | params | stage |
|---|---|---|
| `addMarketplace` | `input, egressAllowedDomains, pluginContext` | source registration |
| `removeMarketplace` | `name, egressAllowedDomains, pluginContext, backendId` | source removal |
| `refreshMarketplace` | `name, egressAllowedDomains, pluginContext, backendId` | source refresh |
| `listMarketplaces` | `egressAllowedDomains, pluginContext` | list |
| `installPlugin` | `pluginId, egressAllowedDomains, pluginContext` | install |
| `updatePlugin` | `pluginId, egressAllowedDomains, pluginContext` | update |
| `uninstallPlugin` | `pluginId, egressAllowedDomains, pluginContext` | remove |
| `listAvailablePlugins` | `egressAllowedDomains, pluginContext` | browse |
| `listRemotePluginsPage` | `limit, offset` | browse (paged remote) |
| `checkPluginHasLocalChanges` | `pluginId, pluginContext` | verify/dirty check before update |
| `getAndClearMigrationIssues` | — | migration repair |
| `listLocalOrgPlugins` | — | org-pushed plugins |
| `installLocalOrgPlugin` | `name` | install (org) |
| `syncLocalOrgPlugins` | — | update (org) |
| event `localOrgPluginsSynced` | — | — |

### `LocalPlugins` — service table `@1970952`

| method | params | stage |
|---|---|---|
| `getPlugins` | `options, pluginContext` | list |
| `getDownloadedRemotePlugins` | `pluginContext` | list (remote-synced) |
| `syncRemotePlugins` | `pluginContext, options` | update (claude.ai → disk) |
| `materializeEnabledPlugins` | `pluginContext` | enable→materialize |
| `listSkillFiles` | `pluginId, skillName, pluginContext` | inspect skills |
| `uploadPlugin` | `filename, base64Content, replaceExisting, pluginContext, uploadSource` | install (sideload zip) |
| `deletePlugin` | `pluginId, pluginContext` | remove |
| `setPluginEnabled` | `pluginId, enabled, pluginContext` | enable/disable |
| `startPluginOAuthFlow` / `revokePluginOAuth` | `pluginId, cliName, pluginContext` | connector auth |
| `getPluginCliStatus` | `pluginId, pluginContext` | runtime status |
| `setPluginEnvVars` | `pluginId, cliName, values, pluginContext` | runtime config |
| `setPluginOAuthClient` | `pluginId, cliName, clientId, clientSecret, pluginContext` | runtime config |
| `getPluginShimOps` / `getPluginCliBatch` / `setPluginShimPermission` | … | permission shim |
| event `onCliOpAlwaysAllowed(keys)` | | permission |

### `PluginBridgeMcp` — service table `@1972381`

| method | params | stage |
|---|---|---|
| `listServers` | — | enumerate MCP servers contributed by plugins for the desktop host bridge |
| event `changed` | — | — |

Missing MCPB support is explicit: `index.chunk-Bgul06K6.js@2268` logs
`Plugin "<n>" server "<r.name>": config references plugin user configuration (…) —
user_config is not supported on the desktop host bridge; dropping server`.

---

## 7. Marketplace / directory URLs (all S)

| purpose | URL | offset |
|---|---|---|
| extension directory base | `${mainWindowUrl}/api/organizations/<org>/dxt` | lza `@4518575` |
| extension download | `${base}/extensions/<id>/download[/<version>]` | lza `@4515187` |
| extension versions | via `getExtensionVersions` (same base) | lza `@4516500` |
| allowlist / blocklist | `${base-api}/api/organizations/<org>/dxt/can_install` | lza `@6510050` |
| allowlist enabled flag | `${base-api}/api/organizations/<org>` → `settings.is_desktop_extension_allowlist_enabled` | lza `@6510300` |
| bundled skills list (contrast) | `${api}/api/organizations/<org>/skills/list-skills?include_wiggle_skills=true&entrypoint=local-agent` | DLqLwOmD.js `@18484` |
| skills download | `${api}/api/organizations/<org>/skills/download-dot-skill-file?skill_id=…` | DLqLwOmD.js `@18900` |
| first-party plugin marketplaces (hard-coded) | `anthropics/knowledge-work-plugins`, `anthropics/claude-plugins-official`, `anthropics/financial-services`, `anthropics/claude-for-legal`, `anthropics/life-sciences` | lza `@657228` |
| trusted marketplace names | `claude-code-marketplace`, `claude-code-plugins`, `claude-plugins-official`, `anthropic-marketplace`, `anthropic-plugins`, `agent-skills`, `anthropic-agent-skills`, `life-sciences`, `knowledge-work-plugins`, `claude-for-legal`, `claude-for-financial-services`, `financial-services-plugins`, `first-party-plugins`, `claude-tag-plugins`, `anthropic-plugin-directory`, `claude-plugin-directory` | `index.chunk-DNyequwM.js@845182`, lza `@115789` |

`pO()` = `G().getMainWindowUrl()` (`@2887286`), i.e. the signed-in claude.ai origin — not a
separate marketplace host. There is **no** independent public marketplace endpoint in this build.

---

## 8. Stage reached (per subsystem)

| item | packaged | registered | delegated | invoked |
|---|---|---|---|---|
| DXT/MCPB install pipeline | yes | yes (`Extensions` eipc, 24 methods) | heavy-work-worker does extract/verify | **U** — needs a real `.dxt` and user consent; no runtime artifact here |
| Signature verifier (PKCS#7 + OS chain) | yes | yes | yes (heavy-work `dxtPreview`/`dxtExtract`) | **U** |
| can_install allowlist | yes | yes | network POST | **U** (needs org login) |
| Auto-update sweep | yes | yes (6 h timer) | install path | **U** |
| Plugin marketplaces (`CustomPlugins`) | yes | yes (14 methods) | git/zip fetch + materialize | **U** |
| Local plugins (`LocalPlugins`) | yes | yes (16 methods) | `--plugin-dir` into CLI | partially: skills plugin path is delegated (`Bn6onBlX.js@548274`), user plugins same mechanism |
