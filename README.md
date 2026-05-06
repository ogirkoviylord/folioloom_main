# FolioLoom

Telegram bot prototype for translating books, chapters, and manuscripts.

FolioLoom is the Telegram product for the Folio & Loom translation workflow.
DeepSeek is an internal translation provider, not the user-facing brand.

## Current Prototype

Implemented:

- TXT upload validation and translation flow.
- DOCX text extraction, price estimation, and translation flow.
- EPUB text extraction, price estimation, and translation flow.
- DeepSeek chat-completions client.
- Fragmented TXT, DOCX, and EPUB translation runners.
- In-memory translation job status model.
- In-memory balance, ledger, order charge, and refund backend domain.
- aiogram runtime skeleton with `/start`, `/menu`, `/help`, `/language`, document upload, `/confirm`, `/cancel`, and `/status`.

The Telegram runtime currently translates TXT, DOCX, and EPUB files.

## Workspace Policy

Active development work must happen in the dev workspace:

```text
/Users/yuriimedvediev/Documents/New project 2 dev
```

The release workspace is reserved for the stable bot and must receive only reviewed, working changes ready for release:

```text
/Users/yuriimedvediev/Documents/New project 2
```

The legacy beta workspace must not be used for new development or updates:

```text
/Users/yuriimedvediev/Documents/New project 2 beta
```

Before changing files, confirm that the current working directory is the dev workspace unless the task explicitly says to prepare a release.

## Local Checks

Run from the project root:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall src
```

## DeepSeek Smoke Test

```bash
DEEPSEEK_API_KEY='your_key' PYTHONPATH=src python3 -m translator_service.deepseek_probe
```

## TXT Translation Probe

```bash
DEEPSEEK_API_KEY='your_key' PYTHONPATH=src python3 -m translator_service.translate_txt_probe
```

This writes `sample.en.txt` in the project root.

## Telegram Bot Prototype

Install dependencies first, preferably in a virtual environment:

```bash
python3 -m pip install -e .
```

Then run:

```bash
TELEGRAM_BOT_TOKEN='your_bot_token' \
DEEPSEEK_API_KEY='your_deepseek_key' \
PYTHONPATH=src \
python3 -m translator_service.bot
```

When startup succeeds, the terminal prints:

```text
Telegram bot polling started. Open Telegram and send /start.
```

Prototype flow:

1. Send `/start`.
2. Choose `📖 Translate a Book`, or use `🌍 Language` to change the interface language.
3. Upload a `.txt`, `.docx`, or `.epub` file.
4. Choose the translation target language button.
5. Review the estimate and translation summary.
6. Press the localized start button or send `/confirm`.
   Use the localized Back button before confirmation if the wrong file was uploaded.
7. The bot returns the translated file.

During long translations, press the localized Cancel button or send `/cancel` to stop after the current fragment and receive a partial translated file.

Use `/menu` to return to the main menu, `/help` for the help screen, and `/language` to show the interface language buttons again.

Interface messages are currently localized for English, Russian, Ukrainian, French, Spanish, and Dutch.

Sample documents for manual dev checks are in `test_samples/`. Regenerate them with:

```bash
python3 scripts/generate_sample_documents.py
```

For auto-restart during development:

```bash
TELEGRAM_BOT_TOKEN='your_bot_token' \
DEEPSEEK_API_KEY='your_deepseek_key' \
PYTHONPATH=src \
watchfiles "python3 -m translator_service.bot" src
```

## Stable and Dev Bots

Use two different Telegram bots from BotFather:

- stable bot: for the version users rely on;
- dev bot: for testing new behavior from the dev workspace.

Each bot must have its own `TELEGRAM_BOT_TOKEN`. Never run two polling
processes with the same token.

Create local env files from the examples:

```bash
cp .env.stable.example .env.stable
cp .env.dev.example .env.dev
```

Fill `.env.stable` with the stable bot token and `.env.dev` with the dev bot
token. These local files are ignored by git.

Run the stable bot in one terminal:

```bash
scripts/run_bot_env.sh .env.stable
```

Run the dev bot in another terminal:

```bash
scripts/run_bot_env.sh .env.dev
```

During development, you can run the dev bot with auto-restart:

```bash
set -a
source .env.dev
set +a
PYTHONPATH=src watchfiles "python3 -m translator_service.bot" src
```

For production later, stable and dev must also use separate databases, queues,
storage buckets, payment keys, and admin settings.

## Clean-Room Note

This project is implemented from scratch. Do not copy AGPL code, prompts, file structure, class/function names, tests, or implementation details from AGPL projects.
