#!/bin/bash
# LegasVex — двойной клик → push на github.com/parafoto/legavex-platform
# Сохраняет существующую историю, добавляет новые файлы поверх

set -e
cd "$(dirname "$0")"
echo ""
echo "=== LegasVex → github.com/parafoto/legavex-platform ==="
echo ""

# Убираем sandbox .git
rm -rf .git

# Клонируем существующее репо (забираем историю)
echo "Получаю историю репо..."
git clone https://github.com/parafoto/legavex-platform.git .git_tmp

# Переносим историю в текущую папку
mv .git_tmp/.git ./.git
rm -rf .git_tmp

git config user.name "parafoto"
git config user.email "ynesnattalee@mail.com"

# Добавляем все новые файлы из legasvex-v2 поверх существующих
git add .
echo ""
echo "Новые/изменённые файлы:"
git diff --cached --name-only
echo ""

# Коммитим только если есть изменения
if git diff --cached --quiet; then
    echo "Изменений нет — всё уже актуально."
else
    git commit -m "Add: Telegram bot + multi-agent orchestrator + OSS docs

Services added:
- services/chat/telegram_assistant/ — Telegram bot (Bot API + Telethon)
- services/orchestrator/ — 8-role AgentCouncil with HITL StateMachine

Docs updated:
- README.md — full architecture with agent roles table
- .env.example — all 40+ environment variables documented
- requirements.txt — telethon, pypdf, python-dotenv, pyyaml
- CONTRIBUTING.md — contribution guidelines with HITL rules
- application_text.md — Claude for OSS program application

Features:
- Legal case law search: kad.arbitr.ru + sudact.ru
- Ollama (local, privacy-first) + OpenRouter LLM support
- Full audit trail with legal_significance tags"

    echo "Пушим..."
    git push origin main

    echo ""
    echo "=== Готово! ==="
fi

open https://github.com/parafoto/legavex-platform
