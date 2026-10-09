"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");
const { spawn, spawnSync } = require("child_process");
const { validateSpec } = require("../schema/validate_folioloom_figma_spec_v1");

const root = path.resolve(__dirname, "..");
const fixtureDir = path.join(root, "fixtures");
const bridgeServerPath = path.join(root, "bridge", "server.py");
const pluginCodePath = path.join(root, "plugin", "code.js");
const pluginUiPath = path.join(root, "plugin", "ui.html");
const manifestPath = path.join(root, "plugin", "manifest.json");
const sendSpecPath = path.join(root, "scripts", "send_spec.py");
const latestStatusPath = path.join(root, "scripts", "latest_status.py");
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

function assertNoWildcardCorsSource() {
  const serverSource = fs.readFileSync(bridgeServerPath, "utf8");
  assert(!serverSource.includes("Access-Control-Allow-Origin\", \"*\""), "bridge server must not emit wildcard CORS headers");
  assert(!serverSource.includes("Access-Control-Allow-Origin', '*'"), "bridge server must not emit wildcard CORS headers");
  assert(!serverSource.includes("Access-Control-Allow-Origin: *"), "bridge server must not emit wildcard CORS headers");
  assert(serverSource.includes("ALLOWED_FIGMA_ORIGINS"), "bridge server must document an explicit Figma Origin allowlist");
}

function assertHelperUrlValidation() {
  const fixturePath = path.join(fixtureDir, "project_overview_cards.json");
  const rejectedUrls = [
    "http://localhost:47831",
    "http://0.0.0.0:47831",
    "http://[::]:47831",
    "http://example.invalid:47831",
    "https://127.0.0.1:47831",
    "http://127.0.0.1:47832",
    "http://127.0.0.1:47831/",
    "http://127.0.0.1:47831/spec",
    "http://127.0.0.1:47831?x=1",
    "http://127.0.0.1:47831#fragment"
  ];
  for (const url of rejectedUrls) {
    const sendResult = spawnSync("python3", [sendSpecPath, fixturePath, "--bridge-url", url], { encoding: "utf8" });
    assert(sendResult.status === 2, "send_spec.py should reject invalid bridge URL before network I/O: " + url);
    assert(sendResult.stderr.includes("bridge URL must be exactly http://127.0.0.1:47831"), "send_spec.py rejection should be a local URL validation error: " + url);
    assert(!sendResult.stderr.includes("bridge request failed"), "send_spec.py must reject before network I/O: " + url);

    const latestResult = spawnSync("python3", [latestStatusPath, "--bridge-url", url], { encoding: "utf8" });
    assert(latestResult.status === 2, "latest_status.py should reject invalid bridge URL before network I/O: " + url);
    assert(latestResult.stderr.includes("bridge URL must be exactly http://127.0.0.1:47831"), "latest_status.py rejection should be a local URL validation error: " + url);
    assert(!latestResult.stderr.includes("bridge request failed"), "latest_status.py must reject before network I/O: " + url);
  }
}

function requestBridge(port, method, pathName, options) {
  const requestOptions = options || {};
  const body = requestOptions.body || "";
  const headers = Object.assign({}, requestOptions.headers || {});
  if (body && !headers["Content-Length"]) headers["Content-Length"] = Buffer.byteLength(body);
  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        hostname: "127.0.0.1",
        port,
        path: pathName,
        method,
        headers
      },
      (res) => {
        let responseBody = "";
        res.setEncoding("utf8");
        res.on("data", (chunk) => {
          responseBody += chunk;
        });
        res.on("end", () => resolve({ statusCode: res.statusCode, headers: res.headers, body: responseBody }));
      }
    );
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

function startBridge(port) {
  return new Promise((resolve, reject) => {
    const child = spawn("python3", [bridgeServerPath, "--port", String(port)], { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    const timeout = setTimeout(() => {
      child.kill();
      reject(new Error("timed out starting bridge test server: " + stderr));
    }, 5000);
    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
      if (stdout.includes("FolioLoom Figma bridge listening")) {
        clearTimeout(timeout);
        resolve(child);
      }
    });
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("exit", (code) => {
      clearTimeout(timeout);
      reject(new Error("bridge test server exited early with code " + code + ": " + stderr));
    });
  });
}

