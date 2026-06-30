# FolioLoom Figma local bridge renderer

This directory contains an owner-local Figma development plugin and tiny localhost bridge for turning tightly bounded synthetic FolioLoom design specs into native editable Figma nodes. It is local design/prototyping infrastructure only. It is not a FolioLoom product surface, not a public Figma plugin, and not release/product-readiness evidence.

## Phase B scope

In scope:

- paste or load one bounded JSON spec in the plugin UI;
- validate it fail-closed before rendering;
- create a new uniquely named Figma page for every render;
- render Phase A primitives as native Figma nodes: `frame`, `section`, `text`, `rectangle`, `line`, `chip`, `card`, `button`, `input`, and `dropzone`;
- use deterministic public node names for manual and MCP-visible verification;
- run a tiny in-memory HTTP bridge bound only to `127.0.0.1:47831`;
- post a bounded JSON spec to the exact bridge origin `http://127.0.0.1:47831` with a helper script;
- pull the latest bridge spec into the plugin without rendering, or pull it and explicitly render once;
- post a render ack back to the bridge after render success/failure.

Out of scope:

- WebSocket, queue daemon, watcher, background polling, background auto-render loop, remote canvas writer, tokens, authentication, deployment, or public server behavior;
- network access beyond exact `http://127.0.0.1:47831` from the plugin;
- arbitrary code execution from specs;
- component instances or a full design-system renderer;
- real document text, provider payloads, private diagnostics, secrets, or copyrighted excerpts.

## Files

- `plugin/manifest.json` - Figma development plugin manifest with `networkAccess.allowedDomains: ["http://127.0.0.1:47831"]` only.
- `plugin/code.js` - main plugin renderer using `figma.*` APIs and an inline copy of `plugin/ui.html` for local smoke reliability.
- `plugin/ui.html` - paste/file-load UI plus bridge URL, `Check bridge`, `Pull latest`, and `Pull latest and render` controls.
- `bridge/server.py` - no-dependency, in-memory owner-local bridge bound to `127.0.0.1` only.
- `scripts/send_spec.py` - helper for posting a JSON spec/fixture to the bridge.
- `scripts/latest_status.py` - helper for reading latest bridge spec metadata and render ack.
- `schema/folioloom_figma_spec_v1.schema.json` - strict JSON schema for the spec shape.
- `schema/validate_folioloom_figma_spec_v1.js` - no-dependency validator used by offline checks.
- `fixtures/*.json` - exactly 3 committed synthetic fixtures.
- `tests/run_validation_tests.js` - no-dependency fixture, negative validation, manifest, and UI sync checks.

## Fixture coverage

| Fixture | Coverage |
| --- | --- |
| `fixtures/project_overview_cards.json` | page/frame/text/card/chip/button/line primitives for a project overview screen. |
| `fixtures/import_dropzone_status.json` | frame/text/dropzone/status chips/divider/card/button primitives for import/preflight states. |
| `fixtures/glossary_review_panel.json` | frame/text/card/chip/input/button rows for glossary review states. |

All fixture copy is synthetic metadata-only copy.

## Spec constraints

The validator rejects specs that do not match the strict schema and runtime checks:

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

Unsupported `componentInstance` nodes are rejected.

## Local bridge runbook

Run from the repository root.

1. Start the bridge in one terminal:

```bash
python3 tools/figma_bridge/bridge/server.py
```

Expected startup line:

```text
FolioLoom Figma bridge listening on http://127.0.0.1:47831
```

The bridge binds only to `127.0.0.1`; it does not expose `0.0.0.0`, `::`, a remote hostname, auth, persistence, polling, or a queue. Helper scripts accept only the exact owner-local bridge origin `http://127.0.0.1:47831`; `localhost`, wildcard hosts, remote hosts, HTTPS URLs, paths/query fragments, and non-default ports are rejected before network I/O.

2. In another terminal, send a synthetic fixture/spec:

```bash
python3 tools/figma_bridge/scripts/send_spec.py tools/figma_bridge/fixtures/project_overview_cards.json
```

The response includes `item_id`, `version`, `received_at`, `spec_id`, and `title`.

3. Optional: inspect bridge status:

```bash
python3 tools/figma_bridge/scripts/latest_status.py
```

Before a Figma render ack, `latest_ack` is `null`. After a plugin bridge render, it shows the latest success/failure ack.

## Bridge HTTP endpoints

- `GET /health` returns bridge status, latest metadata, and latest ack if present.
- `POST /spec` stores the latest bounded JSON object in memory.
- `GET /latest` returns latest spec metadata plus the JSON spec body.
- `POST /render-ack` stores the plugin render confirmation/failure payload in memory.

All endpoints are JSON-only. Request bodies larger than 1 MiB are rejected.

Origin/CORS boundary:

- helper/script requests with no `Origin` header are allowed and do not receive CORS allow headers;
- Figma Desktop/plugin browser requests are allowed only for explicit Origins `null` and `https://www.figma.com`;
- other Origins are rejected before `/latest`, `/spec`, or `/render-ack` can read or mutate bridge state, and they do not receive `Access-Control-Allow-Origin`.

## Offline validation

Run from the repository root:

```bash
node tools/figma_bridge/tests/run_validation_tests.js
```

Expected success summary:

```text
FolioLoom Figma Phase B validation checks passed: 3 fixtures, 12 negative cases, bridge boundary checks
```

## Load and render in Figma Desktop

1. Open Figma Desktop.
2. Use `Plugins -> Development -> Import plugin from manifest...`.
3. Select `tools/figma_bridge/plugin/manifest.json`.
4. Run `FolioLoom Local Bridge Renderer` from `Plugins -> Development`.
5. For manual fallback, paste a fixture JSON from `tools/figma_bridge/fixtures/` or use the file input, then click `Validate and render`.
6. For bridge flow, start the bridge, send a fixture with `scripts/send_spec.py`, then click `Check bridge`.
7. Click `Pull latest` to populate the textarea and metadata without rendering.
8. Click `Pull latest and render` to pull the latest bridge spec and explicitly render once.
9. Confirm the UI reports success and a render summary.
10. Confirm the plugin created a new page named like `FolioLoom <spec_id> <run_id>`.
11. Run `python3 tools/figma_bridge/scripts/latest_status.py` and confirm `latest_ack` includes `status`, `bridge_item_id`, `bridge_version`, `spec_id`, and, on success, `page_name` and `run_id`.

If the bridge is down or unreachable, the plugin shows a clear bridge error and the paste/file-load/manual render fallback remains available.

## Verification recipe

Manual checks:

- verify the render output is a native Figma page, not a bitmap;
- select at least one text node and edit its characters;
- select at least one frame/card/dropzone node and edit its dimensions;
- verify pre-existing pages/nodes were not changed;
- verify `latest_status.py` shows a render ack after bridge render success or failure.

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

The plugin does not delete or modify existing pages/nodes. If a render partially succeeds before an unexpected Figma API error, the partial plugin-created page is left visible for manual inspection and deletion.

## Font strategy

The renderer tries to load Inter Regular first. If Inter is unavailable, it tries Arial Regular. If both font loads fail, the plugin reports a visible error and does not silently create missing-text output.

## Known unknowns

- Exact Figma Desktop behavior is Unknown until a manual smoke is performed on the owner machine.
- Exact MCP metadata coverage is Unknown until the read-only MCP command is run against a rendered fixture.
