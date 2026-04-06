# Bot de Telegram con Gemini

Este es un bot de Telegram que utiliza la API de Gemini de Google para responder mensajes.

## Configuración

1. **Instala las dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Obtén las claves API:**
   - **Gemini API Key:** Ve a [Google AI Studio](https://aistudio.google.com/app/apikey) y crea una clave API.
   - **Telegram Bot Token:** Habla con @BotFather en Telegram y crea un nuevo bot para obtener el token.

3. **Configura el archivo `.env`:**
   Edita el archivo `.env` y agrega tus claves:
   ```
   GEMINI_API_KEY=tu_clave_de_google_gemini
   TELEGRAM_BOT_TOKEN=tu_token_de_telegram
   ```

## Ejecutar el bot

```bash
python bot_gemini.py
```

El bot se conectará a Telegram y estará listo para responder mensajes.

## Comandos

- `/start` - Inicia la conversación
- `/clear` - Limpia el historial de conversación
- `/help` - Muestra ayuda

## Funcionalidades

- Responde en el mismo idioma que el usuario
- Mantiene el contexto de la conversación por usuario
- Usa el modelo Gemini 2.5 Flash (rápido y eficiente)
