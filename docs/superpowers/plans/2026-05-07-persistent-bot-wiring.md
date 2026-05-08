# Persistent Bot Wiring Implementation Plan


**Goal:** Route Telegram confirmation for TXT, DOCX, and EPUB through the persistent job planner, stored work-unit executor, and persistent result assembly when object storage and the SQLite job store are configured.

**Architecture:** Keep the in-memory translation runner as a fallback for test/dev configurations without storage. When persistent infrastructure is available, create a format-specific persistent plan, translate stored units in order, report progress from completed work units, and assemble final or partial output from storage.

---

## Task 1: Add Bot-Service Coverage

- [x] Add a DOCX confirmation test proving the bot service creates a persistent job, translates stored work units, assembles a final DOCX, and attaches the final object key.
- [x] Add an EPUB cancellation test proving the bot service returns a partial EPUB with translated completed units and unchanged remaining content.
- [x] Verify both tests fail before production changes because DOCX/EPUB still use the old in-memory path.

## Task 2: Wire Persistent Formats

- [x] Replace the TXT-only persistent branch with a TXT/DOCX/EPUB persistent branch.
- [x] Create the correct persistent job plan for each document kind.
- [x] Assemble the correct final or partial output format for each document kind.
- [x] Preserve the old in-memory fallback when persistent infrastructure is not configured.

## Task 3: Verify

- [x] Run focused bot/persistent tests.
- [x] Run the full test suite.
- [x] Compile the source tree.
- [x] Run git diff checks.
- [ ] Commit the change.