async function assertBridgeRuntimeCorsBoundary() {
  const port = 47839;
  const child = await startBridge(port);
  try {
    let response = await requestBridge(port, "GET", "/health");
    assert(response.statusCode === 200, "no-Origin GET /health should work");
    assert(response.headers["access-control-allow-origin"] === undefined, "no-Origin helper response should not emit CORS allow header");

    response = await requestBridge(port, "OPTIONS", "/latest", {
      headers: {
        Origin: "https://example.invalid",
        "Access-Control-Request-Method": "GET"
      }
    });
    assert(response.statusCode === 403, "disallowed Origin must not pass preflight");
    assert(response.headers["access-control-allow-origin"] === undefined, "disallowed Origin preflight must not get CORS allow header");

    response = await requestBridge(port, "OPTIONS", "/latest", {
      headers: {
        Origin: "null",
        "Access-Control-Request-Method": "GET"
      }
    });
    assert(response.statusCode === 204, "documented Figma Desktop Origin should pass preflight");
    assert(response.headers["access-control-allow-origin"] === "null", "allowed Origin must be echoed exactly");
    assert(response.headers.vary === "Origin", "allowed CORS response must include Vary: Origin");

    response = await requestBridge(port, "POST", "/spec", {
      headers: { Origin: "https://example.invalid", "Content-Type": "application/json" },
      body: JSON.stringify({ spec_id: "blocked", title: "Blocked" })
    });
    assert(response.statusCode === 403, "disallowed Origin must not mutate /spec");

    response = await requestBridge(port, "GET", "/latest");
    assert(response.statusCode === 404, "blocked /spec mutation must not create latest state");

    response = await requestBridge(port, "POST", "/spec", {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec_id: "ok", title: "OK" })
    });
    assert(response.statusCode === 200, "no-Origin POST /spec should work");

    response = await requestBridge(port, "GET", "/latest", { headers: { Origin: "https://example.invalid" } });
    assert(response.statusCode === 403, "disallowed Origin cannot read /latest");
    assert(response.headers["access-control-allow-origin"] === undefined, "disallowed Origin read must not get CORS allow header");

    response = await requestBridge(port, "POST", "/render-ack", {
      headers: { Origin: "https://example.invalid", "Content-Type": "application/json" },
      body: JSON.stringify({ status: "blocked" })
    });
    assert(response.statusCode === 403, "disallowed Origin must not mutate /render-ack");

    response = await requestBridge(port, "GET", "/latest");
    assert(response.statusCode === 200, "no-Origin GET /latest should work after allowed spec post");
    const latest = JSON.parse(response.body);
    assert(latest.latest_ack === null, "blocked /render-ack mutation must not create latest_ack state");
  } finally {
    child.kill();
  }
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

function extractInlineUiHtml(source) {
  const marker = "const UI_HTML = `";
  const start = source.indexOf(marker);
  assert(start !== -1, "plugin/code.js must inline plugin/ui.html as a template literal");
  const end = source.indexOf("`;\nfigma.showUI", start);
  assert(end !== -1, "plugin/code.js inline UI_HTML must end before figma.showUI");
  return source.slice(start + marker.length, end);
}

function assertPhaseBBridgeSurface() {
  const manifest = readJson(manifestPath);
  assert(
    JSON.stringify(manifest.networkAccess && manifest.networkAccess.allowedDomains) === JSON.stringify(["http://127.0.0.1:47831"]),
    "manifest networkAccess.allowedDomains must allow only exact http://127.0.0.1:47831"
  );

  const pluginSource = fs.readFileSync(pluginCodePath, "utf8");
  const uiSource = fs.readFileSync(pluginUiPath, "utf8");
  assert(extractInlineUiHtml(pluginSource) === uiSource, "plugin/code.js inline UI_HTML must match plugin/ui.html");
  for (const expected of [
    "http://127.0.0.1:47831",
    "Check bridge",
    "Pull latest",
    "Pull latest and render",
    "/render-ack"
  ]) {
    assert(uiSource.includes(expected), "plugin UI missing Phase B bridge surface: " + expected);
  }
  assertNoWildcardCorsSource();
  assertHelperUrlValidation();
}

function firstNode(spec) {
  return spec.pages[0].children[0];
}

async function run() {
  assertValidatorCopiesInSync();
  assertPhaseBBridgeSurface();

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

  await assertBridgeRuntimeCorsBoundary();

  console.log("FolioLoom Figma Phase B validation checks passed: " + validSpecs.length + " fixtures, " + cases.length + " negative cases, bridge boundary checks");
}

run().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
