#!/usr/bin/env node
"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const ts = require(path.resolve(process.argv[2]));
const root = path.resolve(process.argv[3]);
const input = fs.readFileSync(0, "utf8");
const request = JSON.parse(input);
const paths = request.source_paths;
const jsonConfigs = request.json_configs || {};
const jsonConfigPaths = Object.keys(jsonConfigs);

function digest(value) {
  return crypto.createHash("sha256").update(String(value), "utf8").digest("hex");
}

function safeText(node, source) {
  return node && typeof node.getText === "function" ? node.getText(source) : "";
}

function nodeName(node, source) {
  if (!node) return "";
  if (ts.isIdentifier(node) || ts.isPrivateIdentifier(node)) return node.text;
  return safeText(node, source).replace(/\s+/g, " ").slice(0, 160);
}

function scriptKind(file) {
  const ext = path.extname(file).toLowerCase();
  if (ext === ".tsx") return ts.ScriptKind.TSX;
  if (ext === ".jsx") return ts.ScriptKind.JSX;
  if ([".js", ".mjs"].includes(ext)) return ts.ScriptKind.JS;
  return ts.ScriptKind.TS;
}

function functionLike(node) {
  return ts.isFunctionDeclaration(node) || ts.isMethodDeclaration(node)
    || ts.isConstructorDeclaration(node) || ts.isGetAccessorDeclaration(node)
    || ts.isSetAccessorDeclaration(node) || ts.isFunctionExpression(node)
    || ts.isArrowFunction(node);
}

function declaredName(node, parentSymbol, source) {
  if (node.name) return nodeName(node.name, source);
  const parent = node.parent;
  if (parent && ts.isVariableDeclaration(parent) && parent.name) return nodeName(parent.name, source);
  if (parent && ts.isPropertyAssignment(parent) && parent.initializer === node) {
    return nodeName(parent.name, source);
  }
  const start = source.getLineAndCharacterOfPosition(node.getStart(source));
  return `<anonymous@${start.line + 1}:${start.character + 1}>`;
}

function collectFunctions(source) {
  const raw = [];
  function collect(node, parentSymbol = "") {
    let currentParent = parentSymbol;
    if (ts.isClassDeclaration(node) || ts.isClassExpression(node)) {
      const className = node.name ? nodeName(node.name, source) : `<class@${node.pos}>`;
      currentParent = parentSymbol ? `${parentSymbol}.${className}` : className;
    }
    if (functionLike(node)) {
      const name = declaredName(node, parentSymbol, source);
      const qualname = parentSymbol ? `${parentSymbol}.${name}` : name;
      raw.push({ node, name, qualname, owner: parentSymbol });
      currentParent = qualname;
    }
    for (const child of node.getChildren(source)) collect(child, currentParent);
  }
  collect(source);
  return raw;
}

function normalizedFile(file) {
  const normalized = path.resolve(file).replace(/\\/g, "/");
  return process.platform === "win32" ? normalized.toLowerCase() : normalized;
}

function importModuleForSymbol(symbol, checker) {
  if (!symbol) return null;
  let resolved = symbol;
  if (resolved.flags & ts.SymbolFlags.Alias) {
    try { resolved = checker.getAliasedSymbol(resolved); } catch (_) { /* retain alias declarations */ }
  }
  for (const declaration of [...(symbol.declarations || []), ...(resolved.declarations || [])]) {
    let current = declaration;
    while (current && !ts.isImportDeclaration(current)) current = current.parent;
    if (current && ts.isStringLiteral(current.moduleSpecifier)) return current.moduleSpecifier.text;
  }
  return null;
}

function resolveModuleRelative(moduleName, containingFile, compilerOptions, host, allowedFiles, relativeByAbsolute) {
  const resolved = ts.resolveModuleName(moduleName, containingFile, compilerOptions, host).resolvedModule;
  if (!resolved || !allowedFiles.has(normalizedFile(resolved.resolvedFileName))) return null;
  return relativeByAbsolute.get(normalizedFile(resolved.resolvedFileName)) || null;
}

