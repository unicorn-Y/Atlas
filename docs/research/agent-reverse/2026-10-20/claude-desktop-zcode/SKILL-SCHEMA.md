# SKILL-SCHEMA.md — `resources/bundled-skills/manifest.json`

Source of truth (read in full):
`D:\Atlas\_research\claude-desktop\2026-10-20\extract\_asar\resources\bundled-skills\manifest.json`
(4 628 bytes). Read by code at:
`extract\_asar\.vite\build\index.chunk-DLqLwOmD.js@16389` — `readFile(join(ge(),"manifest.json"))`
where `ge()` = `join(app.getAppPath(),"resources","bundled-skills")` (`@16038`).

Real file, verbatim top level:

```json
{
  "agentSkillsRef": "1792020044",
  "skills": [ ... 6 entries ... ]
}
```

## Field-by-field

### `agentSkillsRef` — string, `"1792020044"`

- Type: **string** (numeric-looking, but quoted). No schema ever parses it to a number.
- Meaning: a **content stamp / revision id** for the whole bundled skill set. It is *not* a semver.
- Only consumer found: `index.chunk-DLqLwOmD.js@16389`

  ```js
  e.skills.map((t=>({skillId:`${L}${t.name}`, name:t.name, description:t.description,
                     creatorType:"anthropic", source:"anthropic",
                     updatedAt:e.agentSkillsRef, enabled:t.tier!=="default_false"})))
  ```

  It becomes the `updatedAt` of every bundled skill record. Because `updatedAt` is the field the
  delta calculator compares (`calculateDelta`, `@39300`-ish: `if(!n||n.updatedAt!==r.updatedAt)`),
  changing this one string forces a re-download/re-extract of all bundled skills on next sync.
- No `version`/`schemaVersion` key exists. There is no JSON Schema for this file in the app; the
  shape is enforced only by the destructuring above (a malformed file makes `_e()` return `null`,
  `@16430`: `catch{z=null}` → zero bundled skills, no crash).

### `skills` — array of objects, exactly 6 entries

Each element has **exactly three keys**: `name`, `description`, `tier`.

| key | type | real values | consumed as |
|---|---|---|---|
| `name` | string | `docx`, `pdf`, `pdf-reading`, `pptx`, `xlsx`, `frontend-design` | (a) zip filename: ``readFile(join(ge(),`${e}.skill`))`` (`@16520`); (b) directory name inside the zip; (c) `skillId` = `"bundled:"+name` (`L="bundled:"`, `@15914`); (d) `<available_skills>` `<name>` if no Claude-Code-name collision |
| `description` | string | long prose (the same text as SKILL.md front-matter `description`) | injected verbatim into the model prompt `<skill><description>…` (`@64109`+). Also the trigger mechanism — there is no separate trigger field |
| `tier` | string | `"always"` for all 6 | only comparison in code: `enabled: t.tier!=="default_false"` (`@16414`) |

#### `tier`
Boolean-like **allow-list filter**, evaluated once when the record is built:

```js
enabled: t.tier!=="default_false"
```

- `"always"` → enabled (all six bundled entries).
- Any value other than `"default_false"` → enabled, including typos, `null`, or a missing key.
  Only the exact string `"default_false"` disables an entry.
- The string `"default_false"` appears **nowhere else** in the bundles (grep across `_asar`:
  single hit at `index.chunk-DLqLwOmD.js@16422`). No bundled skill uses it today; it is a
  packaging-time kill switch.

### Keys that do NOT exist (and where their equivalents live)

| Not in manifest | Where the real value comes from |
|---|---|
| `version` | none. The zip has no version; identity is `(name, agentSkillsRef)`. Skill catalog entries get `updatedAt` = `agentSkillsRef`. Individual `SKILL.md` front matter has only `name`, `description`, `license` — no `version` in any of the 6. |
| `trigger` | the `description` string itself. Model-side selection is description-based (prompt says "Only use skills listed in `<available_skills>`", `@67776`). |
| `entry_point` | implied: `<name>/SKILL.md` at the zip root. `findSkillMd` (`@1552`) looks for `SKILL.md` at root or `<dir>/SKILL.md`. |
| `scripts` | discovered at read time from the extracted directory; not declared. |
| `permissions` / `tools` | none. Skill code runs with the session's tools. |

## Packaging contract (what a `.skill` must contain)

Verified by unzipping all six (see `skills-extracted/…` and `SKILL-CONTAINER-LEDGER.tsv`):

