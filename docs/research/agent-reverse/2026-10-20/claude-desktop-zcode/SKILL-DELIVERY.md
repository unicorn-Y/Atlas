# SKILL-DELIVERY.md — how the six bundled skills reach the model

Chain, with the exact code anchor for each hop. All paths relative to
`extract\_asar\.vite\build\`.

## Hop 0 — packaged

`resources/bundled-skills/`: `manifest.json` + `{docx,pdf,pdf-reading,pptx,xlsx,frontend-design}.skill`
(`_asar\resources\bundled-skills`). Path built by `ge()`:
`join(app.getAppPath(),"resources","bundled-skills")` — **index.chunk-DLqLwOmD.js@15975** (`ge()`; the string "bundled-skills" is at @16038).

## Hop 1 — enumerated / registered in the main process

`_e()` reads and caches the manifest (`@16055`; `readFile(join(ge(),"manifest.json"))` at `@16038`); `B()` maps it to records (`@16208`):

```js
{skillId:"bundled:"+t.name, name:t.name, description:t.description,
 creatorType:"anthropic", source:"anthropic", updatedAt:e.agentSkillsRef,
 enabled:t.tier!=="default_false"}
```

This is the *only* place the manifest is read. There is **no readdir of
`resources/bundled-skills/`** anywhere in the build — the directory is not scanned, the manifest is
the sole index (a `.skill` present on disk but absent from `manifest.json` is invisible; `ve()`
`@16450` even throws `Unknown bundled skill: "<name>"`).

## Hop 2 — seeded to disk

`checkBundledSkillsAtSessionStart()` (`@55705`) → `bundledSkillsSeededHere()` (`@26496`) →
`checkBundledSkills()` (`@53366`) → `_checkBundledSkills()` (`@53620`) → `downloadSkills()` (`@57291`):

- For each enabled bundled skill: `ve(name)` reads `<name>.skill` bytes (`@16460`);
  `e.pm(bytes, dir, …, {archiveKind:"skill", moveExistingAside:true, asideDir})` unzips it.
- Target dir: `<pluginDir>/skills/<name>/`, where `<pluginDir>` =
  `<appData>/<orgId>-<accountId>` or `<appData>/<orgId>-<accountId>-builtins`
  (`getPluginDir()`, `@24792`; suffix chosen by `servesAppShippedOnly()` `@24338`).
- Directory validity is enforced: `ensurePluginStructure()` (`@58239`) removes anything at the top
  level the app did not write, refuses symlinks, and rewrites `.claude-plugin/plugin.json`.
- Drift repair: `bundledSkillDiff()` (`@52086`) compares the on-disk tree with the zip
  (entry list + hashes); if it differs the skill is re-extracted, and the log line is
  `[SkillsPlugin] Bundled skill "x" on disk differs from the app's copy (<detail>); re-extracting it from the app`.
- Leftover staging dirs under `<pluginDir>/.staging` are reaped (`@56000`).

## Hop 3 — handed to Claude Code

`resolveSkillsPluginPath()` — **index.chunk-Bn6onBlX.js@1890053**:

```js
async resolveSkillsPluginPath(){
  await re.t.waitForFirstSync();
  let e=re.t.resolveServedSkills(this.currentOrgId),
      t=await re.t.getPluginPath(e);
  return { path: t===null?null:await jF(t), serving:e };
}
```

Consumed in `setupMcpAndPlugins()` (**@542890**), then pushed into the plugin list:

```js
let L=[]; y&&(L.push({type:"local",path:y}), t.L5.info(`[CCD] Using skills plugin at: ${y}`))   // @548274
…
L.push(... user plugins, remote plugin sdkPaths, ~/.claude plugins )
this.deps.sessionPluginPathsSet(r, V?[]:[...L.map(e=>e.path), ...])
```

Delivery to the CLI is one of two modes (`vS()` **@537634**):

| mode | condition | wire form |
|---|---|---|
| `--plugin-dir` flags | spawning CLI ≥ `Y.f` and `ccd_plugins_over_stdin` off | `--plugin-dir <path>` (or `--plugin-dir-no-mcp`) per plugin |
| stdin initialize | CLI supports `--await-initialize` | plugin bundle in the initialize request; CLI answers `plugins_applied` |

Log line either way: `[CCD] <n> plugin(s) go to Claude Code as --plugin-dir flags (<why>)` /
`… over stdin (initialize request, --await-initialize)`.

Override: if managed settings set `disableSideloadFlags`, the skills plugin dir is **not** passed
and the app says so — `[LocalAgentModeSessionManager] disableSideloadFlags (managed settings,
<path>): host-loop spawn passes no --plugin-dir plugins to Claude Code (…, the bundled skills
plugin included) — the host CLI would refuse the flag. The skill listing keeps their SKILL.md
locations and staged plugin reads are unchanged.` (**index.chunk-BvMaI6NQ.js@388066**).