function configurationImports(source, jsonConfigFields, compilerOptions, host, allowedFiles,
  relativeByAbsolute) {
  const imports = new Map();
  for (const statement of source.statements) {
    if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier)) continue;
    const configPath = resolveModuleRelative(
      statement.moduleSpecifier.text, source.fileName, compilerOptions, host, allowedFiles, relativeByAbsolute,
    );
    if (!configPath || !Object.prototype.hasOwnProperty.call(jsonConfigFields, configPath)) continue;
    const clause = statement.importClause;
    if (!clause) continue;
    if (clause.name) imports.set(clause.name.text, { configPath, mode: "default" });
    if (clause.namedBindings && ts.isNamespaceImport(clause.namedBindings)) {
      imports.set(clause.namedBindings.name.text, { configPath, mode: "namespace" });
    } else if (clause.namedBindings && ts.isNamedImports(clause.namedBindings)) {
      for (const specifier of clause.namedBindings.elements) {
        imports.set(specifier.name.text, {
          configPath,
          mode: "named",
          imported: (specifier.propertyName || specifier.name).text,
        });
      }
    }
  }
  return imports;
}

function configurationReadForAccess(node, source, imports, jsonConfigFields) {
  const segments = [];
  let current = node;
  let dynamic = false;
  while (ts.isPropertyAccessExpression(current) || ts.isElementAccessExpression(current)) {
    if (ts.isPropertyAccessExpression(current)) {
      segments.unshift(current.name.text);
    } else if (current.argumentExpression && ts.isStringLiteralLike(current.argumentExpression)) {
      segments.unshift(current.argumentExpression.text);
    } else {
      dynamic = true;
    }
    current = current.expression;
  }
  const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
  const parent = node.parent;
  const hasFallback = ts.isBinaryExpression(parent) && parent.left === node
    && (parent.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken
      || parent.operatorToken.kind === ts.SyntaxKind.BarBarToken);
  const fallback = hasFallback ? {
    fallback_operator: parent.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken ? "??" : "||",
    fallback_digest: digest(safeText(parent.right, source)),
  } : {};
  const isProcessEnv = ts.isIdentifier(current) && current.text === "process" && segments[0] === "env";
  const isImportMetaEnv = ts.isMetaProperty(current)
    && current.keywordToken === ts.SyntaxKind.ImportKeyword && current.name.text === "meta"
    && segments[0] === "env";
  if (isProcessEnv || isImportMetaEnv) {
    const key = !dynamic ? segments[1] || null : null;
    return {
      source_kind: "environment",
      key,
      line,
      resolution: key ? "resolved_environment_key" : "dynamic_environment_key_unresolved",
      ...fallback,
    };
  }
  if (!ts.isIdentifier(current)) return null;
  const binding = imports.get(current.text);
  if (!binding) return null;
  let namespaceDefaultMissing = false;
  if (binding.mode === "namespace") {
    if (segments[0] !== "default") namespaceDefaultMissing = true;
    else segments.shift();
  } else if (binding.mode === "named") {
    segments.unshift(binding.imported);
  }
  const fieldPath = segments.join(".");
  const knownFields = jsonConfigFields[binding.configPath] || [];
  const resolved = !dynamic && !namespaceDefaultMissing && knownFields.includes(fieldPath);
  const result = {
    config_path: binding.configPath,
    line,
    resolution: resolved ? "resolved_json_field" : "dynamic_property_unresolved",
  };
  if (resolved) result.field_path = fieldPath;
  else result.field_prefix = fieldPath || null;
  return result;
}

