# Russian Translation Profile

This profile defines how the service should translate documents into Russian. It is the first target-language quality profile and is used to validate the broader language-profile architecture before the same process is applied to other target languages.

The profile is intentionally layered: universal document-safety rules remain shared, while Russian-specific decisions live here.

## Status

- Priority: first quality-development target language.
- Rollout stage: design draft, not production-ready.
- Target audience: Russian-speaking readers of books, long-form texts, technical materials, business documents, educational content, and publicistic texts.
- Common source languages: English first; Ukrainian, Polish, Dutch, French, Spanish, German, and mixed-language documents next.
- Most important document types: TXT, DOCX, EPUB.
- Current quality goal: create enough decisions and samples to implement a Russian target-language profile through tests instead of ad hoc prompt edits.

Russian is first because it is practical for fast manual QA and exposes hard translation-policy problems early: English calques, technical terminology, transliteration, named entities, inflection around preserved terms, and book-style naturalness. It is not defined as the main market.

## Shared Rules Inherited From The Core

The Russian profile must not override these shared rules unless a documented exception exists:

- preserve document structure, paragraph boundaries, tables, headers, footers, notes, comments, EPUB spine order, and internal batch markers;
- keep `ZXQPROTECTED...QXZ` markers unchanged;
- preserve URLs, email addresses, usernames, code identifiers, package names, API names, commands, JSON/XML/HTML/YAML syntax, placeholders, and environment variables;
- prevent provider commentary, apologies, markdown fences, warnings, and internal markers from leaking into translated files;
- keep cancellation, partial result, retry, resume, and translation-cache behavior stable.

## Default Behavior

- General: produce natural modern Russian, avoid English word order and literal calques, keep meaning and tone without unnecessary embellishment.
- Technical: prefer stable Russian IT terminology, preserve code/API/package identifiers, preserve or transliterate established English terms when literal translation would sound artificial.
- Literary: preserve voice, rhythm, dialogue, imagery, and author style; avoid flattening prose into neutral explanatory Russian.
- Business/legal-like: preserve entities, dates, amounts, obligations, defined terms, and formal tone; avoid creative paraphrase.
- Scientific/academic: preserve exact claims, hedging, citations, units, formulas, and terminology; avoid popularizing the style unless the source is popular science.
- Journalistic/publicistic: preserve factual clarity, attribution, dates, names, and readable Russian publicistic rhythm; avoid both bureaucratic heaviness and clickbait exaggeration.
- Marketing: preserve persuasive intent and idiomatic Russian copy, but do not invent claims, guarantees, or benefits absent from the source.
- Mixed/unknown: use conservative general Russian with technical/entity protections enabled.

## Target-Language Naturalness

Russian output should sound like a text originally edited in Russian, not like English syntax with Russian words.

Required decisions:

- Rewrite sentence order when English or Dutch source order is unnatural in Russian.
- Prefer verbs and concrete nouns over heavy nominalizations when the source is ordinary prose.
- Avoid repeating English possessive structure mechanically, for example `his/her/their` should often become a Russian noun phrase or be omitted when clear.
- Avoid unnecessary pronouns where Russian naturally drops them.
- Preserve author voice in literary text, but do not add explanations.
- Do not over-Russify technical identifiers or official names.

Examples:

- Bad literal: `Он сделал решение использовать фреймворк.`
- Neutral: `Он принял решение использовать фреймворк.`
- Better technical/editorial: `Он решил использовать фреймворк.`

- Bad literal: `Это высокоуровневый обзор системы.`
- Neutral: `Это обзор системы на высоком уровне.`
- Better general: `Это общее описание системы.`

## Text Type Profiles

### General Prose

- Tone: natural, clear, contemporary Russian.
- Terminology strictness: medium.
- Paraphrase level: moderate when needed for Russian syntax.
- Names and titles: preserve official names; translate descriptive titles when not protected.
- User-facing detection: not necessary in MVP.

### Literary Fiction

