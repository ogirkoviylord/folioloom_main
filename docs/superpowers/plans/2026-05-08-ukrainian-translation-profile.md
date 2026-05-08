# Ukrainian Translation Profile Implementation Plan


**Goal:** Add a full Ukrainian target-language translation profile with prompt rules, cache signatures, and source-pair guidance matching the Russian profile architecture.

**Architecture:** Extend the existing profile data model instead of creating a separate Ukrainian path. Generalize profile prompt labels so Russian and Ukrainian share one builder, then add `UKRAINIAN_PROFILE` and `en/ru/auto -> uk` source-pair profiles. Keep deterministic Ukrainian QA, sample corpus generation, and generic quality-track refactoring out of this first implementation.

**Tech Stack:** Python dataclasses, existing `unittest`, existing `translator_service.translation_profiles`, `translator_service.source_pair_profiles`, and `translator_service.translation_policy`.

---

## Baseline Notes

Worktree: `/path/to/local-workspace/Documents/New project 2 dev`

Branch: `codex/dev`

Design docs:

- `docs/superpowers/specs/ukrainian-translation-profile.md`
- `docs/superpowers/specs/2026-05-08-ukrainian-translation-profile-design.md`

The worktree is already dirty with unrelated changes. Do not revert or clean unrelated files. Only touch the files listed in this plan unless a test reveals a direct dependency.

## File Structure

- Modify `src/translator_service/translation_profiles.py`
  - Generalize target-language prompt labels away from hardcoded Russian strings.
  - Normalize target language roots such as `uk-UA` to `uk`.
  - Add `UKRAINIAN_PROFILE`.
- Modify `src/translator_service/source_pair_profiles.py`
  - Remove the Russian-only target gate.
  - Add `en -> uk`, `ru -> uk`, and `auto -> uk` profiles.
- Modify `tests/test_translation_profiles.py`
  - Add Ukrainian target-profile tests.
  - Narrow the no-profile test to a language that still has no profile.
- Modify `tests/test_source_pair_profiles.py`
  - Replace the old `en -> uk` no-guidance assertion.
  - Add Ukrainian source-pair tests.
- Modify `tests/test_translation_policy.py`
  - Add one full system-prompt assertion for Ukrainian profile + source-pair guidance.
- Modify `tests/test_translation_cache.py`
  - Add or extend one policy-signature test that proves Ukrainian target profile participates in cache keys.

---

### Task 1: Ukrainian Target Profile Tests

**Files:**
- Modify: `tests/test_translation_profiles.py`
- Later modify: `src/translator_service/translation_profiles.py`

- [ ] **Step 1: Write failing tests for Ukrainian profile lookup and signature**

Add these methods to `TranslationProfilesTest` in `tests/test_translation_profiles.py`:

```python
    def test_returns_ukrainian_target_language_profile(self):
        profile = get_target_language_profile("uk")

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.language_code, "uk")
        self.assertEqual(profile.version, "ukrainian-v1")
        term_examples = " ".join(profile.term_examples)
        self.assertIn("параметри запиту", term_examples)
        self.assertIn("заповнювач", term_examples)
        self.assertIn("плейсхолдер", term_examples)
        self.assertIn("endpoint", term_examples)

    def test_returns_ukrainian_profile_for_regional_language_tag(self):
        profile = get_target_language_profile("uk-UA")

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.language_code, "uk")

    def test_returns_stable_ukrainian_policy_signature_for_cache_keys(self):
        self.assertEqual(
            target_language_policy_signature("uk"),
            "target-profile:uk:ukrainian-v1",
        )
        self.assertEqual(
            target_language_policy_signature("uk-UA"),
            "target-profile:uk:ukrainian-v1",
        )
```

Also update `test_returns_stable_policy_signature_for_cache_keys` so it still checks Russian and default language behavior:

```python
    def test_returns_stable_policy_signature_for_cache_keys(self):
        self.assertEqual(
            target_language_policy_signature("ru"),
            "target-profile:ru:russian-v2",
        )
        self.assertEqual(
            target_language_policy_signature("en"),
            "target-profile:default-v1",
        )
```