- ZIP with **one top-level directory** named exactly as `manifest.skills[].name`.
- `<name>/SKILL.md` at the root of that directory — required (`validate.py`-style check is not
  used here; the pre-seed check is `ut()` at `@21994`: throws "Couldn't find SKILL.md in this file.").
- Exactly one skill per archive — `ut()` rejects multi-skill zips:
  `"This file contains more than one skill. Upload each skill separately."` (`@22090`).
- All six also ship `LICENSE.txt`; 5 of 6 ship `scripts/`; 4 of 6 ship the 41-file OOXML XSD tree
  under `scripts/office/schemas/` (docx, pptx, xlsx and partially pdf — pdf has none).

Limits that apply to this manifest's payload (constants in `index.chunk-DLqLwOmD.js`):

| constant | value | offset | applies to |
|---|---|---|---|
| `he=2e3` | 2000 entries | `@15920` | max entries when enumerating a bundled archive (`maxEntries:he`) |
| `H=8388608` | 8 MiB | `@18565` | max bundle/`.skill` archive size accepted |
| `je=2097152` | 2 MiB | `@18576` | per-file cap inside the archive |
| `Ae=255` | 255 chars | `@18550` | max skill name length (`Fe()`) |
| description cap | `t.t` (see `Re()` `@21700`) | — | description length enforced for user skills; bundled descriptions are trusted as shipped |

## Registration path (packaged → registered → delegated → invoked)

```
resources/bundled-skills/manifest.json          (packaged)
        │  _e()  readFile+JSON.parse                         DLqLwOmD.js@16389
        ▼
B() → [{skillId:"bundled:<name>", name, description,
        creatorType:"anthropic", source:"anthropic",
        updatedAt:"1792020044", enabled:tier!=="default_false"}]   @16380
        │  bundledSkillsSeededHere()  — only when tier-enabled        @51936
        ▼
seedBundledSkill → ve() reads <name>.skill → e.pm(...) unzip into
   <userData>/<org>-<account>[-builtins]/skills/<name>/            @16620..16800
        │  checkBundledSkillsAtSessionStart() re-extracts if the on-disk
        │  copy differs from the zip (bundledSkillDiff)                @54500
        ▼
getPluginPath() returns the plugin dir; --plugin-dir <dir> to Claude Code
                                                                   Bn6onBlX.js@548274
        ▼
CLI loader publishes the skill; the desktop ALSO builds its own
<available_skills> prompt block from the manifest                    DLqLwOmD.js@63749
        ▼
model reads SKILL.md (Read tool) or calls Skill tool by name
```

### Gating that decides whether the six are served at all

Two independent switches, both must be on:

1. **Deployment/policy switch** — `resolveServedSkills` (`@24338`):
   `served ∈ {"none","app_shipped","synced"}`. Bundled skills only seed when
   `served==="app_shipped"` (`bundledSkillsSeededHere` returns `[]` unless
   `t || usesLocalSkillStorage()`, `@51936`). In the shipped consumer build
   `usesLocalSkillStorage()` returns **`true`** (`index.chunk-lzaSYO3Q.js@2835187`), so the
   local-storage branch is taken and the bundled zip is the catalog source.
2. **Policy key `disableBundledSkills`** — `index.chunk-lzaSYO3Q.js@724139`:
   `failClosedValue:!0`, exposed as "Disable bundled skills and workflows". When true it sets
   `CLAUDE_CODE_DISABLE_BUNDLED_SKILLS:"1"` for the CLI (`@2111240`) — that gates the *CLI's own*
   bundled set; the desktop manifest path is gated by the served mode above.

Additionally, `m` (a "docs tools present" flag) plus `h&&!g&&n.name===qe` pulls `docx` out of the
list into a special `se` sentence (`@64109`+) that tells the model to use `doc_*` tools and only
read the docx skill for comment authoring — i.e. even a served docx skill can be *delisted but
still readable*.

### Stage reached in this build

| stage | reached? | evidence |
|---|---|---|
| packaged | yes | 6 `.skill` + manifest present in `_asar\resources\bundled-skills` |
| registered | yes (static) | `DLqLwOmD.js@16380`, `@51936`, `@54500` enumerate and seed from the manifest |
| delegated | yes (static) | `Bn6onBlX.js@548274` pushes the skills plugin path into `--plugin-dir` |
| invoked | **U** — cannot prove from statics alone; requires a signed-in account to create the userData skills dir and a session spawn to observe. No runtime artifact in this extract shows a session that actually loaded them. |
