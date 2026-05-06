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

Define why this language is being worked on now.

- Is it a first QA language, strategic market language, interface language, or expansion language?
- Which source languages are most likely?
- Which document types matter most?
- What must be true before beta or production exposure?

### 2. Target-Language Naturalness

Define what “good natural output” means.

- Preferred sentence rhythm and word order.
- How much source structure may be rewritten for naturalness.
- Whether borrowed English terms are acceptable.
- How to avoid literal calques.
- How to avoid over-editing the author’s style.

Every profile must include:

- a literal but bad translation;
- an acceptable neutral translation;
- a higher-quality translation for the expected domain.

### 3. Text Type Profiles

Define behavior for:

- general prose;
- literary fiction;
- literary non-fiction;
- journalistic or publicistic text;
- scientific or academic text;
- technical documentation;
- business or legal-like document;
- educational material;
- marketing or sales copy;
- mixed or unknown.

For every type, decide tone, terminology strictness, allowed paraphrase level, named-entity behavior, title behavior, and whether the detected type should be user-visible. Low-confidence detection must fall back to conservative `general` or `mixed`.

### 4. Terminology Policy

Required options:

- preserve original term;
- translate term;
- transliterate or transcribe term;
- use glossary-pinned form.

Each profile must list common technical terms, publishing/book terms, legal/business terms where relevant, false friends, terms that should never be translated, and borrowed words that are natural in the target language.

### 5. Named-Entity Policy

Define defaults and future user-switchable behavior for:

- personal names;
- brands;
- product names;
- legal company names;
- institutions and organizations;
- city and country names;
- street names and addresses;
- book, article, chapter, and event titles;
- link anchor text;
- usernames, package names, API names, and code identifiers.

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

Define what the user can change now, later, and never.

Required future controls:

- translation mode: Fast, Quality, Terms;
- detected text type override;
- terminology mode;
- named-entity preset;
- glossary upload or glossary entries;
- preserve/translate/transliterate switches for advanced users.

Simple UI should use presets. Advanced UI may expose category-level entity controls.

### 11. Regression Sample Set

Each profile must have samples for ordinary prose, literary paragraph, technical paragraph, business/legal-like paragraph, scientific or academic paragraph, journalistic paragraph, table-like text, mixed-language paragraph, named entities and addresses, protected code/URL/placeholders, headings/title-case examples, DOCX, and EPUB.

Every sample must include expected behavior, not necessarily a single exact translation.

### 12. Acceptance Criteria

A profile is beta-ready when:

- the profile has no unresolved decisions;
- every required sample category exists;
- regression tests cover deterministic protections and known exceptions;
- manual QA has checked at least one medium-length document;
- terminology and named-entity defaults are documented;
- text type behavior is documented;
- user-facing target-language button, prompt language name, and language detection display are consistent.

A profile is production-ready when:

- beta feedback has no recurring unresolved quality class;
- common source-target pairs have examples;
- DOCX and EPUB samples preserve structure;
- glossary and named-entity settings are stored with the job or explicitly scoped out;
- cache keys include every policy field that changes translation output;
- failure modes and fallbacks are documented.

## Language Profile Template

```markdown
# <Language> Translation Profile

## Status

- Priority:
- Rollout stage:
- Target audience:
- Common source languages:
- Most important document types:

## Default Behavior

- General:
- Technical:
- Literary:
- Business/legal-like:
- Scientific/academic:
- Journalistic:
- Marketing:

## Terminology

- Preserve:
- Translate:
- Transliterate/transcribe:
- Glossary required:
- False friends:

## Named Entities

- Personal names:
- Brands:
- Products:
- Companies:
- Institutions:
- Cities/countries:
- Streets/addresses:
- Titles:
- Links:
- Code/API/package names:

## Typography

- Quotes:
- Dashes:
- Title capitalization:
- Numbers/dates/units:
- Lists:

## Protected Text Grammar

- Case/gender/number behavior:
- Preserved foreign terms:
- Inline code punctuation:

## Source Pair Exceptions

- English -> <Language>:
- Other common source -> <Language>:
- Mixed source -> <Language>:

## Document Format Risks

- TXT:
- DOCX:
- EPUB:
- Future OCR/PDF:

## User Controls

- Current:
- Future simple presets:
- Future advanced controls:

## Regression Samples

- Ordinary prose:
- Literary:
- Technical:
- Business/legal:
- Scientific:
- Journalistic:
- Mixed-language:
- Named entities:
- Protected content:
- DOCX:
- EPUB:

## Acceptance Notes

- Beta-ready gaps:
- Production-ready gaps:
```
