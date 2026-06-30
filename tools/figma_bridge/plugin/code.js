"use strict";

// Inline UI for reliability in Figma development imports; some desktop builds do not expose __html__ for local smoke tests.
const UI_HTML = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>FolioLoom Figma Bridge Renderer</title>
  <style>
    body { margin: 0; padding: 16px; font: 12px Inter, Arial, sans-serif; color: #172033; background: #f7f8fa; }
    h1 { margin: 0 0 8px; font-size: 16px; }
    p { margin: 0 0 12px; color: #586174; line-height: 1.4; }
    label { display: block; margin: 0 0 4px; color: #3c4658; font-weight: 600; }
    input[type=text] { width: 100%; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px 10px; font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; }
    textarea { width: 100%; height: 230px; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 8px; padding: 10px; font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; resize: vertical; }
    .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 10px 0; }
    button { border: 0; border-radius: 8px; padding: 8px 12px; background: #2957d6; color: #fff; font-weight: 600; cursor: pointer; }
    button.secondary { background: #dbe4ff; color: #203252; }
    button.warning { background: #5940a8; color: #fff; }
    input[type=file] { font-size: 11px; }
    #bridgeMeta { white-space: pre-wrap; border-radius: 8px; padding: 8px 10px; background: #eef3ff; border: 1px solid #c9d7ff; min-height: 36px; }
    #status { white-space: pre-wrap; border-radius: 8px; padding: 10px; background: #fff; border: 1px solid #d9dee8; min-height: 56px; }
    .ok { color: #156b3a; }
    .error { color: #a33a24; }
  </style>
</head>
<body>
  <h1>FolioLoom Figma Bridge Renderer</h1>
  <p>Paste/load a bounded synthetic JSON fixture, or pull the latest spec from the owner-local 127.0.0.1 bridge. Rendering always creates a new Figma page and does not modify existing nodes.</p>

  <label for="bridgeUrl">Bridge URL</label>
  <input id="bridgeUrl" type="text" value="http://127.0.0.1:47831" spellcheck="false">
  <div class="row">
    <button id="checkBridge" class="secondary">Check bridge</button>
    <button id="pullLatest" class="secondary">Pull latest</button>
    <button id="pullRender" class="warning">Pull latest and render</button>
  </div>
  <div id="bridgeMeta">No bridge spec loaded.</div>

  <textarea id="spec" spellcheck="false" placeholder="Paste tools/figma_bridge/fixtures/*.json here or click Pull latest"></textarea>
  <div class="row">
    <button id="render">Validate and render</button>
    <button id="clear" class="secondary">Clear input</button>
    <input id="file" type="file" accept="application/json,.json">
  </div>
  <div id="status">Idle.</div>

  <script>
    const DEFAULT_BRIDGE_URL = 'http://127.0.0.1:47831';
    const specInput = document.getElementById('spec');
    const statusBox = document.getElementById('status');
    const bridgeUrlInput = document.getElementById('bridgeUrl');
    const bridgeMeta = document.getElementById('bridgeMeta');
    let activeBridgeItem = null;
    let currentRenderContext = null;

    function setStatus(message, className) {
      statusBox.className = className || '';
      statusBox.textContent = message;
    }

    function setBridgeMeta(message, className) {
      bridgeMeta.className = className || '';
      bridgeMeta.textContent = message;
    }

    function formatLatestMeta(latest) {
      return 'Latest bridge spec:' +
        '\nitem_id: ' + latest.item_id +
        '\nversion: ' + latest.version +
        '\nspec_id: ' + (latest.spec_id || 'Unknown') +
        '\ntitle: ' + (latest.title || 'Unknown') +
        '\nreceived_at: ' + latest.received_at;
    }

    function getBridgeBaseUrl() {
      let parsed;
      try {
        parsed = new URL((bridgeUrlInput.value || '').trim());
      } catch (error) {
        throw new Error('Bridge URL must be a valid URL.');
      }
      if (parsed.origin !== DEFAULT_BRIDGE_URL) {
        throw new Error('Bridge URL must stay on exact owner-local origin ' + DEFAULT_BRIDGE_URL + '.');
      }
      return parsed.origin;
    }

    async function fetchJson(path, options) {
      const baseUrl = getBridgeBaseUrl();
      const response = await fetch(baseUrl + path, options || {});
      let body = null;
      try {
        body = await response.json();
      } catch (error) {
        throw new Error('Bridge returned non-JSON response with HTTP ' + response.status + '.');
      }
      if (!response.ok || !body.ok) {
        throw new Error((body && body.error) || ('Bridge HTTP ' + response.status));
      }
      return body;
    }

    async function checkBridge() {
      try {
        const body = await fetchJson('/health');
        setStatus('Bridge is reachable at ' + DEFAULT_BRIDGE_URL + '.\nhas_latest: ' + body.has_latest, 'ok');
      } catch (error) {
        setStatus('Bridge check failed: ' + error.message + '\nPaste/file-load rendering still works without the bridge.', 'error');
      }
    }

    async function loadLatestSpec() {
      const body = await fetchJson('/latest');
      const latest = body.latest;
      activeBridgeItem = {
        item_id: latest.item_id,
        version: latest.version,
        received_at: latest.received_at,
        spec_id: latest.spec_id,
        title: latest.title
      };
      specInput.value = JSON.stringify(latest.spec, null, 2);
      setBridgeMeta(formatLatestMeta(latest), 'ok');
      setStatus('Pulled latest spec into the textarea. Click Validate and render, or use Pull latest and render.', 'ok');
      return latest;
    }

    function renderSpecFromText(statusPrefix) {
      const raw = specInput.value || '';
      if (new Blob([raw]).size > 1024 * 1024) {
        setStatus('Error: spec exceeds 1 MiB.', 'error');
        return false;
      }
      let parsed;
      try {
        parsed = JSON.parse(raw);
      } catch (error) {
        setStatus('Invalid JSON: ' + error.message, 'error');
        return false;
      }
      currentRenderContext = {
        bridgeItem: activeBridgeItem,
        specId: parsed && parsed.spec_id,
        title: parsed && parsed.title,
        startedAt: new Date().toISOString()
      };
      setStatus((statusPrefix || 'Sending spec to main plugin renderer') + '...', '');
      parent.postMessage({ pluginMessage: { type: 'render-spec', spec: parsed } }, '*');
      return true;
    }

    async function pullLatestAndRender() {
      try {
        await loadLatestSpec();
        renderSpecFromText('Pulled latest spec; sending to main plugin renderer');
      } catch (error) {
        setStatus('Pull latest and render failed: ' + error.message + '\nPaste/file-load rendering still works without the bridge.', 'error');
      }
    }

    async function postRenderAck(status, detail) {
      const context = currentRenderContext;
      if (!context || !context.bridgeItem) return;
      const ack = {
        source: 'figma-plugin',
        status,
        spec_id: context.specId || context.bridgeItem.spec_id || null,
        title: context.title || context.bridgeItem.title || null,
        bridge_item_id: context.bridgeItem.item_id,
        bridge_version: context.bridgeItem.version,
        started_at: context.startedAt,
        acknowledged_at: new Date().toISOString(),
        page_name: detail.pageName || null,
        run_id: detail.runId || null,
        summary: detail.summary || null,
        errors: detail.errors || []
      };
      try {
        const body = await fetchJson('/render-ack', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json; charset=utf-8' },
          body: JSON.stringify(ack)
        });
        const ackInfo = body.latest_ack;
        setBridgeMeta(formatLatestMeta(context.bridgeItem) + '\nlast_ack_id: ' + ackInfo.ack_id + '\nlast_ack_status: ' + status + '\nlast_ack_at: ' + ackInfo.received_at, status === 'success' ? 'ok' : 'error');
      } catch (error) {
        setBridgeMeta(formatLatestMeta(context.bridgeItem) + '\nAck failed: ' + error.message, 'error');
      }
    }

    document.getElementById('checkBridge').addEventListener('click', checkBridge);
    document.getElementById('pullLatest').addEventListener('click', async () => {
      try {
        await loadLatestSpec();
      } catch (error) {
        setStatus('Pull latest failed: ' + error.message + '\nPaste/file-load rendering still works without the bridge.', 'error');
      }
    });
    document.getElementById('pullRender').addEventListener('click', pullLatestAndRender);
    document.getElementById('render').addEventListener('click', () => renderSpecFromText('Sending spec to main plugin renderer'));

    document.getElementById('clear').addEventListener('click', () => {
      specInput.value = '';
      activeBridgeItem = null;
      currentRenderContext = null;
      setBridgeMeta('No bridge spec loaded.', '');
      setStatus('Input cleared. Existing Figma nodes were not touched.', '');
    });

    specInput.addEventListener('input', () => {
      activeBridgeItem = null;
      currentRenderContext = null;
      setBridgeMeta('Manual input edited; bridge ack disabled for the next render unless you Pull latest again.', '');
    });

    document.getElementById('file').addEventListener('change', async (event) => {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      if (file.size > 1024 * 1024) {
        setStatus('Error: selected fixture exceeds 1 MiB.', 'error');
        return;
      }
      specInput.value = await file.text();
      activeBridgeItem = null;
      currentRenderContext = null;
      setBridgeMeta('Loaded local file; bridge ack disabled unless you Pull latest again.', '');
      setStatus('Loaded fixture file: ' + file.name, 'ok');
    });

    window.onmessage = async (event) => {
      const message = event.data.pluginMessage;
      if (!message) return;
      if (message.type === 'render-success') {
        setStatus('Rendered successfully.\nPage: ' + message.pageName + '\nRun: ' + message.runId + '\nSummary: ' + JSON.stringify(message.summary, null, 2), 'ok');
        await postRenderAck('success', message);
      } else if (message.type === 'render-error') {
        const errors = Array.isArray(message.errors) ? message.errors : [String(message.errors || 'Unknown render error')];
        setStatus('Render failed.\n' + errors.join('\n'), 'error');
        await postRenderAck('failure', { errors });
      }
    };
  </script>
</body>
</html>
`;
figma.showUI(UI_HTML, { width: 520, height: 520 });
figma.notify("FolioLoom renderer opened");

const LIMITS = { maxBytes: 1024 * 1024, maxPages: 3, maxNodes: 500, maxDepth: 8, maxTextLength: 10000 };
const ROOT_KEYS = new Set(["schema_version", "spec_id", "title", "metadata", "pages"]);
const METADATA_KEYS = new Set(["product_context", "fixture_type", "generated_for"]);
const PAGE_KEYS = new Set(["id", "name", "children"]);
const NODE_KEYS = new Set(["id", "type", "name", "x", "y", "width", "height", "layout", "fill", "stroke", "strokeWidth", "cornerRadius", "text", "fontSize", "fontWeight", "color", "align", "children", "padding", "itemSpacing"]);
const NODE_TYPES = new Set(["frame", "section", "text", "rectangle", "line", "chip", "card", "button", "input", "dropzone"]);
const CONTAINER_TYPES = new Set(["frame", "section", "card", "dropzone"]);
const TEXTUAL_FRAME_TYPES = new Set(["chip", "button", "input"]);
const LAYOUTS = new Set(["none", "vertical", "horizontal"]);
const ALIGNS = new Set(["left", "center", "right"]);
const FONT_WEIGHTS = new Set(["regular", "medium", "semibold", "bold"]);
const BAD_KEYS = new Set(["__proto__", "prototype", "constructor", "eval", "function"]);
const URLISH = /(?:https?:\/\/|file:\/\/|data:|ftp:\/\/)/i;
const ID_RE = /^[a-z0-9][a-z0-9_-]{1,63}$/;
const COLOR_RE = /^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/;

figma.ui.onmessage = async (message) => {
  if (!message || message.type !== "render-spec") return;
  const result = validateSpec(message.spec);
  if (!result.ok) {
    figma.ui.postMessage({ type: "render-error", errors: result.errors });
    return;
  }

  try {
    const fontName = await loadUsableFont();
    const runId = makeRunId();
    const pageName = "FolioLoom " + message.spec.spec_id + " " + runId;
    const page = figma.createPage();
    page.name = pageName;
    figma.currentPage = page;

    const summary = { pages: 1, nodes: 0, byType: {} };
    for (const specPage of message.spec.pages) {
      for (const nodeSpec of specPage.children) {
        const node = await createNode(nodeSpec, message.spec.spec_id, runId, fontName, summary);
        page.appendChild(node);
      }
    }
    figma.viewport.scrollAndZoomIntoView(page.children);
    figma.ui.postMessage({ type: "render-success", pageName, runId, summary });
  } catch (error) {
    figma.ui.postMessage({ type: "render-error", errors: [String(error && error.message ? error.message : error)] });
  }
};

async function loadUsableFont() {
  const candidates = [
    { family: "Inter", style: "Regular" },
    { family: "Arial", style: "Regular" }
  ];
  const errors = [];
  for (const font of candidates) {
    try {
      await figma.loadFontAsync(font);
      return font;
    } catch (error) {
      errors.push(font.family + " " + font.style + ": " + String(error && error.message ? error.message : error));
    }
  }
  throw new Error("Unable to load Inter Regular or Arial Regular. No text was rendered. " + errors.join(" | "));
}

function makeRunId() {
  const stamp = new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);
  const suffix = Math.random().toString(36).slice(2, 8);
  return stamp + "_" + suffix;
}

async function createNode(spec, specId, runId, fontName, summary) {
  let node;
  if (spec.type === "text") {
    node = figma.createText();
    node.fontName = fontName;
    node.characters = spec.text || "";
    node.fontSize = spec.fontSize || 14;
    node.fills = [solidPaint(spec.color || "#172033")];
    node.textAlignHorizontal = alignToFigma(spec.align || "left");
    node.resize(spec.width, spec.height);
  } else if (spec.type === "rectangle") {
    node = figma.createRectangle();
    node.resize(spec.width, spec.height);
    applyBoxStyle(node, spec, "#D9DEE8");
  } else if (spec.type === "line") {
    node = figma.createLine();
    node.resize(spec.width, 0);
    node.strokes = [solidPaint(spec.stroke || "#D9DEE8")];
    node.strokeWeight = spec.strokeWidth || 1;
  } else {
    node = figma.createFrame();
    node.resize(spec.width, spec.height);
    applyBoxStyle(node, spec, defaultFill(spec.type));
    if (spec.layout === "vertical" || spec.layout === "horizontal") {
      node.layoutMode = spec.layout === "vertical" ? "VERTICAL" : "HORIZONTAL";
      node.paddingLeft = node.paddingRight = node.paddingTop = node.paddingBottom = spec.padding || 0;
      node.itemSpacing = spec.itemSpacing || 0;
    }
    if (TEXTUAL_FRAME_TYPES.has(spec.type)) {
      const label = figma.createText();
      label.fontName = fontName;
      label.characters = spec.text || "";
      label.fontSize = spec.fontSize || 13;
      label.fills = [solidPaint(spec.color || "#172033")];
      label.resize(Math.max(1, spec.width - 20), Math.max(1, spec.height - 10));
      label.x = 10;
      label.y = Math.max(4, Math.round((spec.height - (spec.fontSize || 13) - 4) / 2));
      label.name = nameFor(specId, runId, "text", spec.id + "_label");
      node.appendChild(label);
    }
    if (Array.isArray(spec.children)) {
      for (const childSpec of spec.children) {
        const child = await createNode(childSpec, specId, runId, fontName, summary);
        node.appendChild(child);
      }
    }
  }

  node.name = nameFor(specId, runId, spec.type, spec.id);
  node.x = spec.x;
  node.y = spec.y;
  summary.nodes += 1;
  summary.byType[spec.type] = (summary.byType[spec.type] || 0) + 1;
  return node;
}

function nameFor(specId, runId, type, id) {
  return "[FL:" + specId + ":" + runId + "] " + type + " " + id;
}

function defaultFill(type) {
  if (type === "chip") return "#EBF2FF";
  if (type === "button") return "#172033";
  if (type === "input" || type === "card" || type === "dropzone") return "#FFFFFF";
  return "#F7F8FA";
}

function applyBoxStyle(node, spec, fallbackFill) {
  node.fills = [solidPaint(spec.fill || fallbackFill)];
  if (spec.stroke) node.strokes = [solidPaint(spec.stroke)];
  if (spec.strokeWidth !== undefined) node.strokeWeight = spec.strokeWidth;
  if (spec.cornerRadius !== undefined && "cornerRadius" in node) node.cornerRadius = spec.cornerRadius;
}

function solidPaint(hex) {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16) / 255;
  const g = parseInt(value.slice(2, 4), 16) / 255;
  const b = parseInt(value.slice(4, 6), 16) / 255;
  const paint = { type: "SOLID", color: { r, g, b } };
  if (value.length === 8) paint.opacity = parseInt(value.slice(6, 8), 16) / 255;
  return paint;
}

function alignToFigma(align) {
  if (align === "center") return "CENTER";
  if (align === "right") return "RIGHT";
  return "LEFT";
}

function validateSpec(input) {
  const errors = [];
  let serialized = "";
  try {
    serialized = JSON.stringify(input);
  } catch (error) {
    return { ok: false, errors: ["spec is not serializable JSON"] };
  }
  if (!serialized || utf8ByteLength(serialized) > LIMITS.maxBytes) errors.push("spec exceeds 1MB byte limit");
  rejectDangerousShape(input, "$", errors);
  requirePlainObject(input, "$", errors);
  if (errors.length) return { ok: false, errors };

  validateAllowedKeys(input, ROOT_KEYS, "$", errors);
  requireString(input.schema_version, "$.schema_version", errors, { exact: "folioloom_figma_spec_v1" });
  requireString(input.spec_id, "$.spec_id", errors, { pattern: ID_RE, max: 64 });
  requireString(input.title, "$.title", errors, { max: 120 });
  validateMetadata(input.metadata, errors);
  if (!Array.isArray(input.pages)) {
    errors.push("$.pages must be an array");
  } else {
    if (input.pages.length < 1) errors.push("$.pages must contain at least one page");
    if (input.pages.length > LIMITS.maxPages) errors.push("$.pages exceeds max page count " + LIMITS.maxPages);
    let totalNodes = 0;
    input.pages.forEach((page, pageIndex) => validatePage(page, pageIndex, errors, (count) => { totalNodes += count; }));
    if (totalNodes > LIMITS.maxNodes) errors.push("spec exceeds max node count " + LIMITS.maxNodes + " (got " + totalNodes + ")");
  }
  return { ok: errors.length === 0, errors };
}

function rejectDangerousShape(value, path, errors) {
  if (typeof value === "string" && URLISH.test(value)) {
    errors.push(path + " must not contain URL-like or file/data references");
    return;
  }
  if (!value || typeof value !== "object") return;
  if (Array.isArray(value)) {
    value.forEach((item, index) => rejectDangerousShape(item, path + "[" + index + "]", errors));
    return;
  }
  for (const key of Object.keys(value)) {
    const normalized = key.toLowerCase();
    if (BAD_KEYS.has(normalized) || normalized.startsWith("$")) errors.push(path + "." + key + " is not an allowed key");
    rejectDangerousShape(value[key], path + "." + key, errors);
  }
}

function requirePlainObject(value, path, errors) {
  if (!value || typeof value !== "object" || Array.isArray(value)) errors.push(path + " must be an object");
}

function validateAllowedKeys(object, allowed, path, errors) {
  for (const key of Object.keys(object || {})) if (!allowed.has(key)) errors.push(path + "." + key + " is not allowed");
}

function validateMetadata(metadata, errors) {
  requirePlainObject(metadata, "$.metadata", errors);
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) return;
  validateAllowedKeys(metadata, METADATA_KEYS, "$.metadata", errors);
  for (const key of METADATA_KEYS) requireString(metadata[key], "$.metadata." + key, errors, { max: 120 });
}

function validatePage(page, pageIndex, errors, addCount) {
  const path = "$.pages[" + pageIndex + "]";
  requirePlainObject(page, path, errors);
  if (!page || typeof page !== "object" || Array.isArray(page)) return;
  validateAllowedKeys(page, PAGE_KEYS, path, errors);
  requireString(page.id, path + ".id", errors, { pattern: ID_RE, max: 64 });
  requireString(page.name, path + ".name", errors, { max: 80 });
  if (!Array.isArray(page.children)) {
    errors.push(path + ".children must be an array");
    return;
  }
  if (page.children.length < 1) errors.push(path + ".children must not be empty");
  let count = 0;
  page.children.forEach((node, index) => { count += validateNode(node, path + ".children[" + index + "]", 1, errors); });
  addCount(count);
}

function validateNode(node, path, depth, errors) {
  requirePlainObject(node, path, errors);
  if (!node || typeof node !== "object" || Array.isArray(node)) return 0;
  if (depth > LIMITS.maxDepth) errors.push(path + " exceeds max depth " + LIMITS.maxDepth);
  validateAllowedKeys(node, NODE_KEYS, path, errors);
  requireString(node.id, path + ".id", errors, { pattern: ID_RE, max: 64 });
  requireString(node.type, path + ".type", errors, { enumSet: NODE_TYPES, max: 32 });
  if (node.name !== undefined) requireString(node.name, path + ".name", errors, { max: 80 });
  requireNumber(node.x, path + ".x", errors, { min: -10000, max: 10000, integer: true });
  requireNumber(node.y, path + ".y", errors, { min: -10000, max: 10000, integer: true });
  requireNumber(node.width, path + ".width", errors, { min: 1, max: 5000, integer: true });
  requireNumber(node.height, path + ".height", errors, { min: 1, max: 5000, integer: true });
  if (node.layout !== undefined) requireString(node.layout, path + ".layout", errors, { enumSet: LAYOUTS });
  if (node.fill !== undefined) requireString(node.fill, path + ".fill", errors, { pattern: COLOR_RE });
  if (node.stroke !== undefined) requireString(node.stroke, path + ".stroke", errors, { pattern: COLOR_RE });
  if (node.strokeWidth !== undefined) requireNumber(node.strokeWidth, path + ".strokeWidth", errors, { min: 0, max: 24 });
  if (node.cornerRadius !== undefined) requireNumber(node.cornerRadius, path + ".cornerRadius", errors, { min: 0, max: 80 });
  if (node.text !== undefined) requireString(node.text, path + ".text", errors, { max: LIMITS.maxTextLength });
  if (node.fontSize !== undefined) requireNumber(node.fontSize, path + ".fontSize", errors, { min: 8, max: 96 });
  if (node.fontWeight !== undefined) requireString(node.fontWeight, path + ".fontWeight", errors, { enumSet: FONT_WEIGHTS });
  if (node.color !== undefined) requireString(node.color, path + ".color", errors, { pattern: COLOR_RE });
  if (node.align !== undefined) requireString(node.align, path + ".align", errors, { enumSet: ALIGNS });
  if (node.padding !== undefined) requireNumber(node.padding, path + ".padding", errors, { min: 0, max: 120 });
  if (node.itemSpacing !== undefined) requireNumber(node.itemSpacing, path + ".itemSpacing", errors, { min: 0, max: 120 });
  if (node.children !== undefined) {
    if (!CONTAINER_TYPES.has(node.type)) errors.push(path + ".children is only allowed on frame/section/card/dropzone nodes");
    if (!Array.isArray(node.children)) errors.push(path + ".children must be an array");
    else {
      if (node.children.length > 100) errors.push(path + ".children exceeds max children per node 100");
      return 1 + node.children.reduce((sum, child, index) => sum + validateNode(child, path + ".children[" + index + "]", depth + 1, errors), 0);
    }
  }
  if (node.type === "text" && node.text === undefined) errors.push(path + ".text is required for text nodes");
  if (TEXTUAL_FRAME_TYPES.has(node.type) && node.text === undefined) errors.push(path + ".text is required for " + node.type + " nodes");
  if (!NODE_TYPES.has(node.type)) errors.push(path + ".type is unsupported in Phase A");
  return 1;
}

function requireString(value, path, errors, options) {
  options = options || {};
  if (typeof value !== "string") { errors.push(path + " must be a string"); return; }
  if (options.exact !== undefined && value !== options.exact) errors.push(path + " must be " + options.exact);
  if (options.max !== undefined && value.length > options.max) errors.push(path + " exceeds max length " + options.max);
  if (options.pattern && !options.pattern.test(value)) errors.push(path + " has invalid format");
  if (options.enumSet && !options.enumSet.has(value)) errors.push(path + " has unsupported value " + value);
}

function requireNumber(value, path, errors, options) {
  options = options || {};
  if (typeof value !== "number" || !Number.isFinite(value)) { errors.push(path + " must be a finite number"); return; }
  if (options.integer && !Number.isInteger(value)) errors.push(path + " must be an integer");
  if (options.min !== undefined && value < options.min) errors.push(path + " must be >= " + options.min);
  if (options.max !== undefined && value > options.max) errors.push(path + " must be <= " + options.max);
}

function utf8ByteLength(value) {
  let bytes = 0;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code <= 0x7f) bytes += 1;
    else if (code <= 0x7ff) bytes += 2;
    else if (code >= 0xd800 && code <= 0xdbff) {
      bytes += 4;
      index += 1;
    } else bytes += 3;
  }
  return bytes;
}