- [ ] **Step 2: Verify RED for profile lookup**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_translation_profiles.TranslationProfilesTest.test_returns_ukrainian_target_language_profile tests.test_translation_profiles.TranslationProfilesTest.test_returns_ukrainian_profile_for_regional_language_tag tests.test_translation_profiles.TranslationProfilesTest.test_returns_stable_ukrainian_policy_signature_for_cache_keys
```

Expected: failures because `get_target_language_profile("uk")` currently returns `None` and `target_language_policy_signature("uk")` currently returns `target-profile:default-v1`.

- [ ] **Step 3: Implement language-root normalization**

In `src/translator_service/translation_profiles.py`, add this helper near the top-level functions:

```python
def _language_root(language_code: str) -> str:
    return language_code.strip().lower().replace("_", "-").split("-", 1)[0]
```

Then replace `get_target_language_profile()` with:

```python
def get_target_language_profile(
    target_language: str,
) -> TargetLanguageProfile | None:
    normalized = _language_root(target_language)
    if normalized == "ru":
        return RUSSIAN_PROFILE
    if normalized == "uk":
        return UKRAINIAN_PROFILE
    return None
```

- [ ] **Step 4: Add minimal Ukrainian profile data**

In `src/translator_service/translation_profiles.py`, add `UKRAINIAN_PROFILE` after `RUSSIAN_PROFILE` with this initial content:

```python
UKRAINIAN_PROFILE = TargetLanguageProfile(
    language_code="uk",
    version="ukrainian-v1",
    default_rules=(
        "Write natural contemporary standard Ukrainian according to the current official Ukrainian orthography standard.",
        "Avoid Russian calques, surzhyk, English word order, literal phrasal translations, and awkward nominalizations.",
        "Preserve meaning, tone, author voice, paragraph boundaries, and document structure.",
        "Do not add explanations or simplify specialized content unless the source does so.",
    ),
    named_entity_rules=(
        "Preserve brands, product names, legal company names, URLs, usernames, code identifiers, API names, package names, library names, commands, flags, filenames, and environment variables.",
        "Transcribe ordinary personal names for Ukrainian readers when the document is not a legal identity, citation, username, email, or code-owner context.",
        "Use established Ukrainian country and city names where they exist; preserve exact address components when precision matters.",
    ),
    terminology_rules=(
        "Use stable Ukrainian technical terminology where it is natural.",
        "Preserve exact English technical terms only when they are protected names, API references, or code-like identifiers.",
        "Keep the same terminology choice consistently throughout the document.",
        "Avoid false friends and calques such as actual, accurate, eventually, control, regular, data, decade, magazine, приймати участь, на протязі, являється, and слідуючий.",
    ),
    term_examples=(
        "query parameters -> параметри запиту",
        "regular expression -> регулярний вираз",
        "footnote -> виноска",
        "endnote -> кінцева виноска by context",
        "tracked changes -> виправлення or відстежені зміни by context",
        "section break -> розрив розділу",
        "table of contents -> зміст",
        "placeholder -> заповнювач in general UI context, плейсхолдер in technical UI/LLM context",
        "prompt -> промпт in LLM context, підказка only for user hints",
        "token -> токен in LLM/API/security context",
        "callback -> callback for exact code/API reference, зворотний виклик or колбек in explanatory prose by context",
        "endpoint -> endpoint for exact API references, кінцева точка or glossary-pinned ендпоінт in explanatory prose",
        "framework -> фреймворк",
    ),
    naturalness_examples=(
        "Do not translate made a decision as зробив рішення; prefer вирішив or ухвалив рішення by register.",
        "Do not translate participate as приймати участь; use брати участь.",
        "Do not translate during or over as на протязі unless the source literally describes physical draft or extension; use протягом.",
        "Do not translate is or constitutes as являється; use є, a verb, or a natural Ukrainian construction.",
    ),
    protected_grammar_examples=(
        "When preserved terms need Ukrainian grammar, write a Ukrainian support noun such as модуль FastAPI, пакет requests, метод callback, змінна PATH, or команда git commit.",
        "Do not add Ukrainian case endings inside inline code, API names, package names, URLs, commands, or protected markers.",
    ),
    text_type_rules={
        TextType.GENERAL: "Use clear contemporary Ukrainian with moderate rewriting for natural Ukrainian syntax.",
        TextType.LITERARY_FICTION: "Preserve voice, rhythm, dialogue, imagery, irony, ambiguity, and narrator perspective.",
        TextType.LITERARY_NON_FICTION: "Preserve author voice while producing polished editorial Ukrainian.",
        TextType.JOURNALISTIC_PUBLICISTIC: "Use readable Ukrainian publicistic style and preserve facts, attribution, dates, and quotes.",
        TextType.SCIENTIFIC_ACADEMIC: "Preserve claims, hedging, citations, units, formulas, and exact terminology.",
        TextType.TECHNICAL: "For technical documentation, be concise; preserve code identifiers, API names, package names, filenames, command flags, env vars, and product names.",
        TextType.BUSINESS_LEGAL_LIKE: "Use formal Ukrainian without creative paraphrase; preserve obligations, defined terms, dates, amounts, and legal entity names.",
        TextType.EDUCATIONAL: "Use clear explanatory Ukrainian and translate descriptive learning headings.",
        TextType.MARKETING: "Use idiomatic Ukrainian marketing copy without inventing claims, benefits, urgency, or guarantees.",
        TextType.MIXED_UNKNOWN: "Use conservative general Ukrainian with technical and named-entity protections enabled.",
    },
    quality_track_rules={
        RussianQualityTrack.LITERARY: "Literary Ukrainian quality track: preserve voice, rhythm, dialogue, imagery, narrator perspective, ambiguity, and author style; allow natural Ukrainian sentence restructuring when it improves literary fluency without adding explanations.",
        RussianQualityTrack.PRECISION: "Precision Ukrainian quality track: prioritize terminology, dates, numbers, legal obligations, structure, code, URLs, IDs, placeholders, tables, lists, and exact named entities over stylistic embellishment.",
    },
)
```

- [ ] **Step 5: Verify profile lookup tests pass**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_translation_profiles.TranslationProfilesTest.test_returns_ukrainian_target_language_profile tests.test_translation_profiles.TranslationProfilesTest.test_returns_ukrainian_profile_for_regional_language_tag tests.test_translation_profiles.TranslationProfilesTest.test_returns_stable_ukrainian_policy_signature_for_cache_keys
```

