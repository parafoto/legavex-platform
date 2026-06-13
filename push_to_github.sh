#!/bin/bash
# LegasVex — одна команда для публикации на GitHub
# Запусти из папки legasvex-v2:  bash push_to_github.sh

set -e
cd "$(dirname "$0")"

echo "=== LegasVex → GitHub ==="

# Убираем .git от sandbox если есть
rm -rf .git

# Инициализация
git init -b main
git config user.name "parafoto"
git config user.email "ynesnattalee@mail.com"

# Индексируем всё кроме секретов
git add .
git status --short

# Коммит
git commit -m "Initial commit: LegasVex legal AI platform

Multi-agent legal assistant for Russian legal system:
- Telegram bot for advocates (Bot API + Telethon modes)
- 8-role AgentCouncil orchestrator with HITL enforcement
- Contract risk scanner
- Case law search: kad.arbitr.ru + sudact.ru
- Local LLM (Ollama) + OpenRouter support
- Full audit trail"

# Push
echo ""
echo "Репо создано локально. Теперь подключи GitHub:"
echo ""
echo "  git remote add origin https://github.com/parafoto/legasvex.git"
echo "  git push -u origin main"
echo ""
echo "Или запусти эти две строки прямо сейчас если репо уже создано на GitHub."
