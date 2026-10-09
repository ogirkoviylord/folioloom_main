# Test samples

## Repository-generated fixtures

`sample_book.*`, Russian/Ukrainian profile regression samples and the adversarial
glossary TXT/JSON fixtures are repository-generated test material. See
`scripts/generate_sample_documents.py` and the related regression modules.
The stress-test DOCX is a synthetic structural fixture.

## Project Gutenberg source fixtures

`pg78824-images-3.en-ru.epub` and `pg78824-images-3.en-uk.epub` both contain the
English source of *Girls together* by Amy Ella Blanchard. The suffixes identify
target-language checks; they do not indicate translated book contents.

The official catalog is https://www.gutenberg.org/ebooks/78824. The EPUB embeds
https://www.gutenberg.org/files/78824/78824-h/78824-h.htm as its source and a US
public-domain rights statement. This metadata provides source evidence beyond
the original local-file confirmation. Exact upstream byte identity has not been
independently established.

`gutenberg_time_machine_noimages.en.epub` is the English control source for
*The Time Machine* by H. G. Wells, catalog https://www.gutenberg.org/ebooks/35.

Checksums, source metadata and the remaining jurisdiction review are recorded
in `rights-manifest.json`. The Project Gutenberg license remains inside the
EPUBs. Its terms and rights outside the USA must be checked before distribution:
https://www.gutenberg.org/policy/license.html. A future source-code license does
not replace the separate conditions of these third-party books.

## Private external fixtures

Unverified third-party DOCX packs and translated EPUB artifacts are excluded
from the candidate public source history. Optional personally supplied files
belong in untracked `private_fixtures/`, not in the repository.

Tests are local/fake. Provider-backed tools require deliberate configuration;
fixtures and successful structural tests are not translation-quality evidence.
