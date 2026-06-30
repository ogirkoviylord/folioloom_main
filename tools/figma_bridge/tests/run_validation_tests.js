"use strict";

const fs = require("fs");
const path = require("path");
const { validateSpec } = require("../schema/validate_folioloom_figma_spec_v1");

const root = path.resolve(__dirname, "..");
const fixtureDir = path.join(root, "fixtures");
const pluginCodePath = path.join(root, "plugin", "code.js");
const standaloneValidatorPath = path.join(root, "schema", "validate_folioloom_figma_spec_v1.js");
const expectedFixtures = [
  "glossary_review_panel.json",
  "import_dropzone_status.json",
  "project_overview_cards.json"
];
const sharedValidatorConstants = [
  "ROOT_KEYS",
  "METADATA_KEYS",
  "PAGE_KEYS",
  "NODE_KEYS",
  "NODE_TYPES",
  "CONTAINER_TYPES",
  "TEXTUAL_FRAME_TYPES",
  "LAYOUTS",
  "ALIGNS",
  "FONT_WEIGHTS",
  "BAD_KEYS",
  "URLISH",
  "ID_RE",
  "COLOR_RE"
];
const sharedValidatorFunctions = [
  "rejectDangerousShape",
  "requirePlainObject",
  "validateAllowedKeys",
  "validateMetadata",
  "validatePage",
  "validateNode",
  "requireString",
  "requireNumber"
];

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function scanBalanced(source, openIndex, openChar, closeChar) {
  let depth = 0;
  let quote = null;
  let escaped = false;
  let lineComment = false;
  let blockComment = false;
  for (let index = openIndex; index < source.length; index += 1) {
    const ch = source[index];
    const next = source[index + 1];
    if (lineComment) {
      if (ch === "\n") lineComment = false;
      continue;
    }
    if (blockComment) {
      if (ch === "*" && next === "/") {
        blockComment = false;
        index += 1;
      }
      continue;
    }
    if (quote) {
      if (escaped) {
        escaped = false;
      } else if (ch === "\\") {
        escaped = true;
      } else if (ch === quote) {
        quote = null;
      }
      continue;
    }
    if (ch === "/" && next === "/") {
      lineComment = true;
      index += 1;
      continue;
    }
    if (ch === "/" && next === "*") {
      blockComment = true;
      index += 1;
      continue;
    }
    if (ch === "\"" || ch === "'" || ch === "`") {
      quote = ch;
      continue;
    }
    if (ch === openChar) depth += 1;
    if (ch === closeChar) {
      depth -= 1;
      if (depth === 0) return index;
    }
  }
  return -1;
}

function extractFunctionBody(source, functionName) {
  const marker = "function " + functionName + "(";
  const start = source.indexOf(marker);
  assert(start !== -1, "missing function " + functionName);
  const paramsStart = source.indexOf("(", start);
  const paramsEnd = scanBalanced(source, paramsStart, "(", ")");
  assert(paramsEnd !== -1, "unterminated params for function " + functionName);
  const openIndex = source.indexOf("{", paramsEnd);
  assert(openIndex !== -1, "missing body for function " + functionName);
  const closeIndex = scanBalanced(source, openIndex, "{", "}");
  assert(closeIndex !== -1, "unterminated body for function " + functionName);
  return source.slice(openIndex + 1, closeIndex);
}

function extractConstInitializer(source, constName) {
  const marker = "const " + constName + " =";
  const start = source.indexOf(marker);
  assert(start !== -1, "missing const " + constName);
  let index = start + marker.length;
  let depth = 0;
  let quote = null;
  let escaped = false;
  for (; index < source.length; index += 1) {
    const ch = source[index];
    if (quote) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === "\"" || ch === "'" || ch === "`") {
      quote = ch;
      continue;
    }
    if (ch === "(" || ch === "[" || ch === "{") depth += 1;
    if (ch === ")" || ch === "]" || ch === "}") depth -= 1;
    if (ch === ";" && depth === 0) return source.slice(start + marker.length, index);
  }
  throw new Error("unterminated const " + constName);
}