Expected: all three tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add tests/test_translation_profiles.py src/translator_service/translation_profiles.py
git commit -m "test: add Ukrainian target profile lookup"
```

---

### Task 2: Generalized Target Profile Prompt Builder

**Files:**
- Modify: `tests/test_translation_profiles.py`
- Modify: `src/translator_service/translation_profiles.py`

- [ ] **Step 1: Write failing Ukrainian prompt tests**

Add these methods to `TranslationProfilesTest`:

```python
    def test_builds_ukrainian_prompt_with_text_type_specific_rules(self):
        prompt = build_target_language_profile_prompt(
            target_language="uk",
            text_type=TextType.TECHNICAL,
            quality_track=RussianQualityTrack.PRECISION,
        )

        self.assertIn("Ukrainian target-language profile", prompt)
        self.assertIn("standard Ukrainian", prompt)
        self.assertIn("Avoid Russian calques", prompt)
        self.assertIn("technical documentation", prompt)
        self.assertIn("preserve code identifiers", prompt)
        self.assertIn("API names", prompt)
        self.assertIn("Transcribe ordinary personal names", prompt)
        self.assertIn("placeholder", prompt)
        self.assertIn("заповнювач", prompt)
        self.assertIn("Precision Ukrainian quality track", prompt)
        self.assertIn("dates, numbers, legal obligations", prompt)

    def test_ukrainian_prompt_includes_naturalness_and_protected_grammar_examples(self):
        prompt = build_target_language_profile_prompt(
            target_language="uk",
            text_type=TextType.GENERAL,
            quality_track=RussianQualityTrack.LITERARY,
        )

        self.assertIn("Do not translate made a decision as зробив рішення", prompt)
        self.assertIn("prefer вирішив or ухвалив рішення", prompt)
        self.assertIn("приймати участь", prompt)
        self.assertIn("брати участь", prompt)
        self.assertIn("на протязі", prompt)
        self.assertIn("протягом", prompt)
        self.assertIn("модуль FastAPI", prompt)
        self.assertIn("пакет requests", prompt)
        self.assertIn("змінна PATH", prompt)
        self.assertIn("Literary Ukrainian quality track", prompt)
        self.assertIn("voice, rhythm, dialogue, imagery", prompt)
