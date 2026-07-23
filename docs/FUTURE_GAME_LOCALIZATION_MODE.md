# Future Idea: Game and Modpack Localization Mode

- **Status:** Proposed / deferred; documentation only.
- **Owner intent:** Preserve the option to localize game mods, modpacks and their structured content in a future FolioLoom mode.
- **Implementation approval:** None. This document does not create an issue, implementation work, runtime behavior, supported format, release claim or product-scope change.
- **Tracking issue:** #828.

## Product hypothesis

FolioLoom's glossary-first, author-approved translation workflow could be adapted from authorized TXT/DOCX/EPUB documents to authorized game-localization projects. A primary motivating case is Minecraft mods and modpacks, including quest-heavy packs.

The value is not a generic one-shot translation of arbitrary files. It is a maintainable localization workflow:

1. ingest an authorized package or a deliberately prepared localization source set;
2. extract only supported, human-facing strings while retaining file and game context;
3. build, import or review a project glossary and style rules;
4. generate translation candidates under those approved rules;
5. validate technical tokens and translation consistency;
6. review exceptions and risky content; and
7. export a structurally correct localization overlay, patch set or other format-specific output.

This is conceptually adjacent to the Workbench's terminology control, translation suggestions, review and QA evidence. It is **not** a reason to turn the current author/rightsholder Workbench into a general archive translator or to dilute the current TXT/DOCX/EPUB scope.

## Candidate domains: game mods and structured game content

Minecraft is a motivating first example, not the product boundary. The same future workflow could apply to mods and structured localization content for other games — for example, Civilization mods — when a format-specific adapter can safely extract strings and produce a valid output.

Potential future inputs may include supported, explicitly parsed text formats such as:

- Minecraft language JSON files and legacy `.lang` files;
- resource-pack and datapack localization sources;
- selected Minecraft quest-system data (for example, an adapter for a particular quest mod);
- Civilization or other game-mod localization assets, only after their concrete format and validation contract are separately assessed;
- selected scripted/configured user-facing text only when an adapter can preserve syntax and validate the output.

A useful future output could be a resource-pack overlay, a game-specific localization mod, or another format-specific patch archive, rather than a translated document.

## Commercial hypothesis (unvalidated)

The owner believes that professional mod creators, modpack teams and localization maintainers could be willing to pay for a reliable workflow that preserves technical structure while enforcing terminology and reducing repeated update work. The likely paid value is not raw machine translation alone; it is the combination of project glossary, context-aware suggestions, safe validation, reviewable exceptions, update/diff translation and export that can be installed or distributed.

This is a market hypothesis, not evidence of willingness to pay, a pricing decision, a paid-feature commitment or authorization to begin payment work. If promoted, discovery should interview or test with a small set of authorized professional creators/maintainers and separately establish their formats, update cadence, current translation workflow, failure costs and willingness to pay.

## Why terminology control matters

A modpack repeats the same mechanics and terms across item names, tooltips, quests, achievements, guides and dialogue. Inconsistent translations can directly impair play. A future mode should therefore retain the core FolioLoom principle: AI output is a suggestion; approved terminology and style rules are the authority.

Possible future controls include:

- project-wide glossary plus mod-specific term scopes;
- approved, forbidden and pending term variants;
- translation memory across modpack updates;
- per-string source context (mod identifier, localization key, quest position or file);
- a report of glossary adherence and unresolved/high-risk items.

## Non-negotiable technical boundaries for any future discovery

Any future exploration must assume that translated text cannot modify technical structure. Adapters would need to preserve and validate, as applicable:

- localization keys and file structure;
- placeholders such as `%s`, `%1$s`, `{player}` and equivalent tokens;
- markup, color/formatting codes and escaping;
- item/resource identifiers, commands, links and script syntax;
- cross-file references and format-specific ordering/serialization rules.

Importing an arbitrary modpack archive is not a safe or sufficient first scope. Formats, Minecraft versions, loaders, quest systems and individual mod conventions vary. A format-adapter architecture is the working hypothesis, not an approved design.

## Explicit exclusions now

- No implementation, import endpoint, parser, AI job, UI, export pipeline or support commitment.
- No claim that arbitrary modpacks, archives, JARs, scripts or quest systems are supported.
- No expansion of the active product scope beyond authorized TXT/DOCX/EPUB.
- No automatic claim that output will be game-safe without format-specific validation and real fixtures.
- No acceptance of unlicensed or unauthorized third-party content for processing merely because a ZIP can be uploaded.

## Preconditions before promotion from idea to work

Before this becomes a roadmap slice, run a separate, owner-approved discovery and architecture review that at minimum:

1. inventories real sample formats from the owner's prior Minecraft localization work, with authorization and fixture-handling boundaries;
2. selects one narrowly bounded first adapter (likely language JSON/legacy `.lang`, not an arbitrary archive);
3. defines source extraction and safe output/export contracts;
4. defines token, placeholder, syntax and structural validation requirements;
5. decides whether the first unit of work is a standalone Game Localization Mode or a separate product-room using shared FolioLoom glossary/QA primitives;
6. evaluates update/diff localization and translation-memory behavior; and
7. produces representative fixture-based evidence that the exported result both preserves structure and improves terminology consistency.

If the idea is ever promoted, it should be treated as a distinct future product/workflow track rather than as an unbounded "future format" checkbox.