- Tone: preserve authorial voice, register, rhythm, dialogue, imagery, irony, and ambiguity.
- Terminology strictness: low unless the text contains domain terms.
- Paraphrase level: allowed for natural Russian style, but not for changing meaning.
- Names and titles: personal names usually transliterate unless a canonical Russian form exists; titles require case-by-case handling.
- User-facing detection: useful later because users may want a literary mode.

### Literary Non-Fiction

- Tone: clear editorial Russian with author voice preserved.
- Terminology strictness: medium.
- Paraphrase level: moderate.
- Names and titles: preserve official names; translate descriptive book/article titles when the source title is not protected.

### Journalistic Or Publicistic Text

- Tone: readable publicistic Russian.
- Terminology strictness: medium.
- Paraphrase level: limited; preserve facts, dates, attributions, quotes.
- Names and titles: preserve official organizations and publication names; translate descriptive event names only when natural.

### Scientific Or Academic Text

- Tone: precise academic Russian.
- Terminology strictness: high.
- Paraphrase level: low; preserve claims, uncertainty, citations, units, formulas.
- Names and titles: preserve source titles in references unless a canonical Russian title is known or glossary-pinned.

### Technical Documentation

- Tone: concise technical Russian.
- Terminology strictness: high.
- Paraphrase level: low to medium; rewrite for clarity but preserve exact procedures.
- Names and titles: preserve code, APIs, package names, filenames, command flags, env vars, and product names.

### Business Or Legal-Like Document

- Tone: formal Russian, but avoid unnecessary bureaucracy.
- Terminology strictness: high.
- Paraphrase level: low; preserve obligations, definitions, dates, amounts, and entity names.
- Names and titles: preserve legal company names and official names; optional translation in parentheses is a future user setting.

### Educational Material

- Tone: clear explanatory Russian.
- Terminology strictness: medium to high.
- Paraphrase level: moderate for clarity.
- Names and titles: preserve protected names and translate descriptive learning headings.

### Marketing Or Sales Copy

- Tone: idiomatic Russian marketing copy.
- Terminology strictness: medium.
- Paraphrase level: moderate, but no invented claims.
- Names and titles: preserve brands and product names; translate slogans only when user policy allows localization.

## Terminology

The default Russian terminology policy is conservative: preserve technical precision, use established Russian equivalents where natural, and avoid inconsistent switching between translation, transliteration, and preservation.

### Preserve

Preserve unchanged unless glossary or user policy says otherwise:

- API names, package names, library names, model names, product identifiers, environment variables, command names, flags, filenames, code symbols;
- URLs, emails, usernames, issue IDs, document-control labels;
- registered brand and product names.

### Translate

Translate when there is a natural and established Russian term:

- `query parameters` -> `параметры запроса`;
- `regular expression` -> `регулярное выражение`;
- `footnote` -> `сноска`;
- `endnote` -> `концевая сноска` or `затекстовая сноска` depending on document context;
- `tracked changes` -> `исправления` or `отслеживаемые изменения` depending on UI/document context;
- `section break` -> `разрыв раздела`;
- `merge cells` -> `объединение ячеек`.

### Transliterate Or Transcribe

Use when the borrowed form is natural in Russian technical or publishing context:

- `prompt` -> `промпт` for LLM/product context; `подсказка` only when the source means a user hint rather than an LLM instruction;
- `token` -> `токен` for LLM/API/security context; `маркер` only when source means a visible marker;
- `placeholder` -> `плейсхолдер` in technical UI/LLM context; `заполнитель` in general UI text; avoid `местозаполнитель` unless glossary-pinned;
- `framework` -> `фреймворк`;
- `callback` -> `callback` or `колбэк`; default `callback` for code/API reference, `колбэк` in explanatory prose;
- `endpoint` -> `endpoint` or `эндпоинт`; default `endpoint` for API references, `эндпоинт` in explanatory technical prose.

### Glossary Required

Use glossary-pinned forms when consistency is more important than default behavior:

- product UI terms;
- book series names;
- company-specific terminology;
- recurring technical terms such as `prompt tier`, `translation memory`, `protected markers`;
- official legal names and institutions.

### False Friends

English to Russian profile must guard against:

