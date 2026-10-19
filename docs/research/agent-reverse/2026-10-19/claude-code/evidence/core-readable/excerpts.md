# Core package readable excerpts

These short extracts are from the hash-pinned `@anthropic-ai/claude-code@2.1.302` core TGZ. They are for path/function verification, not a source redistribution. Full member hashes and lengths are in `../01-archive-manifest.json`.

## `package/package.json`

```text
2:   "name": "@anthropic-ai/claude-code",
3:   "version": "2.1.302",
4:   "bin": {
5:     "claude": "bin/claude.exe"
7:   "scripts": {
8:     "postinstall": "node install.cjs",
11:   "engines": {
12:     "node": ">=22.0.0"
23:   "optionalDependencies": {
30:     "@anthropic-ai/claude-code-win32-x64": "2.1.302",
33:   "files": [
34:     "bin/claude.exe",
35:     "install.cjs",
36:     "cli-wrapper.cjs",
37:     "sdk-tools.d.ts"
```

## `package/bin/claude.exe`

This 500-byte archived member is plain shell text (not an MZ PE). Its opening exact lines are:

```text
1: echo "Error: claude native binary not installed." >&2
3: echo "Either postinstall did not run (--ignore-scripts, some pnpm configs)" >&2
4: echo "or the platform-native optional dependency was not downloaded" >&2
7: echo "Run the postinstall manually (adjust path for local vs global install):" >&2
8: echo "  node node_modules/@anthropic-ai/claude-code/install.cjs" >&2
```

## `package/install.cjs`

`placeBinary(src, dest)` at lines 105-123 first tries a hardlink and handles an existing destination by unlink/retry, then copy fallback:

```text
105: function placeBinary(src, dest) {
110:   try {
111:     linkSync(src, dest)
112:   } catch (err) {
113:     if (err.code === 'EEXIST') {
117:       const stub = statSync(dest).size < 4096 ? readFileSync(dest) : null
118:       unlinkSync(dest)
120:         linkSync(src, dest)
122:         try {
123:           copyFileSync(src, dest)
```

Postinstall's target selection begins at line 165; optional dependency resolution is at 198-199; the replacement path is `bin/claude.exe` at line 236 and `placeBinary(src, dest)` is called at 239.

## `package/cli-wrapper.cjs`

The fallback resolver selects the optional package binary at lines 83-112. Its direct spawn and exit mapping are:

```text
131: function main() {
132:   const binaryPath = getBinaryPath()
133:   const result = spawnSync(binaryPath, process.argv.slice(2), {
134:     stdio: 'inherit',
135:     env: { ...process.env, CLAUDE_CODE_INSTALLED_VIA_NPM_WRAPPER: '1' },
144:   if (result.signal) {
147:     const signum = constants.signals[result.signal] ?? 0
148:     process.exit(128 + signum)
150:     process.exit(result.status ?? 1)
```