## Hop 4 — the desktop's own prompt block

Independently of the CLI, the desktop builds `<available_skills>` for its own sessions
(`getForSystemPrompt`, **index.chunk-DLqLwOmD.js@63749**):

- Iterates `manifest.skills` of the served plugin dir.
- Skips `!enabled`, hidden skills, and "built-in manifest residue"
  (`creatorType==="anthropic" && skillId===name && updatedAt===null && !served-names.has(name)`).
- Computes a **Claude Code–safe registered name** (`pH`) because the CLI only accepts
  `[A-Za-z0-9_-]`; collisions downgrade the whole set to per-skill `<location>` entries and log
  `[SkillsPlugin] <n> skills share one Claude Code name (…), so <available_skills> lists each under its own name and path instead of the shared one`.
- Two listing forms (`@66300`+):

  ```
  <skill>
  <name>…</name>
  <description>…</description>
  <location>…/skills/<name>/SKILL.md</location>        ← viaSkillTool=false
  </skill>
  ```
  or
  ```
  <invoke_with>
  Skill tool
  </invoke_with>                                        ← viaSkillTool=true
  ```

  A skill gets `<invoke_with>Skill tool</invoke_with>` only when its name is CLI-safe and unique
  (`registeredName!==undefined`); otherwise it gets an on-disk `<location>` the model must `Read`.

- The wrapper text (`@67776`):

  ```
  <skills_instructions>
  Skills give you specialized instructions and domain knowledge for particular kinds of tasks.
  Before starting a task, check whether one of the skills in <available_skills> below covers it.

  How to use a skill:
  - A skill listed with a <location> is on disk: read <location>/SKILL.md (or <location> itself
    when it names a .md file) with the Read tool and follow its instructions.
  - A skill listed with <invoke_with>Skill tool</invoke_with>: call the Skill tool with the
    skill's <name> exactly as listed (`skill: "<name>"`) and follow the instructions it loads.
    Load such a skill this way rather than by searching for or reading its files: skills refer to
    their own folders with the placeholders `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_SKILL_DIR}`,
    which only the Skill tool fills in …
  Important:
  - Only use skills listed in <available_skills> below
  - Once a skill's instructions are loaded in the current turn, follow them rather than loading
    the skill again
  …
  </skills_instructions>

  <available_skills>
  <skill>…</skill> …
  </available_skills>
  ```

- `disableModelInvocation` is read per skill from its `SKILL.md` front matter
  (`e.gV(join(pluginDir,name,"SKILL.md"), u).disableModelInvocation`, `@64505`). None of the six
  bundles declare it, so all default to invocable.

## Hop 5 — invocation

Two distinct mechanisms, both live for these six:

1. **`Read <location>/SKILL.md`** — the model reads the file like any other file. No host
   involvement beyond file access.
2. **`Skill` tool** — the CLI's own tool. The desktop prompt only *mentions* it; the tool is
   registered by the Claude Code CLI, not by the desktop (no `Skill` registration in the asar's
   tool tables; the strings `<invoke_with>Skill tool</invoke_with>` are prompt text, `@65594`).

Skills' own scripts are then executed by the agent inside the session (Bash/Python), relative to
`${CLAUDE_SKILL_DIR}`.

## What is definitely NOT happening

- No `readdir("resources/bundled-skills")` (grep: only `readdir` on the *target* skill dir, `@26220`).
- No per-skill prompt injection at startup before a session: the block is built per session/spawn.
- No MCP server exposing the skills (the `Skills` eipc service has exactly one event,
  `previewSkillFile(data,filename)`, and zero methods — `EIPC-EVENTS.tsv`,
  `index.chunk-lzaSYO3Q.js@5193169`).
- No network fetch in the consumer build for these six: `De()` (SkillsFetcher) returns `B()`
  immediately when `usesLocalSkillStorage()` is true (`@17411`), which it is
  (`index.chunk-lzaSYO3Q.js@2835187`).

## Stage table

| stage | docx | pdf | pdf-reading | pptx | xlsx | frontend-design |
|---|---|---|---|---|---|---|
| packaged | S | S | S | S | S | S |
| registered (manifest read) | S | S | S | S | S | S |
| seeded to disk | I (code path; needs userData dir) | I | I | I | I | I |
| delegated (`--plugin-dir`) | I (same path for all six) | I | I | I | I | I |
| listed in `<available_skills>` | I | I | I | I | I | I |
| invoked | U | U | U | U | U | U |