function extract(file, source, checker, allDeclarations, jsonConfigFields, compilerOptions, host,
  allowedFiles, relativeByAbsolute) {
  const absolute = path.resolve(root, file);
  const diagnostics = (source.parseDiagnostics || []).map((item) => ({
    code: Number(item.code),
    line: item.start == null ? 0 : source.getLineAndCharacterOfPosition(item.start).line + 1,
  }));
  const raw = collectFunctions(source);
  const configImports = configurationImports(source, jsonConfigFields, compilerOptions, host,
    allowedFiles, relativeByAbsolute);

  const shortNames = new Map();
  for (const item of raw) {
    if (!shortNames.has(item.name)) shortNames.set(item.name, []);
    shortNames.get(item.name).push(item.qualname);
  }

  const contracts = raw.map(({ node, name, qualname, owner }) => {
    const start = node.getStart(source);
    const end = node.end;
    const startLine = source.getLineAndCharacterOfPosition(start).line + 1;
    const endLine = source.getLineAndCharacterOfPosition(Math.max(start, end - 1)).line + 1;
    const parameters = (node.parameters || []).map((parameter) => ({
      name: nodeName(parameter.name, source),
      optional: Boolean(parameter.questionToken || parameter.initializer),
      default_digest: parameter.initializer ? digest(safeText(parameter.initializer, source)) : null,
    }));
    const exceptions = [];
    const exceptionScopes = [];
    const awaitErrorSites = [];
    const promiseErrorPaths = [];
    const platformBranches = [];
    const stateTransitions = [];
    const calls = [];
    const configReads = [];

    function inspect(item) {
      if (item !== node && functionLike(item)) return;
      if (ts.isTryStatement(item)) {
        const span = (part) => {
          if (!part) return null;
          const first = source.getLineAndCharacterOfPosition(part.getStart(source)).line + 1;
          const last = source.getLineAndCharacterOfPosition(Math.max(part.getStart(source), part.end - 1)).line + 1;
          return { start_line: first, end_line: last };
        };
        exceptionScopes.push({
          try_span: span(item.tryBlock),
          catch_span: span(item.catchClause),
          finally_span: span(item.finallyBlock),
          catch_binding_digest: item.catchClause && item.catchClause.variableDeclaration
            ? digest(safeText(item.catchClause.variableDeclaration.name, source)) : null,
          try_body_digest: digest(safeText(item.tryBlock, source)),
          catch_body_digest: item.catchClause ? digest(safeText(item.catchClause.block, source)) : null,
          finally_body_digest: item.finallyBlock ? digest(safeText(item.finallyBlock, source)) : null,
        });
      } else if (ts.isCatchClause(item)) {
        exceptions.push({
          kind: "catch",
          line: source.getLineAndCharacterOfPosition(item.getStart(source)).line + 1,
          caught_name_digest: item.variableDeclaration
            ? digest(safeText(item.variableDeclaration.name, source)) : null,
        });
      } else if (ts.isThrowStatement(item)) {
        exceptions.push({
          kind: "throw",
          line: source.getLineAndCharacterOfPosition(item.getStart(source)).line + 1,
          expression_digest: item.expression ? digest(safeText(item.expression, source)) : null,
        });
      } else if (ts.isAwaitExpression(item)) {
        awaitErrorSites.push({
          kind: "await_rejection_candidate",
          line: source.getLineAndCharacterOfPosition(item.getStart(source)).line + 1,
          expression_digest: digest(safeText(item.expression, source)),
          async_function: Boolean(node.modifiers && node.modifiers.some(
            (modifier) => modifier.kind === ts.SyntaxKind.AsyncKeyword)),
        });
      } else if (ts.isIfStatement(item) || ts.isConditionalExpression(item) || ts.isSwitchStatement(item)) {
        const condition = item.expression;
        if (condition && /process\.platform|process\.arch|Platform\.OS|isWindows|isMacOS|isLinux|os\.platform/.test(safeText(condition, source))) {
          platformBranches.push({
            line: source.getLineAndCharacterOfPosition(condition.getStart(source)).line + 1,
            expression_digest: digest(safeText(condition, source)),
          });
        }
      } else if (ts.isBinaryExpression(item) && item.operatorToken.kind >= ts.SyntaxKind.FirstAssignment
        && item.operatorToken.kind <= ts.SyntaxKind.LastAssignment) {
        const target = safeText(item.left, source);
        if (/(?:^|\.)(?:state|status|phase)$/.test(target)) {
          stateTransitions.push({
            target,
            line: source.getLineAndCharacterOfPosition(item.getStart(source)).line + 1,
            value_digest: digest(safeText(item.right, source)),
          });
        }
      } else if (ts.isCallExpression(item)) {
        if (item.expression.kind === ts.SyntaxKind.ImportKeyword) {
          calls.push({
            callee: "import()",
            line: source.getLineAndCharacterOfPosition(item.getStart(source)).line + 1,
            resolution: "dynamic_import_unresolved",
          });
        } else {
          const calleeText = safeText(item.expression, source);
          const terminal = calleeText.split(".").pop().replace(/^#/, "");
          const callLine = source.getLineAndCharacterOfPosition(item.getStart(source)).line + 1;
          if (ts.isPropertyAccessExpression(item.expression) && terminal === "reject"
            && ts.isIdentifier(item.expression.expression) && item.expression.expression.text === "Promise") {
            promiseErrorPaths.push({
              kind: "promise_reject",
              line: callLine,
              call_digest: digest(safeText(item, source)),
            });
          } else if (ts.isPropertyAccessExpression(item.expression)
            && (terminal === "catch" || terminal === "finally")) {
            promiseErrorPaths.push({
              kind: `promise_${terminal}_candidate`,
              line: callLine,
              receiver_digest: digest(safeText(item.expression.expression, source)),
              callback_present: item.arguments.length > 0,
              call_digest: digest(safeText(item, source)),
            });
          }
          const targets = shortNames.get(terminal) || [];
          const signature = checker.getResolvedSignature(item);
          const declaration = signature && signature.getDeclaration();
          const resolvedTarget = declaration && allDeclarations.get(declaration);
          if (resolvedTarget && resolvedTarget.path !== file) {
            calls.push({
              callee: resolvedTarget.qualname,
              line: source.getLineAndCharacterOfPosition(item.getStart(source)).line + 1,
              resolution: "cross_file_symbol",
              target_path: resolvedTarget.path,
              target_qualname: resolvedTarget.qualname,
              target_span: resolvedTarget.source_span,
            });
          } else if (targets.length === 1) {
            calls.push({
              callee: targets[0],
              line: source.getLineAndCharacterOfPosition(item.getStart(source)).line + 1,
              resolution: "same_file_unique_name",
            });
          } else if (targets.length > 1) {
            calls.push({
              callee: terminal,
              line: source.getLineAndCharacterOfPosition(item.getStart(source)).line + 1,
              resolution: "same_file_ambiguous_name",
              candidate_count: targets.length,
            });
          } else if (ts.isIdentifier(item.expression)) {
            const moduleSpecifier = importModuleForSymbol(checker.getSymbolAtLocation(item.expression), checker);
            if (moduleSpecifier) {
              calls.push({
                callee: terminal,
                line: source.getLineAndCharacterOfPosition(item.getStart(source)).line + 1,
                resolution: "unresolved_external_import",
                module_specifier: moduleSpecifier,
              });
            }
          }
        }
      }
      if ((ts.isPropertyAccessExpression(item) || ts.isElementAccessExpression(item))
        && !((ts.isPropertyAccessExpression(item.parent) || ts.isElementAccessExpression(item.parent))
          && item.parent.expression === item)) {
        const read = configurationReadForAccess(item, source, configImports, jsonConfigFields);
        if (read) configReads.push(read);
      }
      for (const child of item.getChildren(source)) inspect(child);
    }
    inspect(node);

    let contractKind = "javascript_function";
    if (scriptKind(absolute) === ts.ScriptKind.TS || scriptKind(absolute) === ts.ScriptKind.TSX) {
      contractKind = ts.isMethodDeclaration(node) || ts.isConstructorDeclaration(node)
        || ts.isGetAccessorDeclaration(node) || ts.isSetAccessorDeclaration(node)
        ? "typescript_method" : "typescript_function";
    } else if (ts.isMethodDeclaration(node)) {
      contractKind = "javascript_method";
    }
    return {
      kind: contractKind,
      qualname,
      owner,
      async: Boolean(node.modifiers && node.modifiers.some((modifier) => modifier.kind === ts.SyntaxKind.AsyncKeyword)),
      source_span: { start_line: startLine, end_line: endLine },
      parameters,
      obligations: {
        exceptions,
        exception_scopes: exceptionScopes,
        await_error_sites: awaitErrorSites,
        promise_error_paths: promiseErrorPaths,
        platform_branches: platformBranches,
        state_transitions: stateTransitions,
      },
      caller_edges: calls,
      configuration_reads: configReads,
    };
  });

  return { path: file, contracts, parse_diagnostics: diagnostics };
}

try {
  const allPaths = [...paths, ...jsonConfigPaths];
  const absoluteByRelative = new Map(allPaths.map((file) => [file, path.resolve(root, file)]));
  const relativeByAbsolute = new Map(allPaths.map((file) => [normalizedFile(path.resolve(root, file)), file]));
  const allowedFiles = new Set(relativeByAbsolute.keys());
  const compilerOptions = {
    allowJs: true,
    checkJs: false,
    noEmit: true,
    skipLibCheck: true,
    types: [],
    resolveJsonModule: true,
    esModuleInterop: true,
    allowSyntheticDefaultImports: true,
    target: ts.ScriptTarget.Latest,
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler || ts.ModuleResolutionKind.NodeJs,
  };
  const host = ts.createCompilerHost(compilerOptions);
  host.resolveModuleNames = (moduleNames, containingFile) => moduleNames.map((moduleName) => {
    const result = ts.resolveModuleName(moduleName, containingFile, compilerOptions, host).resolvedModule;
    return result && allowedFiles.has(normalizedFile(result.resolvedFileName)) ? result : undefined;
  });
  const program = ts.createProgram([...absoluteByRelative.values()], compilerOptions, host);
  const checker = program.getTypeChecker();
  const sources = new Map();
  for (const source of program.getSourceFiles()) {
    const relative = relativeByAbsolute.get(normalizedFile(source.fileName));
    if (relative) sources.set(relative, source);
  }
  const allDeclarations = new Map();
  for (const [file, source] of sources) {
    for (const { node, qualname } of collectFunctions(source)) {
      const start = node.getStart(source);
      const end = node.end;
      allDeclarations.set(node, {
        path: file,
        qualname,
        source_span: {
          start_line: source.getLineAndCharacterOfPosition(start).line + 1,
          end_line: source.getLineAndCharacterOfPosition(Math.max(start, end - 1)).line + 1,
        },
      });
    }
  }
  const result = paths.map((file) => {
    try {
      const source = sources.get(file);
      if (!source) throw new Error("source file was not included in the restricted TypeScript program");
      return extract(file, source, checker, allDeclarations, jsonConfigs, compilerOptions, host,
        allowedFiles, relativeByAbsolute);
    } catch (error) {
      const name = error && error.name ? error.name : "Error";
      const message = error && error.message ? String(error.message).slice(0, 300) : "no message";
      throw new Error(`${name} while parsing ${file}: ${message}`);
    }
  });
  process.stdout.write(JSON.stringify(result));
} catch (error) {
  const name = error && error.name ? error.name : "Error";
  const message = error && error.message ? String(error.message).slice(0, 500) : "no message";
  process.stderr.write(`${name}: ${message}\n`);
  process.exitCode = 2;
}