- `actual` -> usually `фактический`, `реальный`, `действительный`; not automatically `актуальный`;
- `accurate` -> `точный`; not `аккуратный` unless about neatness;
- `eventually` -> `в итоге`, `со временем`; not `эвентуально`;
- `control` -> `управление`, `проверка`, `контроль` depending on context;
- `data` -> `данные`, usually plural agreement in Russian editorial style;
- `public` -> `общедоступный`, `публичный`, `общественный` depending on context;
- `regular` -> `обычный`, `регулярный`, `штатный` depending on context.

## Named Entities

### Personal Names

- Default: transliterate/transcribe ordinary personal names into Russian when the text is intended for Russian readers.
- Preserve original spelling when the name is part of a citation, bibliography, legal identity, username, email, code owner, or product/account handle.
- If a canonical Russian form exists, prefer it: `William Shakespeare` -> `Уильям Шекспир`.
- Future advanced setting: preserve original in parentheses after first occurrence.

### Brands

- Default: preserve original brand spelling.
- Do not translate registered brands.
- Do not transliterate brands unless the brand has a common Russian form or glossary pins it.

### Products

- Default: preserve official product names.
- Translate generic descriptive product categories around the name.
- Example: `OpenAI Responses API` should preserve `OpenAI` and `Responses API`, while surrounding prose becomes Russian.

### Companies And Legal Names

- Default: preserve legal company names.
- Company type suffixes such as `LLC`, `Inc.`, `GmbH`, `B.V.` should be preserved unless a legal-localization setting exists.
- Future setting: add translated explanation in parentheses for reader clarity.

### Institutions And Organizations

- Default: preserve official names if they are recognized or legal names.
- Translate descriptive organization names when no official English branding is implied.
- Future setting: translated form with original in parentheses on first mention.

### Cities, Countries, Streets, Addresses

- Countries and major cities: use established Russian forms when they exist, for example `Netherlands` -> `Нидерланды`, `Germany` -> `Германия`, `Amsterdam` -> `Амстердам`.
- Street names and addresses: default transliterate/transcribe for readability while preserving exact address components when delivery/legal precision matters.
- Future setting: preserve addresses exactly.

### Titles

- Book, article, chapter, event, and campaign titles require context:
  - preserve official or branded titles;
  - translate descriptive titles for reader comprehension;
  - future setting: translated title with original in parentheses.

### Links And Anchors

- URLs always preserve.
- Link anchor text may be translated if it is ordinary prose.
- Anchors that are product names, command names, IDs, or UI labels follow the entity/technical policy.

### Code, API, Package Names

- Always preserve exact spelling.
- Do not add Russian inflection inside inline code.
- If grammar requires an ending, prefer a surrounding Russian noun over changing protected code.

## Typography

- Quotes: use Russian guillemets `«...»` for ordinary prose when typography normalization is safe. Preserve source quote style if the document clearly uses a deliberate style.
- Dashes: use em dash with spaces in prose where safe: `слово — слово`. Preserve protected hyphens, ranges, IDs, command flags, and table spacing.
- Title capitalization: convert English Title Case to Russian sentence-style capitalization unless preserving an official title.
- Apostrophes: preserve in names and code; avoid introducing apostrophes in Russian transliteration unless canonical.
- Ellipses: use `...` or source style consistently; do not alter protected layout.
- Decimal separators: preserve numeric format in technical/business data unless localization policy explicitly allows conversion.
- Dates: preserve exact dates in legal/business/scientific texts; naturalize only in prose when safe.
- Units: preserve values and units; translate unit names in prose, preserve unit symbols.
- Lists: preserve numbering and bullet structure; translate list item text without changing hierarchy.

## Protected Text Grammar

Protected terms can make Russian ungrammatical if inserted raw. The Russian profile should use these strategies:

- Prefer a Russian generic noun around preserved foreign terms when inflection is needed: `модуль FastAPI`, `пакет requests`, `метод callback`.
- Do not alter inline code or protected identifiers to add Russian endings.
- For common borrowed technical terms, use inflected transliteration when allowed: `фреймворка`, `токена`, `эндпоинта`, `промпта`.
- If a preserved brand or API name needs a case ending, rewrite the sentence around it rather than attaching endings to the brand.
- Keep punctuation outside protected inline code where possible.