```

- [ ] **Step 2: Verify RED for Ukrainian prompt labels**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_translation_profiles.TranslationProfilesTest.test_builds_ukrainian_prompt_with_text_type_specific_rules tests.test_translation_profiles.TranslationProfilesTest.test_ukrainian_prompt_includes_naturalness_and_protected_grammar_examples
```

Expected: failure because the prompt builder still emits hardcoded Russian labels such as `Russian target-language profile`.

- [ ] **Step 3: Add profile display names**

In `src/translator_service/translation_profiles.py`, add:

```python
_PROFILE_DISPLAY_NAMES = {
    "ru": "Russian",
    "uk": "Ukrainian",
}


def _profile_display_name(profile: TargetLanguageProfile) -> str:
    return _PROFILE_DISPLAY_NAMES.get(profile.language_code, profile.language_code)
```

- [ ] **Step 4: Generalize prompt labels**

Replace the `sections = [...]` block in `build_target_language_profile_prompt()` with:

```python
    display_name = _profile_display_name(profile)
    sections = [
        f"Target-language policy: {display_name} target-language profile {profile.version}.",
        f"Detected text type: {text_type.value}.",
        f"Text-type instruction: {text_type_rule}",
        quality_track_rule,
        f"Default {display_name} rules: " + " ".join(profile.default_rules),
        "Named entity rules: " + " ".join(profile.named_entity_rules),
        "Terminology rules: " + " ".join(profile.terminology_rules),
        "Term examples: " + "; ".join(profile.term_examples) + ".",
        f"{display_name} naturalness examples: "
        + " ".join(profile.naturalness_examples),
        "Protected-term grammar examples: "
        + " ".join(profile.protected_grammar_examples),
    ]
```

- [ ] **Step 5: Verify Ukrainian and Russian prompt tests pass**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_translation_profiles
```

Expected: all translation profile tests pass, including existing Russian prompt tests.

- [ ] **Step 6: Commit Task 2**

```bash
git add tests/test_translation_profiles.py src/translator_service/translation_profiles.py
git commit -m "feat: build Ukrainian target profile prompt"
```

---

### Task 3: Ukrainian Source-Pair Profiles

**Files:**
- Modify: `tests/test_source_pair_profiles.py`
- Modify: `src/translator_service/source_pair_profiles.py`

- [ ] **Step 1: Write failing Ukrainian source-pair tests**

In `tests/test_source_pair_profiles.py`, replace `test_non_russian_target_has_no_source_pair_guidance` with:

```python
    def test_language_pair_without_profile_has_no_source_pair_guidance(self):
        self.assertEqual(build_source_pair_profile_prompt("en", "fr"), "")
        self.assertEqual(source_pair_profile_signature("en", "fr"), "source-pair:none")
```

Add these tests:

```python
    def test_builds_english_to_ukrainian_guidance(self):
        prompt = build_source_pair_profile_prompt("en", "uk")

        self.assertIn("English to Ukrainian source-pair profile", prompt)
        self.assertIn("English word order", prompt)
        self.assertIn("phrasal verbs", prompt)
        self.assertIn("false friends", prompt)
        self.assertIn("Title Case", prompt)

    def test_builds_russian_to_ukrainian_guidance(self):
        prompt = build_source_pair_profile_prompt("ru", "uk")

        self.assertIn("Russian to Ukrainian source-pair profile", prompt)
        self.assertIn("standard Ukrainian", prompt)
        self.assertIn("not word-by-word replacement", prompt)
        self.assertIn("surzhyk", prompt)
        self.assertIn("приймати участь", prompt)

    def test_builds_mixed_auto_to_ukrainian_guidance(self):
        prompt = build_source_pair_profile_prompt("auto", "uk")

        self.assertIn("Mixed-source to Ukrainian source-pair profile", prompt)
        self.assertIn("source_language hints", prompt)
        self.assertIn("do not assume English", prompt)
        self.assertIn("translate every human-language span", prompt)
        self.assertIn("Ukrainian", prompt)

    def test_ukrainian_source_pair_signature_is_stable(self):
        self.assertEqual(
            source_pair_profile_signature("en-US", "uk-UA"),
            "source-pair:en-uk:v1",
        )
        self.assertEqual(
            source_pair_profile_signature("ru", "uk"),
            "source-pair:ru-uk:v1",
        )
        self.assertEqual(
            source_pair_profile_signature("auto", "uk"),
            "source-pair:auto-uk:v1",
        )
