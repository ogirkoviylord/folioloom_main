"use strict";

figma.showUI(__html__, { width: 520, height: 520 });

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