Examples:

- Awkward: `с помощью framework`
- Better: `с помощью фреймворка`
- Better when preserving official name: `с помощью фреймворка FrameworkName`

- Awkward: `вызовите callback`
- Better explanatory: `вызовите callback-функцию`
- Better prose: `вызовите колбэк`

## Source Pair Exceptions

### English -> Russian

- Avoid English word order and mechanical possessives.
- Guard false friends listed in the terminology section.
- Convert Title Case to Russian capitalization unless official.
- Translate all human-readable prose even when it appears inside a mixed-language paragraph.
- Preserve code, API names, URLs, and technical identifiers.

### Ukrainian -> Russian

- Do not over-normalize shared Slavic structures into stiff Russian.
- Preserve Ukrainian personal and place names with established Russian forms only when appropriate for the document type.
- Be careful with cognates that have shifted meaning or register.

### Polish -> Russian

- Handle orthographic samples such as `Zażółć gęślą jaźń` as letter/diacritic tests, not literal prose.
- Preserve Polish personal and street names according to named-entity policy.
- Avoid transliterated nonsense when the source is a pangram.

### Dutch -> Russian

- Split Dutch compounds by meaning instead of flattening them into one awkward Russian noun.
- Handle labels such as `Nederlands:` as source-language labels and regenerate them as `Нидерландский:` when preserving the label is useful.
- Preserve Dutch legal suffixes such as `B.V.` in company names.

### French / Spanish / German -> Russian

- Preserve official names and accents when the original form is part of a brand, citation, or legal name.
- Translate descriptive institution names when no official title is implied.
- Use established Russian country/city names.

### Mixed Source -> Russian

- Translate all human-language segments into Russian.
- Preserve protected technical fragments.
- Preserve or regenerate language labels consistently, for example `English:` -> `Английский:` when labels remain in the output.

## Document Format Risks

### TXT

- Paragraph flow is flexible, but blank lines must remain stable.
- Avoid adding explanatory notes or headings.

### DOCX

- Russian word order and length changes can disrupt run-level formatting. Preserve structure first, then distribute translated text as safely as possible.
- Tables, pseudo-tables, headers, footers, footnotes, endnotes, and comments must be translated without leaking markers.
- Subscript/superscript, formulas, IDs, and repeated spacing must stay protected.
- Russian typography should not break layout-sensitive spacing.

### EPUB

- Preserve XHTML inline elements and spine order.
- Russian text length can change line breaks; do not alter markup just to control pagination.
- Captions, footnotes, and notes may need stricter, less literary translation than body prose.

### Future OCR/PDF

- OCR language pack for Russian must be available before scanned Russian target output is production-bound.
- PDF reconstruction may need font support for Cyrillic.

### Subtitles

- Russian often expands compared with English. Subtitle mode should prefer concise Russian and preserve timing.

### CSV/TSV

- Preserve row and column count.
- Do not translate machine-readable keys unless structured-value translation is explicitly enabled.

## User Controls

### Current

- User chooses target language.
- Translation mode/profile is not yet exposed.
- Terminology and named-entity controls are not yet exposed.

### Future Simple Presets

- `Natural Russian`: default general profile.
- `Technical Russian`: preserve identifiers and use stable IT terminology.
- `Literary Russian`: preserve voice and style.
- `Preserve names`: keep brands, companies, products, API names, and official titles.
- `Transliterate names`: transliterate ordinary personal names and some place names.
- `Use glossary`: apply user-pinned terms.

### Future Advanced Controls

- Technical terms: preserve, translate, transliterate, glossary.
- Personal names: preserve, transliterate, canonical Russian form, original in parentheses.
- Brands/products/companies: preserve, glossary.
- Streets/addresses: preserve exact, transliterate, translate descriptive parts.
- Titles: preserve, translate, translated with original in parentheses.
- Text type override: general, technical, literary, business/legal-like, scientific, journalistic, marketing, mixed.

