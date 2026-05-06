# Despliegue en Render.com 🚀

## Paso 1: Subir tu código a GitHub

1. Abre https://github.com/new
2. Crea un nuevo repositorio llamado `gemini_bot_telegram`
3. Clona el repositorio en tu PC:
   ```bash
   git clone https://github.com/TU_USUARIO/gemini_bot_telegram.git
   cd gemini_bot_telegram
   ```
4. Copia todos los archivos de `gemini_proyect_asis` aquí
5. Sube los cambios:
   ```bash
   git add .
   git commit -m "Inicial: Bot Telegram con Gemini y Groq"
   git push origin main
   ```

**⚠️ IMPORTANTE:** NO subas el archivo `.env` (contiene tus claves API)
- Ya lo hemos excluido en `.gitignore`

---

## Paso 2: Crear cuenta en Render.com

1. Ve a https://render.com
2. Click en **"Sign Up"**
3. Registrarte con GitHub (el más fácil)
4. Autoriza a Render acceder a tu GitHub

---

## Paso 3: Desplegar en Render

1. En el dashboard de Render, click en **"New +"** → **"Web Service"**
2. Si no aparece tu repositorio:
   - Click en **"Connect account"**
   - Autoriza acceso a GitHub
3. Selecciona: `gemini_bot_telegram`
4. Configura:
   - **Name:** `gemini-telegram-bot`
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot_gemini.py`
   - **Plan:** `Free` (gratuito)

---

## Paso 4: Añadir Variables de Entorno

En Render, antes de hacer "Deploy":

1. Scroll hacia abajo hasta **"Environment"**
2. Agrega las siguientes variables (click en **"Add Environment Variable"**):

   ```
   TELEGRAM_BOT_TOKEN=tu_token_de_telegram_aqui
   GEMINI_API_KEY=tu_clave_gemini_aqui
   GROQ_API_KEY=tu_clave_groq_aqui
   GROQ_API_BASE=https://api.groq.com/v1
   ```

3. Click en **"Create Web Service"** / **"Deploy"**

---

## Paso 5: Esperar al despliegue

1. Render empezará a instalar dependencias y ejecutar el bot
2. Verás los logs en tiempo real
3. Cuando veas `"El bot está en línea y escuchando mensajes..."` = ¡LISTO!

---

## Resultados

✅ El bot estará **online 24/7** sin tu PC  
✅ Gratis (plan Free de Render)  
✅ Se despliega automáticamente cada vez que haces push a GitHub  

---

## Troubleshooting

**"ModuleNotFoundError"**
- Verifica que `requirements.txt` esté completo y con versiones específicas

**"Bot no responde"**
- Revisa los logs en Render para ver errores
- Verifica que las variables de entorno estén correctas

**"Cambié el código, ¿cómo actualizo?"**
- Haz push a GitHub y Render se redesplegará automáticamente

---

## Opcional: Webhook en lugar de Polling

Si quieres más eficiencia (sin encuestas constantes a Telegram):
- Edita `bot_gemini.py` para usar webhooks
- Requiere un endpoint HTTPS (Render lo proporciona)
- Consume menos recursos

¿Quieres que te ayude con esto?