```

- [ ] **Step 2: Verify RED for Ukrainian source-pair profiles**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_source_pair_profiles.SourcePairProfilesTest.test_builds_english_to_ukrainian_guidance tests.test_source_pair_profiles.SourcePairProfilesTest.test_builds_russian_to_ukrainian_guidance tests.test_source_pair_profiles.SourcePairProfilesTest.test_builds_mixed_auto_to_ukrainian_guidance tests.test_source_pair_profiles.SourcePairProfilesTest.test_ukrainian_source_pair_signature_is_stable
```

Expected: failures because source-pair profiles currently return `None` for every non-Russian target.

- [ ] **Step 3: Remove Russian-only source-pair gate**

In `src/translator_service/source_pair_profiles.py`, replace `_profile_for_pair()` with:

```python
def _profile_for_pair(
    source_language: str,
    target_language: str,
) -> SourcePairProfile | None:
    normalized_target = _language_root(target_language)
    normalized_source = _language_root(source_language)
    return _SOURCE_PAIR_PROFILES.get(
        (normalized_source, normalized_target),
        _SOURCE_PAIR_PROFILES.get(("auto", normalized_target)),
    )
```

- [ ] **Step 4: Add Ukrainian source-pair entries**

In `_SOURCE_PAIR_PROFILES`, add these entries before `("auto", "ru")` or after the Russian entries:

```python
    ("en", "uk"): SourcePairProfile(
        source_language="en",
        target_language="uk",
        version="v1",
        prompt=(
            "Source-pair policy: English to Ukrainian source-pair profile. "
            "Translate meaning into idiomatic Ukrainian; avoid English word order, "
            "mechanical possessives, article-like phrasing, literal phrasal verbs, "
            "and Title Case capitalization. "
            "Resolve English false friends by context, including actual, accurate, "
            "eventually, control, regular, data, decade, and magazine. "
            "Preserve protected code, API, URL, and exact identifier text."
        ),
    ),
    ("ru", "uk"): SourcePairProfile(
        source_language="ru",
        target_language="uk",
        version="v1",
        prompt=(
            "Source-pair policy: Russian to Ukrainian source-pair profile. "
            "Translate close Slavic wording into standard Ukrainian, not word-by-word replacement. "
            "Avoid Russian syntax calques, surzhyk, and lexical calques such as "
            "приймати участь, на протязі, являється, and слідуючий. "
            "Do not preserve Russian words unless they are names, citations, usernames, "
            "addresses, legal identities, or protected text. "
            "Preserve tone and document register without over-formalizing shared phrasing."
        ),
    ),
    ("auto", "uk"): SourcePairProfile(
        source_language="auto",
        target_language="uk",
        version="v1",
        prompt=(
            "Source-pair policy: Mixed-source to Ukrainian source-pair profile. "
            "Use source_language hints when present, do not assume English, and translate "
            "every human-language span into Ukrainian, including secondary languages. "
            "Keep labels consistent in Ukrainian while preserving protected markers, code, "
            "URLs, placeholders, exact identifiers, and intentional names."
        ),
    ),
```

- [ ] **Step 5: Verify source-pair tests pass**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_source_pair_profiles
```

Expected: all source-pair profile tests pass, and existing Russian source-pair tests still pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add tests/test_source_pair_profiles.py src/translator_service/source_pair_profiles.py
git commit -m "feat: add Ukrainian source pair profiles"
```

---

### Task 4: Full Translation Policy Prompt Coverage

**Files:**
- Modify: `tests/test_translation_policy.py`
- Potentially no production-code changes if Tasks 1-3 are complete.

- [ ] **Step 1: Inspect existing translation policy test imports**

Open the top of `tests/test_translation_policy.py` and confirm it already imports:

```python
from translator_service.translation_policy import (
    build_system_prompt,
    build_translation_policy,
)
```

If the imports are grouped differently, reuse the existing import style.

- [ ] **Step 2: Add failing full-prompt test**

Add this test to the existing translation policy test class:

