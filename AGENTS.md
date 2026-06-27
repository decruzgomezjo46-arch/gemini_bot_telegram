# gemini_bot_telegram

Bot de Telegram que usa la API de Google Gemini para responder mensajes. Incluye integración con Notion.

## Stack

- Python 3
- `python-telegram-bot` (Telegram API)
- `google-generativeai` (Gemini API)
- `notion-client` (Notion API)

## Files

- `bot.py` — lógica principal del bot
- `notion_service.py` — integración con Notion para guardar conversaciones
- `setup_notion_db.py` — script para configurar la base de datos en Notion
- `requirements.txt` — dependencias
- `Dockerfile` — para despliegue en contenedor
- `Procfile` — para despliegue en Render
- `RENDER_DEPLOYMENT.md` — guía de despliegue en Render

## Commands

```bash
pip install -r requirements.txt
python bot.py
```

## Environment Variables

- `GEMINI_API_KEY` — clave de Google Gemini
- `TELEGRAM_BOT_TOKEN` — token del bot de Telegram
