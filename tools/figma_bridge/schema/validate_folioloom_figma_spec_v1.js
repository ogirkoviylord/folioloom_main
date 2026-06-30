"use strict";

const MAX_BYTES = 1024 * 1024;
const MAX_PAGES = 3;
const MAX_NODES = 500;
const MAX_DEPTH = 8;
const MAX_TEXT_LENGTH = 10000;

const ROOT_KEYS = new Set(["schema_version", "spec_id", "title", "metadata", "pages"]);
const METADATA_KEYS = new Set(["product_context", "fixture_type", "generated_for"]);
const PAGE_KEYS = new Set(["id", "name", "children"]);
const NODE_KEYS = new Set([
  "id", "type", "name", "x", "y", "width", "height", "layout", "fill", "stroke",
  "strokeWidth", "cornerRadius", "text", "fontSize", "fontWeight", "color", "align",
  "children", "padding", "itemSpacing"
]);
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

function validateSpec(input) {
  const errors = [];
  let spec = input;
  if (typeof input === "string") {
    if (Buffer.byteLength(input, "utf8") > MAX_BYTES) {
      return { ok: false, errors: ["spec exceeds 1MB byte limit"] };
    }
    try {
      spec = JSON.parse(input);
    } catch (error) {
      return { ok: false, errors: ["invalid JSON: " + error.message] };
    }
  } else {
    try {
      const serialized = JSON.stringify(input);
      if (Buffer.byteLength(serialized, "utf8") > MAX_BYTES) {
        return { ok: false, errors: ["spec exceeds 1MB byte limit"] };
      }
    } catch (error) {
      return { ok: false, errors: ["spec is not serializable JSON"] };
    }
  }

  rejectDangerousShape(spec, "$", errors);
  requirePlainObject(spec, "$", errors);
  if (errors.length) return { ok: false, errors };

  validateAllowedKeys(spec, ROOT_KEYS, "$", errors);
  requireString(spec.schema_version, "$.schema_version", errors, { exact: "folioloom_figma_spec_v1" });
  requireString(spec.spec_id, "$.spec_id", errors, { pattern: ID_RE, max: 64 });
  requireString(spec.title, "$.title", errors, { max: 120 });
  validateMetadata(spec.metadata, errors);
  if (!Array.isArray(spec.pages)) {
    errors.push("$.pages must be an array");
  } else {
    if (spec.pages.length < 1) errors.push("$.pages must contain at least one page");
    if (spec.pages.length > MAX_PAGES) errors.push("$.pages exceeds max page count " + MAX_PAGES);
    let totalNodes = 0;
    spec.pages.forEach((page, pageIndex) => {
      validatePage(page, pageIndex, errors, (count) => { totalNodes += count; });
    });
    if (totalNodes > MAX_NODES) errors.push("spec exceeds max node count " + MAX_NODES + " (got " + totalNodes + ")");
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
    if (BAD_KEYS.has(normalized) || normalized.startsWith("$")) {
      errors.push(path + "." + key + " is not an allowed key");
    }
    rejectDangerousShape(value[key], path + "." + key, errors);
  }
}

function requirePlainObject(value, path, errors) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    errors.push(path + " must be an object");
  }
}

function validateAllowedKeys(object, allowed, path, errors) {
  for (const key of Object.keys(object || {})) {
    if (!allowed.has(key)) errors.push(path + "." + key + " is not allowed");
  }
}

function validateMetadata(metadata, errors) {
  requirePlainObject(metadata, "$.metadata", errors);
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) return;
  validateAllowedKeys(metadata, METADATA_KEYS, "$.metadata", errors);
  for (const key of METADATA_KEYS) {
    requireString(metadata[key], "$.metadata." + key, errors, { max: 120 });
  }
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
  page.children.forEach((node, index) => {
    count += validateNode(node, path + ".children[" + index + "]", 1, errors);
  });
  addCount(count);
}

function validateNode(node, path, depth, errors) {
  requirePlainObject(node, path, errors);
  if (!node || typeof node !== "object" || Array.isArray(node)) return 0;
  if (depth > MAX_DEPTH) errors.push(path + " exceeds max depth " + MAX_DEPTH);
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
  if (node.text !== undefined) requireString(node.text, path + ".text", errors, { max: MAX_TEXT_LENGTH });
  if (node.fontSize !== undefined) requireNumber(node.fontSize, path + ".fontSize", errors, { min: 8, max: 96 });
  if (node.fontWeight !== undefined) requireString(node.fontWeight, path + ".fontWeight", errors, { enumSet: FONT_WEIGHTS });
  if (node.color !== undefined) requireString(node.color, path + ".color", errors, { pattern: COLOR_RE });
  if (node.align !== undefined) requireString(node.align, path + ".align", errors, { enumSet: ALIGNS });
  if (node.padding !== undefined) requireNumber(node.padding, path + ".padding", errors, { min: 0, max: 120 });
  if (node.itemSpacing !== undefined) requireNumber(node.itemSpacing, path + ".itemSpacing", errors, { min: 0, max: 120 });

  if (node.children !== undefined) {
    if (!CONTAINER_TYPES.has(node.type)) errors.push(path + ".children is only allowed on frame/section/card/dropzone nodes");
    if (!Array.isArray(node.children)) {
      errors.push(path + ".children must be an array");
    } else {
      if (node.children.length > 100) errors.push(path + ".children exceeds max children per node 100");
      return 1 + node.children.reduce((sum, child, index) => sum + validateNode(child, path + ".children[" + index + "]", depth + 1, errors), 0);
    }
  }
  if (node.type === "text" && node.text === undefined) errors.push(path + ".text is required for text nodes");
  if (TEXTUAL_FRAME_TYPES.has(node.type) && node.text === undefined) errors.push(path + ".text is required for " + node.type + " nodes");
  if (!NODE_TYPES.has(node.type)) errors.push(path + ".type is unsupported in Phase A");
  return 1;
}

function requireString(value, path, errors, options = {}) {
  if (typeof value !== "string") {
    errors.push(path + " must be a string");
    return;
  }
  if (options.exact !== undefined && value !== options.exact) errors.push(path + " must be " + options.exact);
  if (options.max !== undefined && value.length > options.max) errors.push(path + " exceeds max length " + options.max);
  if (options.pattern && !options.pattern.test(value)) errors.push(path + " has invalid format");
  if (options.enumSet && !options.enumSet.has(value)) errors.push(path + " has unsupported value " + value);
}

function requireNumber(value, path, errors, options = {}) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    errors.push(path + " must be a finite number");
    return;
  }
  if (options.integer && !Number.isInteger(value)) errors.push(path + " must be an integer");
  if (options.min !== undefined && value < options.min) errors.push(path + " must be >= " + options.min);
  if (options.max !== undefined && value > options.max) errors.push(path + " must be <= " + options.max);
}

module.exports = {
  validateSpec,
  limits: { MAX_BYTES, MAX_PAGES, MAX_NODES, MAX_DEPTH, MAX_TEXT_LENGTH }
};
