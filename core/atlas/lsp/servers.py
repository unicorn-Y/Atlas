# Ported from NousResearch/hermes-agent agent/lsp/servers.py @ 562ad75baec0c8360f6ce2d48b7d9de56506956c (MIT)
"""Server registry — per-language LSP server definitions.

Each :class:`ServerDef` matches files (by extension or basename for
extensionless files like ``Dockerfile``), resolves a project root, and
assembles the spawn command.  Atlas never auto-installs: binary probing goes
through :mod:`atlas.lsp.availability`, and a miss yields ``None`` (the service
layer logs it and surfaces a Chinese install hint).  Nothing here probes
binaries until a file in that language is actually edited.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from atlas.lsp._proc import child_env
from atlas.lsp.availability import find_binary
from atlas.lsp.workspace import nearest_root

logger = logging.getLogger("atlas.lsp.servers")

# LSP languageId for ``textDocument/didOpen``, as language → extensions.  A few
# servers (typescript-language-server, vue-language-server) refuse wrong IDs.
_EXTS_BY_LANGUAGE: Dict[str, Sequence[str]] = {
    "python": (".py", ".pyi"),
    "typescript": (".ts", ".mts", ".cts"),
    "typescriptreact": (".tsx",),
    "javascript": (".js", ".mjs", ".cjs"),
    "javascriptreact": (".jsx",),
    "vue": (".vue",), "svelte": (".svelte",), "astro": (".astro",),
    "go": (".go",), "rust": (".rs",),
    "ruby": (".rb", ".rake", ".gemspec", ".ru"),
    "c": (".c", ".h"),
    "cpp": (".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx"),
    "csharp": (".cs", ".csx"), "fsharp": (".fs", ".fsi", ".fsx"),
    "swift": (".swift",), "java": (".java",), "kotlin": (".kt", ".kts"),
    "yaml": (".yaml", ".yml"), "json": (".json",), "jsonc": (".jsonc",),
    "lua": (".lua",), "php": (".php",), "blade": (".blade.php",), "prisma": (".prisma",), "dart": (".dart",),
    "ocaml": (".ml", ".mli"),
    "shellscript": (".sh", ".bash", ".zsh"),
    "terraform": (".tf", ".tfvars"),
    "latex": (".tex",), "bibtex": (".bib",), "gleam": (".gleam",),
    "clojure": (".clj", ".cljc", ".edn"), "clojurescript": (".cljs",),
    "nix": (".nix",), "typst": (".typ", ".typc"), "haskell": (".hs", ".lhs"),
    "julia": (".jl",), "elixir": (".ex", ".exs"), "zig": (".zig", ".zon"),
    "dockerfile": (".dockerfile",),
    "powershell": (".ps1", ".psm1", ".psd1"),
}
LANGUAGE_BY_EXT: Dict[str, str] = {ext: lang for lang, exts in _EXTS_BY_LANGUAGE.items() for ext in exts}

_SpawnFn = Callable[[str, "ServerContext"], Optional["SpawnSpec"]]
_RootFn = Callable[[str, str], Optional[str]]


@dataclass
class SpawnSpec:
    """Result of resolving a server for a file (``None`` means skip)."""
    command: List[str]
    workspace_root: str
    cwd: str
    env: Dict[str, str] = field(default_factory=dict)
    initialization_options: Dict[str, Any] = field(default_factory=dict)
    seed_diagnostics_on_first_push: bool = False


@dataclass
class ServerDef:
    """One language server: ``resolve_root(file, ws)`` → per-server root or ``None`` to skip;
    ``build_spawn(root, ctx)`` → :class:`SpawnSpec` or ``None`` when the binary can't be found."""
    server_id: str
    extensions: Tuple[str, ...]
    resolve_root: _RootFn
    build_spawn: _SpawnFn
    seed_first_push: bool = False
    description: str = ""
    # Server handles ``workspace/didChangeWorkspaceFolders``: one process serves every project root
    # (git worktrees included) as extra workspaceFolders instead of one process per root.
    multi_root: bool = False
    # didOpen languageId; "" = derive from LANGUAGE_BY_EXT (custom servers name theirs in config).
    language_id: str = ""

    def matches(self, file_path: str) -> bool:
        return _file_ext_or_basename(file_path) in self.extensions