function stripCommentsWhitespaceAndBraces(source) {
  let output = "";
  let quote = null;
  let escaped = false;
  let lineComment = false;
  let blockComment = false;
  for (let index = 0; index < source.length; index += 1) {
    const ch = source[index];
    const next = source[index + 1];
    if (lineComment) {
      if (ch === "\n") lineComment = false;
      continue;
    }
    if (blockComment) {
      if (ch === "*" && next === "/") {
        blockComment = false;
        index += 1;
      }
      continue;
    }
    if (quote) {
      output += ch;
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === "/" && next === "/") {
      lineComment = true;
      index += 1;
      continue;
    }
    if (ch === "/" && next === "*") {
      blockComment = true;
      index += 1;
      continue;
    }
    if (ch === "\"" || ch === "'" || ch === "`") {
      quote = ch;
      output += ch;
      continue;
    }
    if (!/\s/.test(ch) && ch !== "{" && ch !== "}") output += ch;
  }
  return output;
}

function normalizeSharedValidatorCode(source) {
  return stripCommentsWhitespaceAndBraces(source)
    .replace(/\binput\b/g, "spec")
    .replace(/\bLIMITS\.maxBytes\b/g, "MAX_BYTES")
    .replace(/\bLIMITS\.maxPages\b/g, "MAX_PAGES")
    .replace(/\bLIMITS\.maxNodes\b/g, "MAX_NODES")
    .replace(/\bLIMITS\.maxDepth\b/g, "MAX_DEPTH")
    .replace(/\bLIMITS\.maxTextLength\b/g, "MAX_TEXT_LENGTH")
    .replace(/\boptions=options\|\|;?/g, "")
    .replace(/;([),])/g, "$1");
}

function extractPluginLimit(source, name) {
  const limits = extractConstInitializer(source, "LIMITS");
  const match = limits.match(new RegExp(name + "\\s*:\\s*([^,}]+)"));
  assert(match, "missing LIMITS." + name);
  return match[1];
}

function assertSameNormalized(label, pluginSource, standaloneSource) {
  const pluginNormalized = normalizeSharedValidatorCode(pluginSource);
  const standaloneNormalized = normalizeSharedValidatorCode(standaloneSource);
  assert(
    pluginNormalized === standaloneNormalized,
    label + " drifted between plugin/code.js and schema/validate_folioloom_figma_spec_v1.js"
  );
}

function extractValidateSpecSharedCore(source) {
  const body = extractFunctionBody(source, "validateSpec");
  const anchor = body.indexOf("rejectDangerousShape(");
  assert(anchor !== -1, "missing validateSpec shared-core anchor");
  return body.slice(anchor);
}

function assertValidatorCopiesInSync() {
  const pluginSource = fs.readFileSync(pluginCodePath, "utf8");
  const standaloneSource = fs.readFileSync(standaloneValidatorPath, "utf8");

  const limitPairs = [
    ["maxBytes", "MAX_BYTES"],
    ["maxPages", "MAX_PAGES"],
    ["maxNodes", "MAX_NODES"],
    ["maxDepth", "MAX_DEPTH"],
    ["maxTextLength", "MAX_TEXT_LENGTH"]
  ];
  for (const [pluginName, standaloneName] of limitPairs) {
    assertSameNormalized(
      "validator limit " + pluginName,
      extractPluginLimit(pluginSource, pluginName),
      extractConstInitializer(standaloneSource, standaloneName)
    );
  }

  for (const constantName of sharedValidatorConstants) {
    assertSameNormalized(
      "validator constant " + constantName,
      extractConstInitializer(pluginSource, constantName),
      extractConstInitializer(standaloneSource, constantName)
    );
  }

  const pluginValidateCore = extractValidateSpecSharedCore(pluginSource);
  const standaloneValidateCore = extractValidateSpecSharedCore(standaloneSource);
  assertSameNormalized("validateSpec shared core", pluginValidateCore, standaloneValidateCore);

  for (const functionName of sharedValidatorFunctions) {
    assertSameNormalized(
      "validator function " + functionName,
      extractFunctionBody(pluginSource, functionName),
      extractFunctionBody(standaloneSource, functionName)
    );
  }
}

