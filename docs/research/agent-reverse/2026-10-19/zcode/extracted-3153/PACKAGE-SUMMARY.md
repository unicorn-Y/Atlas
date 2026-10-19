# Package summary (checkpoint)

The verified x64 Windows installer contains an Electron desktop package whose retained manifest says version 3.15.3 and entry out/main/index.js. The Agent CLI/runtime is separately bundled as resources/glm/zcode.cjs and metadata explicitly reports electron-node, win32-x64, and the upstream source build path apps/zcode-cli/packages/cli/dist/zcode.cjs.

The actual CJS parses successfully as script/CommonJS with Acorn 8.16.0. It contains a webpack-style numeric module wrapper, minified names, runtime task/agent/tool code, SQLite migration text for workflow journals, plus bundled dependency code. Because no source maps were indexed and the bundle mixes application and dependency modules, every function-level conclusion uses exact byte ranges and remains static.

The desktop app manifest lists host, provider, RPC, service and UI workspace dependencies, but a full ASAR graph is not yet available. Strict REA inspection of the whole extracted application found a mismatch in the unpacked node-pty conpty companion; this native file remains untrusted until a full record-and-continue inventory can resolve the packaging boundary. No claim of valid publisher signature is made.