@dataclass
class ServerContext:
    """User policy passed into :meth:`ServerDef.build_spawn` (install strategy, overrides).
    ``install_strategy`` is kept for config compatibility only — Atlas never installs, so it
    merely flows through as a probe-mode switch."""
    workspace_root: str
    install_strategy: str = "auto"  # "auto" | "manual" | "off" — probe-only, never installs
    binary_overrides: Dict[str, List[str]] = field(default_factory=dict)
    env_overrides: Dict[str, Dict[str, str]] = field(default_factory=dict)
    init_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Whether the server may load code the project ships (see workspace.is_trusted_workspace).
    # Defaults closed: a context built without a trust decision must never run the repo's code.
    trusted: bool = False


# ---- helpers ----

# Multi-part extensions that name a different language than their last segment: ``os.path.splitext``
# would reduce ``home.blade.php`` to ``.php`` and hand Blade templates to the plain-PHP server.
_COMPOUND_EXTS = (".blade.php",)


def _file_ext_or_basename(path: str) -> str:
    """Lower-cased extension (compound ones first), or the full basename for extensionless files (``Dockerfile``)."""
    base = os.path.basename(path)
    lower = base.lower()
    return next((c for c in _COMPOUND_EXTS if lower.endswith(c)), None) or os.path.splitext(base)[1].lower() or base


def _which(*names: str) -> Optional[str]:
    """Return the full path of the first command found on PATH."""
    return next((p for n in names if (p := shutil.which(n))), None)


def _root_or_workspace(file_path: str, workspace: str, markers: Sequence[str], excludes: Sequence[str] = ()) -> Optional[str]:
    """``nearest_root`` with workspace fallback; ``None`` iff an exclude marker hit."""
    ceiling = os.path.dirname(workspace) if workspace else None
    found = nearest_root(file_path, markers, excludes=excludes, ceiling=ceiling)
    if found is None and excludes and nearest_root(file_path, markers, ceiling=ceiling) is not None:
        # None is ambiguous with excludes configured: a hit without them means
        # the exclude fired (gated off); otherwise fall back to the workspace.
        return None
    return found or workspace


def _markers_root(markers: Optional[Sequence[str]], excludes: Sequence[str] = ()) -> _RootFn:
    """Root resolver over marker files; ``None`` markers means "always the workspace root"."""
    if markers is None:
        return lambda fp, ws: ws
    return lambda fp, ws: _root_or_workspace(fp, ws, markers, excludes=excludes)


def _find_binary(ctx: ServerContext, server_id: str, which: Sequence[str]) -> Optional[str]:
    """Config override → PATH probe (never installs); ``None`` when nothing resolves."""
    return find_binary(ctx.binary_overrides.get(server_id), which)


def _make_spec(root: str, ctx: ServerContext, server_id: str, command: List[str],
               base_init: Optional[Dict[str, Any]] = None, seed: bool = False) -> SpawnSpec:
    init = ctx.init_overrides.get(server_id, {}) if base_init is None else {**base_init, **ctx.init_overrides.get(server_id, {})}
    env = child_env()
    env.update(ctx.env_overrides.get(server_id, {}))
    return SpawnSpec(command, root, root, env=env,
                     initialization_options=init, seed_diagnostics_on_first_push=seed)


