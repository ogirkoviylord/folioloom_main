# Test Samples

This directory contains repository fixtures for local tests, tools, and
owner-approved development checks.

## Real-book EPUB fixture

The `pg78824-images-3` EPUB fixture was added from an owner-supplied local EPUB
file with explicit owner rights/permissive-use confirmation in the Codex thread
on 2026-06-12.

Files:

- `pg78824-images-3.en-ru.epub` - English source EPUB for Russian-target checks.
- `pg78824-images-3.en-uk.epub` - English source EPUB for Ukrainian-target checks.

Metadata confirmed locally:

- EPUB title metadata: `Girls together`
- EPUB creator metadata: `Amy Ella Blanchard`
- EPUB language metadata: `en`
- SHA-256: `318d2689b85dc57ae1e91307acebe3b61bf717ef72070aa0566f7f99b880d5a3`

Repository evidence for the original source URL or final license text is
`Unknown`; the committed fixture relies on the owner rights/permissive-use
confirmation above.

## Gutenberg no-images EPUB control fixture

The `gutenberg_time_machine_noimages` EPUB fixture was added from Project
Gutenberg as a small, text-heavy no-images EPUB control for EPUB glossary
runtime pressure checks.

Files:

- `gutenberg_time_machine_noimages.en.epub` - English source EPUB control for
  Russian/Ukrainian EPUB glossary runtime pressure and fake paired rehearsal
  checks.

Source metadata confirmed from Project Gutenberg on 2026-06-13:

- Project Gutenberg eBook No.: `35`
- Title: `The Time Machine`
- Author: `H. G. Wells`
- Language: `English`
- Category: `Text`
- Landing page: `https://www.gutenberg.org/ebooks/35`
- Download used: `https://www.gutenberg.org/ebooks/35.epub.noimages`
- Rights evidence: Project Gutenberg landing page says `Public domain in the
  USA`.
- SHA-256:
  `683bc9a24c75cece891dad50ed4b5cea1373a6ea2783863342dec2493adb1dc7`

Local metadata-only control result on 2026-06-13:

- Mode: local fake, no provider calls.
- Targets checked: `ru`, `uk`.
- Selected runtime unit: 12 source blocks, 816 source characters and 13
  protected markers.
- Fake paired glossary-on/glossary-off rehearsal status: validated for both
  targets.
- Quality claim: `Unknown`; fake output is not translation-quality evidence.

Do not copy raw excerpts, prompts, provider responses, translated text, or
diagnostic payloads from these fixtures into ordinary logs, GitHub issues, PR
descriptions, docs, release artifacts, support artifacts, or user-facing/admin
surfaces. Live provider use requires a separate explicit bounded approval.

## Synthetic adversarial glossary fixture

The `glossary_adversarial_terms` TXT fixture is a synthetic, owner-requested
control sample for glossary benefit checks. It uses invented English names that
look like ordinary phrases, with synthetic Russian and Ukrainian target
metadata that intentionally does not follow the plain literal translation.

Files:

- `glossary_adversarial_terms.en.txt` - English synthetic source fixture.
- `glossary_targets/glossary_adversarial_terms.runtime-glossary-targets.json` -
  owner-requested synthetic target metadata for Russian and Ukrainian
  local/fake glossary checks.

Purpose:

- local/fake glossary-on selection and prompt-context checks;
- future bounded live glossary-on/off provider smoke only after separate owner
  approval;
- no semantic-quality or rollout claim by itself.

Do not copy raw fixture excerpts, prompts, provider responses, translated text,
or diagnostic payloads into ordinary logs, GitHub issues, PR descriptions,
docs, release artifacts, support artifacts, or user-facing/admin surfaces.
Live provider use requires a separate explicit bounded approval.