function firstNode(spec) {
  return spec.pages[0].children[0];
}

function run() {
  assertValidatorCopiesInSync();

  const actualFixtures = fs.readdirSync(fixtureDir).filter((name) => name.endsWith(".json")).sort();
  assert(JSON.stringify(actualFixtures) === JSON.stringify(expectedFixtures), "expected exactly 3 committed fixture JSON files");

  const validSpecs = actualFixtures.map((name) => ({ name, spec: readJson(path.join(fixtureDir, name)) }));
  for (const { name, spec } of validSpecs) {
    const result = validateSpec(spec);
    assert(result.ok, name + " should validate: " + result.errors.join("; "));
  }

  const base = validSpecs[0].spec;
  const cases = [];

  let spec = clone(base);
  spec.extra = true;
  cases.push(["unknown top-level field", spec]);

  spec = clone(base);
  firstNode(spec).unexpected = true;
  cases.push(["unknown nested field", spec]);

  spec = clone(base);
  firstNode(spec).type = "componentInstance";
  cases.push(["unknown node type/componentInstance", spec]);

  spec = clone(base);
  firstNode(spec).fill = "blue";
  cases.push(["malformed color token", spec]);

  spec = clone(base);
  firstNode(spec).text = "Open https://example.invalid";
  cases.push(["remote URL-like string", spec]);

  cases.push(["dangerous prototype key", JSON.parse('{"schema_version":"folioloom_figma_spec_v1","spec_id":"bad_proto","title":"Bad","metadata":{"product_context":"CAT workbench","fixture_type":"negative","generated_for":"test"},"pages":[{"id":"p1","name":"Page","children":[{"id":"n1","type":"text","x":0,"y":0,"width":10,"height":10,"text":"x","__proto__":{"polluted":true}}]}]}')]);

  spec = clone(base);
  delete spec.metadata;
  cases.push(["missing metadata", spec]);

  spec = clone(base);
  spec.pages[0].children = [];
  cases.push(["empty page", spec]);

  spec = clone(base);
  let cursor = firstNode(spec);
  cursor.type = "frame";
  cursor.children = [];
  for (let index = 0; index < 9; index += 1) {
    const child = { id: "depth_" + index, type: "frame", x: 0, y: 0, width: 10, height: 10, children: [] };
    cursor.children.push(child);
    cursor = child;
  }
  cases.push(["too deep", spec]);

  spec = clone(base);
  spec.pages[0].children = Array.from({ length: 501 }, (_, index) => ({
    id: "node_" + index,
    type: "text",
    x: 0,
    y: index,
    width: 10,
    height: 10,
    text: "x"
  }));
  cases.push(["too many nodes", spec]);

  spec = clone(base);
  firstNode(spec).type = "frame";
  firstNode(spec).children = Array.from({ length: 101 }, (_, index) => ({
    id: "c_" + index,
    type: "text",
    x: 0,
    y: index,
    width: 10,
    height: 10,
    text: "x"
  }));
  cases.push(["too many children in container", spec]);

  spec = clone(base);
  firstNode(spec).text = "x".repeat(10001);
  cases.push(["oversized node text", spec]);

  for (const [name, invalidSpec] of cases) {
    const result = validateSpec(invalidSpec);
    assert(!result.ok, name + " should fail validation");
  }

  const schema = readJson(path.join(root, "schema", "folioloom_figma_spec_v1.schema.json"));
  const strictFailures = [];
  function checkStrictObjects(value, pointer) {
    if (!value || typeof value !== "object") return;
    if (value.type === "object" && value.additionalProperties !== false) strictFailures.push(pointer);
    for (const [key, child] of Object.entries(value)) checkStrictObjects(child, pointer + "/" + key);
  }
  checkStrictObjects(schema, "#");
  assert(strictFailures.length === 0, "schema object definitions must be additionalProperties:false: " + strictFailures.join(", "));

  console.log("FolioLoom Figma Phase A validation checks passed: " + validSpecs.length + " fixtures, " + cases.length + " negative cases");
}

run();
