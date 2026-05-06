# Translation Language Quality Methodology

This methodology is used to design and review translation quality for each target language separately. A language profile is not ready until every section below has an explicit decision, examples, and at least one regression case where the decision affects translation quality.

The goal is not to make every language unique. Universal document-safety rules stay shared, while style, terminology, named entities, punctuation, genre behavior, and source-target exceptions become language-specific where needed.

## Output Per Language

Each target language must produce a short language profile with:

- priority and rollout status;
- target audiences and likely source languages;
- default behavior for general, technical, literary, business, scientific, journalistic, educational, and marketing text;
- terminology policy;
- named-entity policy;
- typography and punctuation policy;
- source-language pair exceptions;
- examples of bad, acceptable, and preferred translations;
- regression samples and acceptance checks.

## Universal Rules That Stay Shared

These rules should not be redesigned per language unless a real exception exists:

- preserve document structure, paragraphs, tables, headers, footers, footnotes, comments, EPUB spine order, and batch markers;
- preserve protected markers such as `ZXQPROTECTED...QXZ`;
- preserve URLs, email addresses, code identifiers, commands, JSON/XML/HTML/YAML syntax, placeholders, environment variables, package names, and API identifiers;
- keep fragment count, progress reporting, cancellation, partial results, retries, resume, and cache behavior stable;
- prevent provider commentary, apologies, markdown fences, warnings, and internal markers from leaking into output files.

## Language Profile Checklist

### 1. Role and Priority

Define why this language is being worked on now, likely source languages, most important document types, and beta/production readiness.

### 2. Target-Language Naturalness

Define sentence rhythm, word order, allowed rewriting for naturalness, borrowed-term tolerance, calque avoidance, and author-style preservation. Include a bad literal translation, an acceptable neutral translation, and a preferred domain translation.

### 3. Text Type Profiles

Define behavior for general prose, literary fiction, literary non-fiction, journalistic/publicistic text, scientific/academic text, technical documentation, business/legal-like documents, educational material, marketing/sales copy, and mixed/unknown text.

For every type, decide tone, terminology strictness, allowed paraphrase level, named-entity behavior, title behavior, and whether detected type should be user-visible. Low-confidence detection must fall back to conservative `general` or `mixed`.

### 4. Terminology Policy

Required options:

- preserve original term;
- translate term;
- transliterate or transcribe term;
- use glossary-pinned form.

Each profile must list common technical terms, publishing/book terms, legal/business terms where relevant, false friends, terms that should never be translated, and borrowed words that are natural in the target language.

### 5. Named-Entity Policy

Define defaults and future user-switchable behavior for personal names, brands, products, legal company names, institutions, organizations, cities, countries, street names, addresses, book/article/chapter/event titles, link anchor text, usernames, package names, API names, and code identifiers.

For each category, choose one of: preserve, translate, transliterate/transcribe, glossary-pinned form, preserve with translated explanation in parentheses, or translated form with original in parentheses.

### 6. Typography and Punctuation

Define conventions for quotation marks, apostrophes, dashes, hyphens, ellipses, spaces around punctuation, title capitalization, lists, decimal separators, dates, times, currencies, units, and measurements.

Layout-sensitive characters protected by document adapters must remain protected even when typography rules would normally normalize them.

### 7. Grammar Around Protected Text

Protected terms can make target-language grammar awkward. Decide how to handle case endings, gender/number agreement, prepositions before untranslated names, punctuation around inline code, and explanatory target-language nouns around preserved terms.

### 8. Source-Language Pair Exceptions

List pair-specific rules for common sources. Examples:

- English to Russian: avoid English word order and false friends such as `actual`, `accurate`, `eventually`, and `control`.
- Polish to Russian: handle orthographic samples such as `Zażółć gęślą jaźń` as letter tests rather than literal prose.
- Dutch to Russian: handle compounds and labels without flattening meaning.
- Mixed source to any target: translate all human-language segments while preserving protected technical fragments.

### 9. Document-Format Risks

Check TXT paragraph flow, DOCX runs/comments/notes/tables, EPUB XHTML inline tags/spine/captions/notes, future PDF/OCR output, subtitles, CSV/TSV columns, and future RTL/CJK layout risks.

Production-bound profiles must include at least one DOCX and one EPUB sample.

### 10. User Controls

Define what the user can change now, later, and never. Required future controls include translation mode, detected text type override, terminology mode, named-entity preset, glossary upload or entries, and preserve/translate/transliterate switches for advanced users.

Simple UI should use presets. Advanced UI may expose category-level entity controls.

### 11. Regression Sample Set

Each profile must have samples for ordinary prose, literary paragraph, technical paragraph, business/legal-like paragraph, scientific or academic paragraph, journalistic paragraph, table-like text, mixed-language paragraph, named entities and addresses, protected code/URL/placeholders, headings/title-case examples, DOCX, and EPUB.

Every sample must include expected behavior, not necessarily a single exact translation.

### 12. Acceptance Criteria

A profile is beta-ready when the profile has no unresolved decisions, every required sample category exists, regression tests cover deterministic protections and known exceptions, manual QA has checked at least one medium-length document, terminology and named-entity defaults are documented, text type behavior is documented, and user-facing target-language button, prompt language name, and language detection display are consistent.

A profile is production-ready when beta feedback has no recurring unresolved quality class, common source-target pairs have examples, DOCX and EPUB samples preserve structure, glossary and named-entity settings are stored with the job or explicitly scoped out, cache keys include every policy field that changes translation output, and failure modes/fallbacks are documented.
