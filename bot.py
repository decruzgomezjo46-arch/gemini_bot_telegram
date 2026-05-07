import os
import time
import logging
import json
import asyncio
import re
import uuid
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
import pytz
import inspect
import tempfile
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
import notion_service

# Cargar variables de entorno
load_dotenv()

# Configuración de Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = '''Eres un asistente personal de Telegram muy útil y conciso. 
Ayudas a los usuarios a recordar tareas usando Notion. Eres proactivo e inteligente.'''

AVAILABLE_MODELS = {
    "llama-3.3-70b-versatile": {
        "name": "🟠 Llama 3.3 70B Versatile",
        "limit": "30 req/min",
        "speed": "Rápido",
        "best_for": "Tareas complejas (RECOMENDADO)"
    },
    "llama-3.1-8b-instant": {
        "name": "⚡ Llama 3.1 8B Instant",
        "limit": "30 req/min",
        "speed": "Muy rápido",
        "best_for": "Respuestas rápidas"
    }
}

USER_PREFS_FILE = Path("user_preferences.json")

user_settings = {}
groq_chat_history = {}

DEFAULT_TIMEZONE = os.getenv("TIMEZONE", "America/Mexico_City")
tz = pytz.timezone(DEFAULT_TIMEZONE)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

def load_user_preferences():
    global user_settings
    if USER_PREFS_FILE.exists():
        try:
            raw = json.loads(USER_PREFS_FILE.read_text())
            for key, settings in raw.items():
                user_id = int(key)
                if isinstance(settings, dict) and "model" in settings:
                    user_settings[user_id] = settings
                else:
                    model = settings.get("model") if isinstance(settings, dict) else None
                    if model and model in AVAILABLE_MODELS:
                        user_settings[user_id] = {
                            "model": model,
                            "usage": settings.get("usage", {"count": 0, "last_reset": time.time()})
                        }
            logger.info(f"Preferencias cargadas para {len(user_settings)} usuarios")
        except Exception as e:
            logger.warning(f"Error cargando preferencias: {e}")

def save_user_preferences():
    try:
        data = {str(user_id): settings for user_id, settings in user_settings.items()}
        USER_PREFS_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Error guardando preferencias: {e}")

def get_user_model(user_id: int) -> str:
    return user_settings.get(user_id, {}).get("model", "llama-3.3-70b-versatile")

def set_user_model(user_id: int, model_name: str) -> None:
    if model_name not in AVAILABLE_MODELS:
        return
    settings = user_settings.setdefault(user_id, {})
    settings["model"] = model_name
    save_user_preferences()

def parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M")
        except Exception:
            return None

def parse_notify_before(value: str) -> int:
    if not value:
        return 10
    value = str(value).strip().lower()
    if value.isdigit():
        return int(value)
    match = re.search(r"(\d+)", value)
    if match:
        return int(match.group(1))
    return 10

# --- TOOLS (IA) ---



def tool_add_reminder(user_id: int, text: str, target_time_str: str, **kwargs) -> str:
    try:
        dt = parse_datetime(target_time_str)
        if not dt:
            return f"Error: Formato de fecha inválido '{target_time_str}'. Usa YYYY-MM-DD HH:MM."
        
        if dt.tzinfo is None:
            dt = tz.localize(dt)
        else:
            dt = dt.astimezone(tz)

        now_tz = datetime.now(tz)
        if dt < now_tz:
            return "Error: La fecha ya pasó. Elige un momento futuro."

        notion_time = dt.isoformat()
        reminder_id = notion_service.add_reminder(user_id, text, notion_time, 0)
        
        return f"✅ Recordatorio creado en Notion. ID: {reminder_id}, Para: {dt.strftime('%Y-%m-%d %H:%M')}."
    except Exception as e:
        return f"Error creando recordatorio: {e}"

def tool_search_web(query: str, **kwargs) -> str:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            
        if not results:
            return "No se encontraron resultados en la web."
            
        formatted = [f"Título: {r.get('title')}\nExtracto: {r.get('body')}\nEnlace: {r.get('href')}" for r in results]
        return "\n\n".join(formatted)
    except Exception as e:
        return f"Error buscando en la web: {e}"

def tool_send_image(query: str, **kwargs) -> str:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=1))
            
        if not results:
            return "No se encontraron imágenes en la web para esa consulta."
            
        image_url = results[0].get('image')
        return f"[IMAGEN: {image_url}]"
    except Exception as e:
        return f"Error buscando imagen: {e}"

def tool_list_reminders(user_id: int, status: str = "Pendiente", **kwargs) -> str:
    try:
        active = notion_service.get_user_reminders(user_id)
        if not active:
            return "No tienes recordatorios activos programados en Notion."
        
        res = "Recordatorios activos en Notion:\n"
        for r in active:
            r_id = r["id"]
            props = r["properties"]
            title_list = props.get("Nombre", {}).get("title", [])
            title = title_list[0].get("text", {}).get("content", "Sin título") if title_list else "Sin título"
            
            date_str = props.get("Fecha", {}).get("date", {}).get("start", "")
            if date_str:
                dt = datetime.fromisoformat(date_str)
                if dt.tzinfo is None:
                    dt = pytz.utc.localize(dt).astimezone(tz)
                else:
                    dt = dt.astimezone(tz)
                date_str = dt.strftime('%Y-%m-%d %H:%M')
                
            res += f"- ID: {r_id} | Fecha: {date_str} | Tarea: {title}\n"
        return res
    except Exception as e:
        return f"Error leyendo Notion: {e}"

def tool_delete_reminder(user_id: int, reminder_id: str, **kwargs) -> str:
    try:
        notion_service.delete_reminder(reminder_id)
        return f"✅ Recordatorio {reminder_id} cancelado correctamente en Notion."
    except Exception as e:
        return f"Error borrando recordatorio: {e}"

AVAILABLE_TOOLS = {
    "add_reminder": tool_add_reminder,
    "list_reminders": tool_list_reminders,
    "delete_reminder": tool_delete_reminder,
    "search_web": tool_search_web,
    "send_image": tool_send_image
}

GROQ_TOOLS_DEFINITION = [
    {
        "type": "function",
        "function": {
            "name": "add_reminder",
            "description": "Crea un recordatorio en Notion para el usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Descripción de la tarea."},
                    "target_time_str": {"type": "string", "description": "Fecha y hora en la que debe sonar el recordatorio (formato YYYY-MM-DD HH:MM)."}
                },
                "required": ["text", "target_time_str"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "Lista los recordatorios activos del usuario guardados en Notion.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Estado opcional a filtrar."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_reminder",
            "description": "Cancela/archiva un recordatorio de Notion usando su ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string", "description": "ID del recordatorio a eliminar."}
                },
                "required": ["reminder_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Busca información actualizada en internet usando DuckDuckGo. Útil para responder preguntas sobre actualidad o datos que no sabes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Término de búsqueda."}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_image",
            "description": "Busca y envía una imagen al usuario usando DuckDuckGo Images. Debe usarse cuando el usuario pide explícitamente una foto o imagen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Término de búsqueda de la imagen."}
                },
                "required": ["query"]
            }
        }
    }
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    current_model = get_user_model(user.id)
    groq_chat_history[user.id] = []

    await update.message.reply_text(
        f"¡Hola {user.first_name}! 👋\n\n"
        f"Usas el modelo **{AVAILABLE_MODELS[current_model]['name']}**.\n"
        "Ahora tus recordatorios se sincronizan automáticamente con **Notion**.\n\n"
        "**Comandos útiles:**\n"
        "/start - Reiniciar bot\n"
        "/model - Cambiar modelo de IA\n"
        "/clear - Borrar memoria actual\n"
        "/help  - Ver ayuda",
        parse_mode="Markdown"
    )

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    groq_chat_history[user.id] = []
    await update.message.reply_text("✨ He olvidado todo lo que hablamos. ¡Empecemos de nuevo!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 **Guía del Bot de IA con Notion**\n\n"
        "• **Conversación**: Escribe cualquier mensaje para charlar conmigo.\n"
        "• **Notion**: Pídeme con lenguaje natural: 'Acuérdame de comprar leche mañana a las 5pm' o '¿Qué pendientes tengo?'. Yo consultaré tu base de datos de Notion.\n"
        "• **Modelos**: Usa `/model` para elegir el modelo de IA.\n"
        "• **Privacidad**: Usa `/clear` para borrar el contexto de la charla actual.\n",
        parse_mode="Markdown"
    )

async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    current_model = get_user_model(user.id)

    keyboard = []
    for model_key, model_info in AVAILABLE_MODELS.items():
        label = f"{model_info['name']} {('✓' if model_key == current_model else '')}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"model_{model_key}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    message = "**Selecciona un modelo:**\n\n"
    for model_key, model_info in AVAILABLE_MODELS.items():
        marker = "➜ " if model_key == current_model else "  "
        message += f"{marker}**{model_info['name']}**\n"
        message += f"   Límite: {model_info['limit']}\n"
        message += f"   Velocidad: {model_info['speed']}\n"
        message += f"   Ideal para: {model_info['best_for']}\n\n"

    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user
    data = query.data

    if data.startswith("model_"):
        new_model = data.replace("model_", "")
        if new_model in AVAILABLE_MODELS:
            set_user_model(user.id, new_model)
            model_info = AVAILABLE_MODELS[new_model]
            await query.edit_message_text(
                f"✅ **Modelo cambiado a {model_info['name']}**\n\n"
                f"Límite: {model_info['limit']}\n"
                f"Velocidad: {model_info['speed']}\n"
                f"Ideal para: {model_info['best_for']}",
                parse_mode="Markdown"
            )
        else:
            await query.answer("❌ Modelo no válido", show_alert=True)
    else:
        await query.answer("Acción desconocida", show_alert=True)

async def process_groq_request(update: Update, prompt: str) -> str:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY no configurada")

    user_id = update.effective_user.id
    groq_model = get_user_model(user_id)
    
    history = groq_chat_history.setdefault(user_id, [])
    current_time_str = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    dynamic_system_prompt = f"{SYSTEM_PROMPT}\n\n[Info del Sistema: La hora y fecha actual es {current_time_str}]"
    
    if not history:
        history.append({"role": "system", "content": dynamic_system_prompt})
    elif history[0]["role"] == "system":
        history[0]["content"] = dynamic_system_prompt

    history.append({"role": "user", "content": prompt})
    
    if len(history) > 11:
        history = [history[0]] + history[-10:]
        groq_chat_history[user_id] = history

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": groq_model,
        "messages": history,
        "max_tokens": 800,
        "temperature": 0.7,
        "tools": GROQ_TOOLS_DEFINITION,
        "tool_choice": "auto",
        "parallel_tool_calls": False
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            
            for _ in range(5):
                if not data.get("choices") or data["choices"][0]["finish_reason"] != "tool_calls":
                    break
                
                message = data["choices"][0]["message"]
                tool_calls = message.get("tool_calls", [])
                history.append(message)
                
                for tool_call in tool_calls:
                    function_name = tool_call["function"]["name"]
                    function_args = json.loads(tool_call["function"]["arguments"]) if tool_call["function"]["arguments"] else {}
                    
                    logger.info(f"Groq calling tool: {function_name} with {function_args}")
                    
                    if not isinstance(function_args, dict):
                        function_args = {}

                    if function_name in ["add_reminder", "list_reminders", "delete_reminder"]:
                        function_args["user_id"] = user_id
                        
                    function_to_call = AVAILABLE_TOOLS.get(function_name)
                    if function_to_call:
                        sig = inspect.signature(function_to_call)
                        filtered_args = {k: v for k, v in (function_args or {}).items() if k in sig.parameters}
                        tool_result = function_to_call(**filtered_args)
                        
                        history.append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "name": function_name,
                            "content": str(tool_result)
                        })
                
                payload["messages"] = history
                response = await client.post(url, headers=headers, json=payload, timeout=30.0)
                response.raise_for_status()
                data = response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Error HTTP de Groq: {e.response.status_code} - {e.response.text}")
        raise RuntimeError(f"Error de API Groq: {e.response.text}")
    except Exception as e:
        logger.error(f"Error de conexión con Groq: {e}", exc_info=True)
        raise RuntimeError(f"Error al conectar con Groq: {str(e)}")

    if "choices" in data and len(data["choices"]) > 0:
        assistant_content = data["choices"][0].get("message", {}).get("content", "")
        if assistant_content:
            history.append({"role": "assistant", "content": assistant_content})
            
            # Interceptar petición de imagen en el texto del LLM
            img_match = re.search(r'\[IMAGEN:\s*(https?://[^\s\]]+)\]', assistant_content)
            if img_match:
                image_url = img_match.group(1)
                try:
                    await update.message.reply_photo(photo=image_url)
                    assistant_content = assistant_content.replace(img_match.group(0), "").strip()
                except Exception as e:
                    logger.error(f"Error enviando imagen extraída: {e}")
                    assistant_content += "\n*(No pude cargar la imagen obtenida de internet)*"
            
            # Fallback para tags de función filtrados en texto plano
            match = re.search(r'<function=([^>]+)>(.*?)</function>', assistant_content)
            if match:
                func_name = match.group(1)
                try:
                    func_args = json.loads(match.group(2))
                    logger.info(f"Groq fallback tool call: {func_name} with {func_args}")
                    
                    if func_name in ["add_reminder", "list_reminders", "delete_reminder"]:
                        func_args["user_id"] = user_id
                        
                    function_to_call = AVAILABLE_TOOLS.get(func_name)
                    if function_to_call:
                        sig = inspect.signature(function_to_call)
                        filtered_args = {k: v for k, v in func_args.items() if k in sig.parameters}
                        tool_result = function_to_call(**filtered_args)
                        
                        history.append({
                            "role": "user", 
                            "content": f"System (Tool Output): {str(tool_result)}\n\nAhora responde al usuario de manera natural confirmando la acción."
                        })
                        
                        async with httpx.AsyncClient() as client:
                            response = await client.post(url, headers=headers, json={"model": groq_model, "messages": history}, timeout=30.0)
                            response.raise_for_status()
                            data = response.json()
                            if "choices" in data and len(data["choices"]) > 0:
                                assistant_content = data["choices"][0].get("message", {}).get("content", "")
                                if assistant_content:
                                    history.append({"role": "assistant", "content": assistant_content})
                except Exception as e:
                    logger.error(f"Error procesando fallback tool: {e}")

            return assistant_content
    return ""

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_message = update.message.text

    if not user_message:
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        assistant_text = await process_groq_request(update, user_message)
        
        if not assistant_text:
            assistant_text = "⚠️ No obtuve respuesta de Llama. Intenta de nuevo."
        await update.message.reply_text(assistant_text, parse_mode=None)
    except Exception as e:
        logger.error(f"Error procesando mensaje: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {str(e)[:200]}", parse_mode=None)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message.voice: return
    
    await update.message.chat.send_action(action="record_voice")
    
    try:
        file = await update.message.voice.get_file()
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            temp_path = f.name
            
        await file.download_to_drive(custom_path=temp_path)
        
        # Transcribir con Groq Whisper
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
        
        async with httpx.AsyncClient() as client:
            with open(temp_path, "rb") as audio_file:
                files = {"file": ("audio.ogg", audio_file, "audio/ogg")}
                data = {"model": "whisper-large-v3-turbo"}
                response = await client.post(url, headers=headers, data=data, files=files, timeout=60.0)
                response.raise_for_status()
                transcription = response.json().get("text", "")
                
        if transcription:
            await update.message.reply_text(f"🎤 _Escuchado:_ {transcription}", parse_mode="Markdown")
            await update.message.chat.send_action(action="typing")
            assistant_text = await process_groq_request(update, transcription)
            if assistant_text:
                await update.message.reply_text(assistant_text, parse_mode=None)
        else:
            await update.message.reply_text("❌ No pude entender el audio.")
            
    except Exception as e:
        logger.error(f"Error procesando audio: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Hubo un error procesando tu audio: {str(e)[:100]}")
    finally:
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)

async def check_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    now_tz = datetime.now(tz)
    try:
        pending = notion_service.get_pending_reminders()
        for r in pending:
            props = r["properties"]
            user_id = props.get("TelegramUserID", {}).get("number")
            if not user_id: continue
            
            date_str = props.get("Fecha", {}).get("date", {}).get("start")
            if not date_str: continue
            
            dt_raw = datetime.fromisoformat(date_str)
            if dt_raw.tzinfo is None:
                reminder_time = tz.localize(dt_raw)
            else:
                reminder_time = dt_raw.astimezone(tz)
                
            notify_before = props.get("MinutosAntes", {}).get("number") or 0
            notify_at = reminder_time - timedelta(minutes=notify_before)
            
            if notify_at <= now_tz:
                title_list = props.get("Nombre", {}).get("title", [])
                title = title_list[0].get("text", {}).get("content", "Sin título") if title_list else "Sin título"
                
                message = (
                    f"⏰ *Recordatorio de Notion*: {title}\n"
                    f"Hora: {reminder_time.strftime('%Y-%m-%d %H:%M')}"
                )
                try:
                    await context.bot.send_message(chat_id=user_id, text=message, parse_mode="Markdown")
                    notion_service.mark_as_notified(r["id"])
                    logger.info(f"Recordatorio enviado a {user_id}: {title}")
                except Exception as e:
                    logger.error(f"Error enviando mensaje de recordatorio a {user_id}: {e}")
    except Exception as e:
        logger.error(f"Error verificando Notion: {e}")

def main() -> None:
    load_user_preferences()
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("Error: TELEGRAM_BOT_TOKEN no encontrado en el archivo .env")
        return

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    app.job_queue.run_repeating(check_reminders, interval=60, first=10)

    # SERVIDOR DE SALUD PARA RENDER (Opcional en Termux)
    if os.environ.get("RENDER"):
        def run_health_check():
            class HealthCheckHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.send_header("Content-type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"Bot is alive!")
                def log_message(self, format, *args):
                    pass
            port = int(os.environ.get("PORT", "10000"))
            server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
            logger.info(f"Iniciando servidor de salud en puerto {port}...")
            server.serve_forever()

        health_thread = threading.Thread(target=run_health_check, daemon=True)
        health_thread.start()

    logger.info("El bot está en línea y escuchando mensajes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot apagado por el usuario.")
    except Exception as e:
        logger.critical(f"Error fatal inesperado: {e}", exc_info=True)
