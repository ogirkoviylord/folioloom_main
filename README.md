# DeepSeek Document Translator

Telegram service prototype for paid document translation through DeepSeek API.

## Current Prototype

Implemented:

- TXT upload validation and translation flow.
- DOCX text extraction, price estimation, and translation flow.
- EPUB text extraction, price estimation, and translation flow.
- DeepSeek chat-completions client.
- Fragmented TXT, DOCX, and EPUB translation runners.
- In-memory translation job status model.
- In-memory balance, ledger, order charge, and refund backend domain.
- aiogram runtime skeleton with `/start`, document upload, `/confirm`, `/cancel`, and `/status`.

The Telegram runtime currently translates TXT, DOCX, and EPUB files.

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
2. Choose the bot interface language button: `Русский`, `Українська`, `Français`, `Español`, or `English`.
3. Upload a `.txt`, `.docx`, or `.epub` file.
4. Choose the translation target language button.
5. Review the estimate.
6. Press the localized confirm button or send `/confirm`.
   Use the localized Back button before confirmation if the wrong file was uploaded.
7. The bot returns the translated file.

During long translations, press the localized Cancel button or send `/cancel` to stop after the current fragment and receive a partial translated file.

Use `/language` to show the interface language buttons again.

Interface messages are currently localized for Russian, Ukrainian, French, Spanish, and English.

Sample documents for manual beta checks are in `test_samples/`. Regenerate them with:

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

## Stable and Beta Bots

Use two different Telegram bots from BotFather:

- stable bot: for the version users rely on;
- beta bot: for testing new behavior.

Each bot must have its own `TELEGRAM_BOT_TOKEN`. Never run two polling
processes with the same token.

Create local env files from the examples:

```bash
cp .env.stable.example .env.stable
cp .env.beta.example .env.beta
```

Fill `.env.stable` with the stable bot token and `.env.beta` with the beta bot
token. These local files are ignored by git.

Run the stable bot in one terminal:

```bash
scripts/run_bot_env.sh .env.stable
```

Run the beta bot in another terminal:

```bash
scripts/run_bot_env.sh .env.beta
```

During development, you can run beta with auto-restart:

```bash
set -a
source .env.beta
set +a
PYTHONPATH=src watchfiles "python3 -m translator_service.bot" src
```

For production later, stable and beta must also use separate databases, queues,
storage buckets, payment keys, and admin settings.

## Clean-Room Note

This project is implemented from scratch. Do not copy AGPL code, prompts, file structure, class/function names, tests, or implementation details from AGPL projects.
