# DeepSeek Document Translator

Telegram service prototype for paid document translation through DeepSeek API.

## Current Prototype

Implemented:

- TXT upload validation and translation flow.
- DOCX text extraction and price estimation at domain level.
- DeepSeek chat-completions client.
- Fragmented TXT translation runner.
- In-memory translation job status model.
- aiogram runtime skeleton with `/start`, document upload, `/confirm`, and `/status`.

The Telegram runtime currently translates TXT files only. DOCX translation is intentionally not enabled in the bot flow yet.

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

Prototype flow:

1. Send `/start`.
2. Choose the target language button: `Русский`, `Українська`, `Français`, `Español`, or `English`.
3. Upload a `.txt` file.
4. Review the estimate.
5. Press `Подтвердить` or send `/confirm`.
6. The bot returns the translated TXT file.

Use `/language` to show the language buttons again.

## Clean-Room Note

This project is implemented from scratch. Do not copy AGPL code, prompts, file structure, class/function names, tests, or implementation details from AGPL projects.