def _simple_spawn(server_id: str, which: Sequence[str], args: Sequence[str] = (),
                  base_init: Optional[Dict[str, Any]] = None,
                  seed: bool = False, untrusted_init: Optional[Dict[str, Any]] = None) -> _SpawnFn:
    """Build a spawn function for the common single-binary server shape; ``untrusted_init`` replaces
    ``base_init`` in an untrusted workspace (the server's own switch for not loading project code)."""
    def build(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
        bin_path = _find_binary(ctx, server_id, which)
        init = base_init if ctx.trusted or untrusted_init is None else untrusted_init
        return None if bin_path is None else _make_spec(root, ctx, server_id, [bin_path, *args], init, seed)
    return build


# ---- bespoke spawn builders ----

def _spawn_pyright(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _find_binary(ctx, "pyright", ("pyright-langserver", "pyright"))
    if bin_path is None:
        return None
    # If we got the cli ``pyright``, the langserver is its sibling — same suffix, since on Windows
    # the bare sibling is npm's unrunnable POSIX shim.
    stem, suffix = os.path.splitext(os.path.basename(bin_path))
    if stem == "pyright":
        sibling = os.path.join(os.path.dirname(bin_path), f"pyright-langserver{suffix}")
        if os.path.exists(sibling):
            bin_path = sibling
    # Point pyright at the project venv; its default "python on PATH" rarely is.  Pyright executes
    # this interpreter, so a checkout's own venv is only used when the workspace is trusted.
    py = _detect_python(root if ctx.trusted else None)
    return _make_spec(root, ctx, "pyright", [bin_path, "--stdio"], {"python": {"pythonPath": py}} if py else {})


def _detect_python(root: Optional[str]) -> Optional[str]:
    # Pyright needs the project's dependencies, not Atlas's runtime packages.  ``VIRTUAL_ENV`` is the
    # operator's own environment; ``root`` (the project's .venv/venv) is None for an untrusted workspace.
    # Fallback is Atlas's own interpreter.
    project = (os.path.join(root, ".venv"), os.path.join(root, "venv")) if root else ()
    venvs = [v for v in (os.environ.get("VIRTUAL_ENV"), *project) if v]
    paths = (os.path.join(v, sub) for v in venvs for sub in ("bin/python", "bin/python3", "Scripts/python.exe"))
    project_python = next((p for p in paths if os.path.exists(p)), None)
    return project_python if project_python is not None else sys.executable


_warned_once: set = set()


def _warn_once(key: str, message: str) -> None:
    """Log ``message`` at WARNING the first time ``key`` is seen in this process."""
    if key not in _warned_once:
        _warned_once.add(key)
        logger.warning(message)


def _spawn_bash_ls(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _find_binary(ctx, "bash-language-server", ("bash-language-server",))
    if bin_path is None:
        return None
    # bash-language-server delegates diagnostics to shellcheck; without it the
    # server runs but never reports anything.  Warn once so the gap is visible.
    if _which("shellcheck") is None:
        _warn_once("shellcheck", "bash-language-server: 未在 PATH 上找到 shellcheck，Shell 诊断将为空；"
                   "请安装 shellcheck（如 scoop install shellcheck 或 apt install shellcheck）。")
    return _make_spec(root, ctx, "bash-language-server", [bin_path, "start"])


_VUE_TUNNEL_MSG = (
    "vue-language-server: 检测到 @vue/language-server 3.x，它只在客户端托管的 tsserver 隧道下工作而 Atlas 不提供该隧道，"
    "已跳过；请改用 2.x 版本（npm install -g @vue/language-server@2）后重启 Atlas。"
)
_VUE_TSDK_MSG = (
    "vue-language-server: 服务器旁及项目 node_modules 下都未找到 JavaScript 版 TypeScript SDK"
    "（typescript/lib/typescript.js），已跳过 Vue 诊断；请安装 TypeScript（npm install -g typescript）后重启 Atlas。"
)


def _node_modules_trees(bin_path: str, root: Optional[str]) -> List[str]:
    """``node_modules`` trees that may hold a server and its TypeScript SDK: the launcher's own tree
    (symlinks resolved), then the project's (``root`` None: the launcher tree only, for TypeScript's
    SDK pin in an untrusted workspace, whose own JavaScript must not load)."""
    trees: List[str] = []
    real = os.path.realpath(bin_path)
    marker = f"{os.sep}node_modules{os.sep}"
    if (idx := real.rfind(marker)) >= 0:
        trees.append(real[: idx + len(marker) - 1])
    if root:
        trees.append(os.path.join(root, "node_modules"))
    return trees


def _vue_server_major(trees: Sequence[str]) -> int:
    """Major version of the first ``@vue/language-server`` found in ``trees``; 0 when unreadable."""
    import json
    for tree in trees:
        try:
            with open(os.path.join(tree, "@vue", "language-server", "package.json"), encoding="utf-8-sig") as fh:
                return int(str(json.load(fh).get("version", "")).split(".")[0])
        except (OSError, ValueError):
            continue
    return 0


def _typescript_sdk_dir(trees: Sequence[str]) -> Optional[str]:
    """First ``typescript/lib`` in ``trees`` holding a JS ``typescript.js`` (TypeScript 7+ ships none)."""
    cands = (os.path.join(tree, "typescript", "lib") for tree in trees)
    return next((c for c in cands if os.path.isfile(os.path.join(c, "typescript.js"))), None)


def _spawn_vue(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    """Spawn @vue/language-server 2.x self-hosting TypeScript (``hybridMode`` off, explicit ``tsdk``)."""
    bin_path = _find_binary(ctx, "vue-language-server", ("vue-language-server",))
    if bin_path is None:
        return None
    trees = _node_modules_trees(bin_path, root)
    if _vue_server_major(trees) >= 3:
        _warn_once("vue-tunnel", _VUE_TUNNEL_MSG)
        return None
    tsdk = _typescript_sdk_dir(trees)
    if tsdk is None:
        _warn_once("vue-tsdk", _VUE_TSDK_MSG)
        return None
    return _make_spec(root, ctx, "vue-language-server", [bin_path, "--stdio"],
                      {"typescript": {"tsdk": tsdk}, "vue": {"hybridMode": False}})


_TS_UNTRUSTED_MSG = (
    "typescript-language-server: 服务器旁未找到 TypeScript SDK，且本工作区不受信任（不加载其自带的"
    " node_modules/typescript），已跳过诊断；请安装 TypeScript（npm install -g typescript-language-server typescript），"
    "或将该工作区列入 lsp.trusted_workspaces。"
)


def _spawn_typescript(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    """typescript-language-server loads the workspace's own ``node_modules/typescript`` unless
    ``tsserver.path`` names another, so an untrusted workspace is pinned to the launcher's copy."""
    bin_path = _find_binary(ctx, "typescript", ("typescript-language-server",))
    if bin_path is None:
        return None
    base: Dict[str, Any] = {}
    if not ctx.trusted:
        sdk = _typescript_sdk_dir(_node_modules_trees(bin_path, None))
        if sdk is None:
            _warn_once("ts-untrusted", _TS_UNTRUSTED_MSG)
            return None
        base = {"tsserver": {"path": sdk}}
    return _make_spec(root, ctx, "typescript", [bin_path, "--stdio"], base, seed=True)


def _atlas_data_dir() -> str:
    """Atlas data dir: ``ATLAS_DATA_DIR`` when set, else ``~/.atlas``."""
    return os.environ.get("ATLAS_DATA_DIR", str(Path.home() / ".atlas"))


def _find_pses_bundle(ctx: ServerContext) -> Optional[str]:
    """Locate the PowerShellEditorServices bundle dir (release zip, manual install).  Resolution order:
    ``lsp.servers.powershell.command[0]`` when a directory, ``init_overrides["powershell"]["bundlePath"]``,
    ``PSES_BUNDLE_PATH`` env, then ``<ATLAS_DATA_DIR>/lsp/PowerShellEditorServices``."""
    override = ctx.binary_overrides.get("powershell")
    init = ctx.init_overrides.get("powershell", {})
    candidates = [
        override[0] if override else None,
        str(init["bundlePath"]) if isinstance(init, dict) and init.get("bundlePath") else None,
        os.environ.get("PSES_BUNDLE_PATH"),
        os.path.join(_atlas_data_dir(), "lsp", "PowerShellEditorServices"),
    ]
    for cand in filter(None, candidates):
        # Accept either the bundle root or the inner module dir.
        if os.path.isfile(os.path.join(cand, "PowerShellEditorServices", "Start-EditorServices.ps1")):
            return cand
        if os.path.isfile(os.path.join(cand, "Start-EditorServices.ps1")):
            return os.path.dirname(cand)
    return None


_PSES_MISSING_MSG = (
    "powershell: 已找到 pwsh，但缺少 PowerShellEditorServices bundle；请从 "
    "https://github.com/PowerShell/PowerShellEditorServices/releases 下载 release zip 解压安装，"
    "并将 lsp.servers.powershell.command 指向该目录，或直接解压到 <Atlas 数据目录>/lsp/PowerShellEditorServices。"
)


def _spawn_powershell_es(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    """Spawn PowerShellEditorServices: needs a ``pwsh``/``powershell`` host plus the module bundle."""
    pwsh = _which("pwsh", "powershell")
    if pwsh is None:
        return None
    bundle = _find_pses_bundle(ctx)
    if bundle is None:
        _warn_once("pses-bundle", _PSES_MISSING_MSG)
        return None
    start_script = os.path.join(bundle, "PowerShellEditorServices", "Start-EditorServices.ps1")
    # PSES writes connection info to the session details file on startup.
    session_dir = atlas_lsp_session_dir()
    inner = (
        f"& '{start_script}' -BundledModulesPath '{bundle}' "
        f"-LogPath '{os.path.join(session_dir, 'pses.log')}' "
        f"-SessionDetailsPath '{os.path.join(session_dir, f'pses-session-{os.getpid()}.json')}' "
        f"-FeatureFlags @() -AdditionalModules @() "
        f"-HostName Atlas -HostProfileId atlas -HostVersion 1.0.0 -Stdio -LogLevel Normal"
    )
    return SpawnSpec(
        [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", inner],
        root, root, env=ctx.env_overrides.get("powershell", {}),
        initialization_options={k: v for k, v in ctx.init_overrides.get("powershell", {}).items() if k != "bundlePath"},
    )


def atlas_lsp_session_dir() -> str:
    """Return (and create) the dir for PSES session/log scratch files."""
    d = os.path.join(_atlas_data_dir(), "lsp", "pses")
    os.makedirs(d, exist_ok=True)
    return d


# ---- workspace trust ----

# The only servers that start in an untrusted workspace (``workspace.is_trusted_workspace``): with the
# settings Atlas passes they run nothing the checkout ships.  Everything else waits for trust, because
# it evaluates project build files on start or on save (cargo check / build.rs / proc-macros, Gradle,
# mix.exs, build.zig, stack/cabal, Lua ``runtime.plugin``, terraform providers, prisma.config.ts, Vue's
# tsconfig ``vueCompilerOptions.plugins``, which @vue/language-core require()s from the project, ...),
# and so do user-declared ``lsp.servers`` entries, whose behaviour Atlas cannot vouch for.
UNTRUSTED_SAFE_SERVERS = frozenset({
    "pyright",                  # interpreter pinned to the operator's own (_spawn_pyright)
    "typescript",               # tsserver pinned to the launcher's SDK; plugins then resolve beside it (_spawn_typescript)
    "svelte-language-server",   # isTrusted: false — no svelte.config.js, no project svelte/prettier
    "bash-language-server",     # parses scripts; diagnostics from shellcheck on PATH
    "yaml-language-server",     # validates against JSON schemas (may fetch them); no project code
    "dockerfile-ls",            # parses the Dockerfile; never builds it
    "intelephense",             # static PHP indexer; never runs php or composer
    "clangd",                   # no --query-driver, so it never runs a project compiler
})


# ---- the registry ----

_JS_MARKERS = ["package-lock.json", "bun.lockb", "bun.lock", "pnpm-lock.yaml", "yarn.lock", "package.json", "tsconfig.json"]
_DENO_EXCLUDES = ["deno.json", "deno.jsonc"]
_root_typescript = _markers_root(_JS_MARKERS, _DENO_EXCLUDES)


def _server(server_id: str, extensions: Tuple[str, ...], description: str, *,
            markers: Optional[Sequence[str]] = None, excludes: Sequence[str] = (),
            resolve_root: Optional[_RootFn] = None, build_spawn: Optional[_SpawnFn] = None,
            which: Sequence[str] = (), args: Sequence[str] = (),
            base_init: Optional[Dict[str, Any]] = None, seed: bool = False,
            untrusted_init: Optional[Dict[str, Any]] = None, multi_root: bool = False) -> ServerDef:
    """Registry entry factory: defaults to marker-based root + single-binary spawn."""
    return ServerDef(
        server_id, extensions,
        resolve_root or _markers_root(markers, excludes),
        build_spawn or _simple_spawn(server_id, which or (server_id,), args, base_init, seed, untrusted_init),
        seed_first_push=seed, description=description, multi_root=multi_root,
    )


SERVERS: List[ServerDef] = [
    _server("pyright", (".py", ".pyi"), "Python — Microsoft pyright",
            markers=["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile", "pyrightconfig.json"],
            build_spawn=_spawn_pyright, multi_root=True),
    _server("typescript", (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"),
            "JavaScript/TypeScript — typescript-language-server", resolve_root=_root_typescript,
            build_spawn=_spawn_typescript, seed=True),
    _server("vue-language-server", (".vue",), "Vue.js — @vue/language-server", resolve_root=_root_typescript,
            build_spawn=_spawn_vue),
    _server("svelte-language-server", (".svelte",), "Svelte — svelte-language-server", resolve_root=_root_typescript,
            which=("svelteserver", "svelte-language-server"), args=("--stdio",),
            untrusted_init={"isTrusted": False}),
    _server("astro-language-server", (".astro",), "Astro — @astrojs/language-server", resolve_root=_root_typescript,
            which=("astro-ls", "astro-language-server"), args=("--stdio",)),
    _server("gopls", (".go",), "Go — gopls", markers=["go.work", "go.mod", "go.sum"]),
    _server("rust-analyzer", (".rs",), "Rust — rust-analyzer", markers=["Cargo.toml", "Cargo.lock"]),
    _server("clangd", (".c", ".cpp", ".cc", ".cxx", ".h", ".hh", ".hpp", ".hxx"), "C/C++ — clangd",
            markers=["compile_commands.json", "compile_flags.txt", ".clangd"],
            args=("--background-index", "--clang-tidy")),
    _server("bash-language-server", (".sh", ".bash", ".zsh", ".ksh"), "Bash — bash-language-server", build_spawn=_spawn_bash_ls),
    _server("yaml-language-server", (".yaml", ".yml"), "YAML — yaml-language-server",
            args=("--stdio",)),
    _server("lua-language-server", (".lua",), "Lua — lua-language-server",
            markers=[".luarc.json", ".luarc.jsonc", ".luacheckrc", ".stylua.toml", "stylua.toml", "selene.toml", "selene.yml"]),
    # Before intelephense: Blade templates are Laravel's, plain .php stays with intelephense.
    _server("laravel-lsp", (".blade.php",), "Laravel Blade — laravel-lsp (manual: composer global require laravel/lsp)",
            markers=["artisan", "composer.json", "composer.lock"], args=("lsp",)),
    _server("intelephense", (".php",), "PHP — intelephense", markers=["composer.json", "composer.lock", ".php-version"],
            args=("--stdio",), base_init={"telemetry": {"enabled": False}}),
    _server("ocaml-lsp", (".ml", ".mli"), "OCaml — ocaml-lsp", markers=["dune-project", "dune-workspace", ".merlin", "opam"],
            which=("ocamllsp",)),
    _server("dockerfile-ls", (".dockerfile", "Dockerfile"), "Dockerfile — dockerfile-language-server-nodejs",
            which=("docker-langserver",), args=("--stdio",)),
    # terraform-ls is heavy to auto-install; require the user to provide it.
    _server("terraform-ls", (".tf", ".tfvars"), "Terraform — terraform-ls", markers=[".terraform.lock.hcl", "terraform.tfstate"],
            args=("serve",), base_init={"experimentalFeatures": {"prefillRequiredFields": True, "validateOnSave": True}}),
    _server("dart", (".dart",), "Dart — built-in language server", markers=["pubspec.yaml", "analysis_options.yaml"],
            args=("language-server", "--lsp")),
    _server("haskell-language-server", (".hs", ".lhs"), "Haskell — haskell-language-server",
            markers=["stack.yaml", "cabal.project", "hie.yaml"],
            which=("haskell-language-server-wrapper", "haskell-language-server"), args=("--lsp",)),
    _server("julia", (".jl",), "Julia — LanguageServer.jl", markers=["Project.toml", "Manifest.toml"],
            args=("--startup-file=no", "--history-file=no", "-e", "using LanguageServer; runserver()")),
    _server("clojure-lsp", (".clj", ".cljs", ".cljc", ".edn"), "Clojure — clojure-lsp",
            markers=["deps.edn", "project.clj", "shadow-cljs.edn", "bb.edn", "build.boot"], args=("listen",)),
    _server("nixd", (".nix",), "Nix — nixd", resolve_root=lambda fp, ws: nearest_root(fp, ["flake.nix"]) or ws),
    _server("zls", (".zig", ".zon"), "Zig — zls", markers=["build.zig"]),
    _server("gleam", (".gleam",), "Gleam — built-in language server", markers=["gleam.toml"], args=("lsp",)),
    _server("elixir-ls", (".ex", ".exs"), "Elixir — elixir-ls", markers=["mix.exs", "mix.lock"],
            which=("elixir-ls", "language_server.sh")),
    _server("prisma", (".prisma",), "Prisma — built-in language server", markers=["schema.prisma", "prisma/schema.prisma"],
            args=("language-server",)),
    _server("kotlin-language-server", (".kt", ".kts"), "Kotlin — kotlin-language-server",
            markers=["settings.gradle", "settings.gradle.kts", "build.gradle", "build.gradle.kts", "pom.xml"]),
    # jdtls has a complex install flow; we look for the wrapper script a manual install produces.
    _server("jdtls", (".java",), "Java — Eclipse JDT Language Server",
            markers=["pom.xml", "build.gradle", "build.gradle.kts", ".project", ".classpath", "settings.gradle"]),
    # No universal PowerShell root marker; nearest_root is exact-name only (no globs).
    _server("powershell", (".ps1", ".psm1", ".psd1"), "PowerShell — PowerShellEditorServices (manual bundle)",
            markers=["PSScriptAnalyzerSettings.psd1"], build_spawn=_spawn_powershell_es),
]


def find_server_for_file(file_path: str, servers: Optional[Sequence[ServerDef]] = None) -> Optional[ServerDef]:
    """Return the first entry of ``servers`` (default: the built-in registry) that handles ``file_path``."""
    return next((srv for srv in (SERVERS if servers is None else servers) if srv.matches(file_path)), None)


def language_id_for(path: str, srv: Optional[ServerDef] = None) -> str:
    """Return the LSP languageId to send in didOpen for ``path`` (a custom server's own id wins)."""
    if srv is not None and srv.language_id:
        return srv.language_id
    return LANGUAGE_BY_EXT.get(_file_ext_or_basename(path), "plaintext")


def _custom_spawn(server_id: str, command: Sequence[str]) -> _SpawnFn:
    """Spawn builder for a config-declared server: ``command[0]`` is a path or a PATH lookup, no auto-install."""
    def build(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
        bin_path = _which(os.path.expanduser(command[0]))
        if bin_path is None:
            _warn_once(f"custom:{server_id}", f"lsp.servers.{server_id}: 命令 {command[0]!r} 未在 PATH 上找到，已跳过该自定义语言服务。")
            return None
        return _make_spec(root, ctx, server_id, [bin_path, *command[1:]])
    return build


def custom_servers(servers_cfg: Any) -> List[ServerDef]:
    """``lsp.servers`` entries that declare ``extensions`` and name no built-in server are user-declared
    servers (issue #100257).  They go AHEAD of the built-ins so a custom entry can claim an extension;
    malformed entries are logged and skipped so one typo never disables the rest of the subsystem."""
    if not isinstance(servers_cfg, dict):
        return []
    builtin = {s.server_id for s in SERVERS}
    out: List[ServerDef] = []
    for server_id, cfg in servers_cfg.items():
        if server_id in builtin or not isinstance(cfg, dict) or "extensions" not in cfg:
            continue
        command, exts, markers = cfg.get("command"), cfg.get("extensions"), cfg.get("root_markers")
        if not (isinstance(command, list) and command and all(isinstance(c, str) and c for c in command)
                and isinstance(exts, list) and exts and all(isinstance(e, str) and e for e in exts)):
            logger.warning("lsp.servers.%s: 自定义服务需要 command: [bin, ...args] 与 extensions: [.ext, ...] — 已忽略", server_id)
            continue
        out.append(ServerDef(
            str(server_id), tuple(e.lower() if e.startswith(".") else e for e in exts),
            _markers_root([str(m) for m in markers] if isinstance(markers, list) and markers else None),
            _custom_spawn(str(server_id), command),
            description=str(cfg.get("description") or f"{server_id} — 自定义（lsp.servers）"),
            language_id=str(cfg.get("language_id") or ""),
        ))
    return out


__all__ = ["ServerDef", "ServerContext", "SpawnSpec", "SERVERS", "UNTRUSTED_SAFE_SERVERS", "custom_servers",
           "find_server_for_file", "language_id_for", "LANGUAGE_BY_EXT"]