```python
    def test_ukrainian_target_profile_and_source_pair_guidance_in_system_prompt(self):
        policy = build_translation_policy(
            text="Set the API endpoint and pass the placeholder token to the callback handler.",
            source_language="en",
            target_language="uk",
        )

        system_prompt = build_system_prompt(policy)

        self.assertEqual(policy.target_language_policy, "target-profile:uk:ukrainian-v1")
        self.assertEqual(policy.source_pair_policy, "source-pair:en-uk:v1")
        self.assertIn("English to Ukrainian source-pair profile", system_prompt)
        self.assertIn("Ukrainian target-language profile", system_prompt)
        self.assertIn("standard Ukrainian", system_prompt)
        self.assertIn("Avoid Russian calques", system_prompt)
        self.assertIn("заповнювач", system_prompt)
        self.assertIn("модуль FastAPI", system_prompt)
```

- [ ] **Step 3: Verify RED or GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_translation_policy
```

Expected if Tasks 1-3 were implemented correctly: pass. If it fails, the failure should point to missing Ukrainian profile data in the system prompt. Fix only the missing profile/source-pair wiring, not unrelated policy behavior.

- [ ] **Step 4: Commit Task 4**

```bash
git add tests/test_translation_policy.py
git commit -m "test: cover Ukrainian translation policy prompt"
```

---

### Task 5: Cache Signature Coverage

**Files:**
- Modify: `tests/test_translation_cache.py`
- Potentially no production-code changes if Task 1 is complete.

- [ ] **Step 1: Locate target-language policy cache test**

Open `tests/test_translation_cache.py` and find `test_misses_when_target_language_policy_signature_changes`.

- [ ] **Step 2: Add a Ukrainian policy signature assertion**

If the test already builds policies directly, add this assertion near the existing Russian/default target-language signature coverage:

```python
        ukrainian_policy = build_translation_policy(
            text="Set the API endpoint.",
            source_language="en",
            target_language="uk",
        )
        ukrainian_signature = translation_policy_signature(ukrainian_policy)
        self.assertIn("target-profile:uk:ukrainian-v1", ukrainian_signature)
```

If that test uses monkeypatching that makes the assertion awkward, add a separate test method:

```python
    def test_ukrainian_target_language_policy_signature_is_in_cache_key(self):
        policy = build_translation_policy(
            text="Set the API endpoint.",
            source_language="en",
            target_language="uk",
        )

        signature = translation_policy_signature(policy)

        self.assertIn("target-profile:uk:ukrainian-v1", signature)
        self.assertIn("source-pair:en-uk:v1", signature)
```

- [ ] **Step 3: Verify cache tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_translation_cache
```

Expected: all translation cache tests pass.

- [ ] **Step 4: Commit Task 5**

```bash
git add tests/test_translation_cache.py
git commit -m "test: include Ukrainian profile in cache signatures"
```

---

### Task 6: Focused Verification

**Files:**
- No file changes expected.

- [ ] **Step 1: Run focused profile and policy tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_translation_profiles \
  tests.test_source_pair_profiles \
  tests.test_translation_policy \
  tests.test_translation_cache
```

Expected: all tests pass.

- [ ] **Step 2: Run import compilation**

Run:

```bash
PYTHONPATH=src python3 -m compileall src
```

Expected: compilation completes without syntax errors.

- [ ] **Step 3: Inspect final diff**

Run:

```bash
git diff -- src/translator_service/translation_profiles.py src/translator_service/source_pair_profiles.py tests/test_translation_profiles.py tests/test_source_pair_profiles.py tests/test_translation_policy.py tests/test_translation_cache.py
```

Expected: diff only contains Ukrainian profile/source-pair implementation and tests. No unrelated rewrites.

- [ ] **Step 4: Final commit if previous task commits were skipped**

If Task 1-5 commits were skipped, make one focused commit now:

```bash
git add src/translator_service/translation_profiles.py src/translator_service/source_pair_profiles.py tests/test_translation_profiles.py tests/test_source_pair_profiles.py tests/test_translation_policy.py tests/test_translation_cache.py
git commit -m "feat: add Ukrainian translation profile"
```

If Task 1-5 commits were already made, do not make an empty commit.

---

## Self-Review Checklist

- The plan starts with failing tests before production-code edits.
- Each task has a small red-green loop.
- The first implementation does not add Ukrainian deterministic QA or sample corpus work.
- The plan preserves existing Russian profile behavior.
- The plan accounts for `uk-UA` normalization.
- The plan updates the existing no-Ukrainian-source-pair test instead of leaving contradictory assertions.
- No implementation step requires external network access.