## Regression Samples

Every sample must define expected behavior. Exact output is required only for deterministic cases.

### Ordinary Prose

Source:

```text
He made a decision after a high-level overview of the system.
```

Expected behavior: avoid `сделал решение`; avoid awkward `высокоуровневый обзор` unless the context is explicitly technical.

Acceptable:

```text
Он принял решение после общего обзора системы.
```

### Literary

Source:

```text
The room held its breath while the rain traced silver lines across the window.
```

Expected behavior: preserve imagery and rhythm; do not flatten to technical description.

Quality target:

```text
Комната словно затаила дыхание, пока дождь чертил серебряные линии на стекле.
```

### Technical

Source:

```text
Set the API endpoint and pass the placeholder token to the callback handler.
```

Expected behavior: preserve `API`; choose consistent terms for `endpoint`, `placeholder`, `token`, and `callback`; do not translate into clumsy literal Russian.

Possible technical output:

```text
Укажите API endpoint и передайте токен-плейсхолдер в callback-обработчик.
```

Alternative glossary-driven output may use `эндпоинт`, `плейсхолдер`, and `колбэк`.

### Business/Legal-Like

Source:

```text
Acme B.V. shall deliver the materials by 15 March 2026.
```

Expected behavior: preserve legal company name and date; preserve obligation.

Possible output:

```text
Acme B.V. обязуется предоставить материалы до 15 марта 2026 года.
```

### Scientific

Source:

```text
The results suggest a moderate correlation, but the sample size limits the conclusion.
```

Expected behavior: preserve hedging; do not overstate claim.

Possible output:

```text
Результаты указывают на умеренную корреляцию, однако размер выборки ограничивает достоверность вывода.
```

### Journalistic

Source:

```text
Officials said the policy would be reviewed after public consultations.
```

Expected behavior: preserve attribution and publicistic clarity.

Possible output:

```text
Чиновники заявили, что политику пересмотрят после общественных консультаций.
```

### Mixed-Language

Source:

```text
English: The endpoint failed. Polski: Zażółć gęślą jaźń. Nederlands: De klant bevestigde de bestelling.
```

Expected behavior: translate all human-language segments into Russian, preserve or regenerate language labels, treat Polish pangram as orthographic sample.

### Named Entities

Source:

```text
Maria Johnson visited Baker Street and met the OpenAI Research team.
```

Expected behavior: transliterate ordinary personal name, handle street according to address/title policy, preserve `OpenAI`.

### Protected Content

Source:

```text
Set ${API_TOKEN}, call https://example.com/v1/items, and keep ROW-001 unchanged.
```

Expected behavior: protected content remains byte-for-byte unchanged while surrounding prose becomes Russian.

### Headings And Title Case

Source:

```text
Translation Quality Roadmap
```

Expected behavior: Russian capitalization should be sentence-style unless official title preservation applies.

Possible output:

```text
Дорожная карта качества перевода
```

### DOCX

Required sample coverage:

- headings;
- paragraphs;
- table cells;
- pseudo-table row;
- hyperlink visible text;
- footnote;
- endnote;
- comment;
- subscript/superscript;
- mixed-language paragraph;
- protected technical tokens.

### EPUB

Required sample coverage:

- spine order;
- chapter heading;
- paragraph prose;
- inline `strong` and `em`;
- link;
- caption or footnote-like block;
- mixed-language paragraph.

## Acceptance Notes

### Beta-Ready Gaps

- Create actual TXT, DOCX, and EPUB Russian sample pack files.
- Add automated tests for deterministic Russian exceptions and protected grammar cases.
- Add prompt/profile implementation plan after this profile is reviewed.
- Run manual QA on at least one medium-length English -> Russian document.

### Production-Ready Gaps

- Store selected Russian profile and policy fields with jobs.
- Include policy fields in translation-cache keys.
- Add user-facing presets or explicitly defer them.
- Validate DOCX and EPUB structure preservation on real documents.
- Collect beta feedback and update terminology defaults.
