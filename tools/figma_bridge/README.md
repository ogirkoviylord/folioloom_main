# FolioLoom Figma Phase A paste renderer

This directory contains an owner-local Figma development plugin for turning tightly bounded synthetic FolioLoom design specs into native editable Figma nodes. It is local design/prototyping infrastructure only. It is not a FolioLoom product surface, not a public Figma plugin, and not release/product-readiness evidence.

## Phase A scope

In scope:

- paste or load one bounded JSON spec in the plugin UI;
- validate it fail-closed before rendering;
- create a new uniquely named Figma page for every render;
- render Phase A primitives as native Figma nodes: `frame`, `section`, `text`, `rectangle`, `line`, `chip`, `card`, `button`, `input`, and `dropzone`;
- use deterministic public node names for manual and MCP-visible verification.

Out of scope:

- bridge, queue, watcher, remote canvas writer, tokens, authentication, deployment, or server behavior;
- network access from the plugin;
- arbitrary code execution from specs;
- component instances or a full design-system renderer;
- real document text, provider payloads, private diagnostics, secrets, or copyrighted excerpts.

## Files

- `plugin/manifest.json` - Figma development plugin manifest with an empty `networkAccess.allowedDomains` list.
- `plugin/code.js` - main plugin renderer using `figma.*` APIs only.
- `plugin/ui.html` - paste/file-load UI with status, errors, and render summary.
- `schema/folioloom_figma_spec_v1.schema.json` - strict JSON schema for the Phase A spec shape.
- `schema/validate_folioloom_figma_spec_v1.js` - no-dependency validator used by offline checks.
- `fixtures/*.json` - exactly 3 committed synthetic fixtures.
- `tests/run_validation_tests.js` - no-dependency fixture and negative validation tests.

## Fixture coverage

| Fixture | Coverage |
| --- | --- |
| `fixtures/project_overview_cards.json` | page/frame/text/card/chip/button/line primitives for a project overview screen. |
| `fixtures/import_dropzone_status.json` | frame/text/dropzone/status chips/divider/card/button primitives for import/preflight states. |
| `fixtures/glossary_review_panel.json` | frame/text/card/chip/input/button rows for glossary review states. |

All fixture copy is synthetic metadata-only copy.

## Spec constraints

The Phase A validator rejects specs that do not match the strict schema and runtime checks:

- max spec bytes: 1 MiB;
- max pages: 3;
- max total nodes: 500;
- max nesting depth: 8;
- max text length per node: 10000 characters;
- bounded integer positions/sizes;
- hex color tokens only;
- `additionalProperties:false` object definitions in the JSON schema;
- unknown fields and unknown node types;
- URL-like or file/data references in any string;
- dangerous keys such as prototype pollution keys, command-like keys, and `$`-prefixed keys.

Unsupported `componentInstance` nodes are rejected in Phase A.

## Offline validation

Run from the repository root:

```bash
node tools/figma_bridge/tests/run_validation_tests.js
```

Expected success summary:

```text
FolioLoom Figma Phase A validation checks passed: 3 fixtures, 12 negative cases
```

## Load and render in Figma Desktop

1. Open Figma Desktop.
2. Use `Plugins -> Development -> Import plugin from manifest...`.
3. Select `tools/figma_bridge/plugin/manifest.json`.
4. Run `FolioLoom Phase A Paste Renderer` from `Plugins -> Development`.
5. Paste a fixture JSON from `tools/figma_bridge/fixtures/` or use the file input to load a fixture.
6. Click `Validate and render`.
7. Confirm the UI reports success and a render summary.
8. Confirm the plugin created a new page named like `FolioLoom <spec_id> <run_id>`.

## Verification recipe

Manual checks:

- verify the render output is a native Figma page, not a bitmap;
- select at least one text node and edit its characters;
- select at least one frame/card/dropzone node and edit its dimensions;
- verify pre-existing pages/nodes were not changed.

MCP/read-only checks if available:

- call the available Figma Desktop MCP metadata command for the current file;
- verify public page/node names, node types, and dimensions;
- use names like `[FL:<spec_id>:<run_id>] <type> <node_id>` as the stable verification target;
- use screenshots only as supplementary evidence, not as proof of editability.

## Naming and non-destructive policy

Each render creates a new page by default. Page names include `FolioLoom`, `spec_id`, and a generated `run_id`. Child node names are deterministic and public:

```text
[FL:<spec_id>:<run_id>] <type> <node_id>
```

The Phase A plugin does not delete or modify existing pages/nodes. If a render partially succeeds before an unexpected Figma API error, the partial plugin-created page is left visible for manual inspection and deletion.

## Font strategy

The renderer tries to load Inter Regular first. If Inter is unavailable, it tries Arial Regular. If both font loads fail, the plugin reports a visible error and does not silently create missing-text output.

## Known unknowns

- Exact Figma Desktop behavior is Unknown until a manual smoke is performed on the owner machine.
- Exact MCP metadata coverage is Unknown until the read-only MCP command is run against a rendered fixture.
