import os
import time
import logging
import json
import asyncio
import re
import uuid
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import requests
from PIL import Image
import io
import tempfile
from dotenv import load_dotenv
import google.generativeai as genai
import pytz
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

# Cargar variables de entorno
load_dotenv()

# Configuración de Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configurar Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

SYSTEM_PROMPT = """Eres un asistente útil y amigable para Telegram. 
Responde siempre en el mismo idioma que el usuario. 
Sé conciso pero completo en tus respuestas. 
Usa formato Markdown si es necesario para resaltar información."""

# Proveedores y modelos disponibles
AVAILABLE_PROVIDERS = {
    "gemini": "Gemini",
    "groq": "Groq"
}

AVAILABLE_MODELS = {
    "gemini": {
        "gemini-2.5-flash": {
            "name": "⚡ Gemini 2.5 Flash",
            "limit": "20 req/día",
            "speed": "Muy rápido",
            "best_for": "Balance velocidad/capacidad (RECOMENDADO)"
        },
        "gemini-2.5-flash-lite": {
            "name": "⚡ Gemini 2.5 Flash Lite",
            "limit": "20 req/día",
            "speed": "Muy rápido + eficiente",
            "best_for": "Tareas simples, conservar cuota"
        }
    },
    "groq": {
        "llama-3.1-8b-instant": {
            "name": "⚡ Llama 3.1 8B Instant",
            "limit": "30 req/min",
            "speed": "Muy rápido",
            "best_for": "Respuestas rápidas, bajo costo (RECOMENDADO PARA SPEED)"
        },
        "llama-3.3-70b-versatile": {
            "name": "🟠 Llama 3.3 70B Versatile",
            "limit": "30 req/min",
            "speed": "Rápido",
            "best_for": "Tareas más complejas, contexto largo (RECOMENDADO PARA CALIDAD)"
        }
    }
}

# Archivos de configuración
USER_PREFS_FILE = Path("user_preferences.json")
REMINDERS_FILE = Path("reminders.json")

# Configuración Google Calendar
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Diccionarios para almacenar datos
user_settings: dict[int, dict] = {}
model_instances: dict[str, any] = {}
chat_sessions: dict[int, any] = {}
reminders: dict[int, list[dict]] = {}
groq_chat_history: dict[int, list[dict]] = {}
calendar_service = None

# Configuración de Zona Horaria (puedes cambiarla en el .env)
DEFAULT_TIMEZONE = os.getenv("TIMEZONE", "America/Mexico_City")
tz = pytz.timezone(DEFAULT_TIMEZONE)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_BASE = os.getenv("GROQ_API_BASE", "https://api.groq.com/v1")

def load_user_preferences():
    """Cargar preferencias de usuarios desde JSON"""
    global user_settings
    if USER_PREFS_FILE.exists():
        try:
            raw = json.loads(USER_PREFS_FILE.read_text())
            for key, settings in raw.items():
                user_id = int(key)
                if isinstance(settings, dict) and "model" in settings:
                    user_settings[user_id] = settings
                else:
                    # Compatibilidad con el formato antiguo
                    model = settings.get("model") if isinstance(settings, dict) else None
                    if model:
                        user_settings[user_id] = {
                            "provider": "gemini",
                            "model": model,
                            "usage": settings.get("usage", {"count": 0, "last_reset": time.time()})
                        }
            logger.info(f"Preferencias cargadas para {len(user_settings)} usuarios")
        except Exception as e:
            logger.warning(f"Error cargando preferencias: {e}")


def load_reminders():
    """Cargar recordatorios de usuarios desde JSON"""
    global reminders
    if REMINDERS_FILE.exists():
        try:
            raw = json.loads(REMINDERS_FILE.read_text())
            reminders = {int(uid): data for uid, data in raw.items()}
            logger.info(f"Recordatorios cargados para {len(reminders)} usuarios")
        except Exception as e:
            reminders = {}
            logger.warning(f"Error cargando recordatorios: {e}")


def save_reminders():
    """Guardar recordatorios de usuarios en JSON"""
    try:
        data = {str(user_id): reminder_list for user_id, reminder_list in reminders.items()}
        REMINDERS_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Error guardando recordatorios: {e}")


def load_calendar_credentials() -> Credentials | None:
    """Cargar credenciales de servicio de Google Calendar desde env."""
    if GOOGLE_SERVICE_ACCOUNT_JSON:
        try:
            info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
            return Credentials.from_service_account_info(info, scopes=GOOGLE_CALENDAR_SCOPES)
        except Exception as e:
            logger.error(f"Error leyendo GOOGLE_SERVICE_ACCOUNT_JSON: {e}")
            return None

    if GOOGLE_SERVICE_ACCOUNT_FILE:
        try:
            return Credentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT_FILE, scopes=GOOGLE_CALENDAR_SCOPES)
        except Exception as e:
            logger.error(f"Error leyendo GOOGLE_SERVICE_ACCOUNT_FILE: {e}")
            return None

    return None


def get_calendar_service():
    """Obtener cliente de Google Calendar."""
    global calendar_service
    if calendar_service is None:
        creds = load_calendar_credentials()
        if not creds:
            raise RuntimeError("Google Calendar no está configurado. Define GOOGLE_SERVICE_ACCOUNT_JSON o GOOGLE_SERVICE_ACCOUNT_FILE.")
        calendar_service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return calendar_service


def get_calendar_events(days: int = 7, max_results: int = 10) -> list[dict]:
    service = get_calendar_service()
    now = datetime.utcnow().isoformat() + "Z"
    later = (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"
    events_result = service.events().list(
        calendarId=GOOGLE_CALENDAR_ID,
        timeMin=now,
        timeMax=later,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    return events_result.get("items", [])


def create_calendar_event(summary: str, start_time: datetime, duration_minutes: int = 60, description: str = "") -> dict:
    service = get_calendar_service()
    end_time = start_time + timedelta(minutes=duration_minutes)
    event_body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_time.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end_time.isoformat(), "timeZone": "UTC"}
    }
    event = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event_body).execute()
    return event


def parse_datetime(value: str) -> datetime | None:
    """Parsear fecha/hora en formato ISO o 'YYYY-MM-DD HH:MM'."""
    try:
        return datetime.fromisoformat(value)
    except Exception:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M")
        except Exception:
            return None


def parse_notify_before(value: str) -> int:
    """Parsear minutos antes para notificación de recordatorio."""
    if not value:
        return 10
    value = value.strip().lower()
    if value.isdigit():
        return int(value)
    match = re.search(r"(\d+)", value)
    if match:
        return int(match.group(1))
    return 10


def add_reminder(user_id: int, text: str, target_time: datetime, notify_before: int) -> str:
    reminder_id = str(uuid.uuid4())
    reminder_data = {
        "id": reminder_id,
        "text": text,
        "time": target_time.isoformat(),
        "notify_before": notify_before,
        "notified": False
    }
    reminders.setdefault(user_id, []).append(reminder_data)
    save_reminders()
    return reminder_id


def format_reminder(reminder: dict) -> str:
    reminder_time = datetime.fromisoformat(reminder["time"])
    return (
        f"ID: {reminder['id']}\n"
        f"Cuando: {reminder_time.strftime('%Y-%m-%d %H:%M')}\n"
        f"Recordatorio: {reminder['text']}\n"
        f"Notificar: {reminder['notify_before']} minutos antes"
    )


def save_user_preferences():
    """Guardar preferencias de usuarios en JSON"""
    try:
        data = {str(user_id): settings for user_id, settings in user_settings.items()}
        USER_PREFS_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Error guardando preferencias: {e}")


def get_user_provider(user_id: int) -> str:
    return user_settings.get(user_id, {}).get("provider", "gemini")


def get_user_model(user_id: int) -> str:
    provider = get_user_provider(user_id)
    return user_settings.get(user_id, {}).get("model", list(AVAILABLE_MODELS[provider].keys())[0])


def set_user_provider(user_id: int, provider: str) -> None:
    if provider not in AVAILABLE_PROVIDERS:
        return
    settings = user_settings.setdefault(user_id, {})
    settings["provider"] = provider
    settings.setdefault("model", list(AVAILABLE_MODELS[provider].keys())[0])
    save_user_preferences()


def set_user_model(user_id: int, model_name: str) -> None:
    provider = get_user_provider(user_id)
    if model_name not in AVAILABLE_MODELS.get(provider, {}):
        return
    settings = user_settings.setdefault(user_id, {})
    settings["model"] = model_name
    save_user_preferences()


def get_model_instance(model_name: str):
    """Obtener instancia cacheada del modelo Gemini"""
    if model_name not in model_instances:
        logger.info(f"Creando instancia para {model_name}")
        model_instances[model_name] = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=SYSTEM_PROMPT
        )
    return model_instances[model_name]


def increment_usage(user_id: int, model_name: str):
    settings = user_settings.setdefault(user_id, {})
    usage = settings.setdefault("usage", {"count": 0, "model": model_name, "last_reset": time.time()})
    usage["count"] = usage.get("count", 0) + 1
    usage["model"] = model_name
    usage["last_reset"] = usage.get("last_reset", time.time())
    save_user_preferences()

def get_chat_session(user_id: int):
    """Obtener o crear una sesión de chat Gemini para el usuario."""
    if user_id not in chat_sessions:
        provider = get_user_provider(user_id)
        model_name = get_user_model(user_id) if provider == "gemini" else "gemini-2.5-flash"
        model = get_model_instance(model_name)
        chat_sessions[user_id] = model.start_chat(history=[])
    return chat_sessions[user_id]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /start - Inicia la interacción y limpia la sesión anterior"""
    user = update.effective_user
    provider = get_user_provider(user.id)
    current_model = get_user_model(user.id)
    if provider == "gemini":
        model = get_model_instance(current_model)
        chat_sessions[user.id] = model.start_chat(history=[])

    await update.message.reply_text(
        f"¡Hola {user.first_name}! 👋\n\n"
        f"Usas el proveedor **{AVAILABLE_PROVIDERS[provider]}** y el modelo **{AVAILABLE_MODELS[provider][current_model]['name']}**.\n"
        "Ahora puedo **ver imágenes** y **escuchar notas de voz** (voz usa Gemini).\n\n"
        "**Comandos útiles:**\n"
        "/start - Reiniciar bot\n"
        "/provider - Cambiar proveedor\n"
        "/model - Cambiar modelo de IA\n"
        "/clear - Borrar nuestra memoria actual\n"
        "/help  - Ver ayuda",
        parse_mode="Markdown"
    )

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /clear - Limpia el historial de la sesión actual"""
    user = update.effective_user
    provider = get_user_provider(user.id)
    current_model = get_user_model(user.id) if provider == "gemini" else "gemini-2.5-flash"
    model = get_model_instance(current_model)
    chat_sessions[user.id] = model.start_chat(history=[])
    # También limpiar el historial de Groq
    if user.id in groq_chat_history:
        groq_chat_history[user.id] = []
    await update.message.reply_text("✨ He olvidado todo lo que hablamos (incluyendo Groq). ¡Empecemos de nuevo!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /help - Información sobre el bot"""
    await update.message.reply_text(
        "🤖 **Guía del Bot de IA**\n\n"
        "• **Conversación**: Escribe, envía una **foto** o una **nota de voz**.\n"
        "• **Contexto**: Recuerdo mensajes anteriores para dar mejores respuestas.\n"
        "• **Privacidad**: Usa `/clear` si quieres que borre el contexto de la charla actual.\n"
        "• **Proveedores**: Usa `/provider` para cambiar entre Gemini y Groq.\n"
        "• **Modelos**: Usa `/model` para elegir un modelo del proveedor activo.\n"
        "• **Recordatorios**: Usa `/recordatorio` para crear un recordatorio.\n"
        "  Ejemplo: `/recordatorio 2026-04-07 19:00 | Pagar facturas | 10`\n"
        "• **Mis recordatorios**: Usa `/misrecordatorios` para ver tus recordatorios.\n"
        "• **Borrar recordatorio**: Usa `/borrarrecordatorio <id>`.\n"
        "• **Calendario**: Usa `/eventos` para ver tus próximos eventos de Google Calendar.\n"
        "• **Agendar**: Usa `/agendar YYYY-MM-DD HH:MM | Título | minutos_duración | descripción`.\n\n"
        "Voz e imagen usan Gemini porque el procesamiento de audio/imagen es más completo allí.",
        parse_mode="Markdown"
    )

async def eventos_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /eventos - Mostrar próximos eventos de Google Calendar."""
    try:
        events = get_calendar_events(days=7, max_results=10)
        if not events:
            await update.message.reply_text("No encontré eventos próximos en tu calendario.")
            return

        lines = []
        for event in events:
            start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
            summary = event.get("summary", "Sin título")
            lines.append(f"• {start}: {summary}")

        await update.message.reply_text("📅 *Próximos eventos:*\n" + "\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error al obtener eventos de calendario: {e}")
        await update.message.reply_text("No pude conectar con Google Calendar. Revisa la configuración.")

async def agendar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /agendar - Crear un evento en Google Calendar."""
    if not context.args:
        await update.message.reply_text(
            "Uso: /agendar YYYY-MM-DD HH:MM | Título | minutos_duración | descripción\n"
            "Ejemplo: /agendar 2026-04-07 19:00 | Reunión con equipo | 60 | Revisar objetivos"
        )
        return

    parts = " ".join(context.args).split("|")
    if len(parts) < 2:
        await update.message.reply_text(
            "Por favor usa el formato: `YYYY-MM-DD HH:MM | Título | minutos_duración | descripción`",
            parse_mode=None
        )
        return

    time_part = parts[0].strip()
    title = parts[1].strip()
    duration = int(parts[2].strip()) if len(parts) > 2 and parts[2].strip().isdigit() else 60
    description = parts[3].strip() if len(parts) > 3 else ""
    start_time = parse_datetime(time_part)

    if not start_time:
        await update.message.reply_text("No pude leer la fecha/hora. Usa `YYYY-MM-DD HH:MM`.")
        return

    try:
        event = create_calendar_event(title, start_time, duration_minutes=duration, description=description)
        await update.message.reply_text(
            f"✅ Evento creado: {event.get('htmlLink', 'Enlace no disponible')}"
        )
    except Exception as e:
        logger.error(f"Error creando evento de calendario: {e}")
        await update.message.reply_text("No pude crear el evento. Revisa la configuración de Google Calendar.")

async def provider_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /provider - Cambiar proveedor de IA"""
    user = update.effective_user
    current_provider = get_user_provider(user.id)

    keyboard = []
    for provider_key, provider_name in AVAILABLE_PROVIDERS.items():
        label = f"{provider_name} {('✓' if provider_key == current_provider else '')}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"provider_{provider_key}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🤖 **Selecciona un proveedor:**",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /model - Cambiar entre modelos disponibles"""
    user = update.effective_user
    provider = get_user_provider(user.id)
    current_model = get_user_model(user.id)

    keyboard = []
    for model_key, model_info in AVAILABLE_MODELS[provider].items():
        label = f"{model_info['name']} {('✓' if model_key == current_model else '')}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"model_{model_key}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    message = f"🤖 **Proveedor actual:** {AVAILABLE_PROVIDERS[provider]}\n\n"
    message += "**Selecciona un modelo:**\n\n"
    for model_key, model_info in AVAILABLE_MODELS[provider].items():
        marker = "➜ " if model_key == current_model else "  "
        message += f"{marker}**{model_info['name']}**\n"
        message += f"   Límite: {model_info['limit']}\n"
        message += f"   Velocidad: {model_info['speed']}\n"
        message += f"   Ideal para: {model_info['best_for']}\n\n"

    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manejar clics en botones de cambio de proveedor/modelo"""
    query = update.callback_query
    user = query.from_user
    data = query.data

    if data.startswith("provider_"):
        new_provider = data.replace("provider_", "")
        if new_provider in AVAILABLE_PROVIDERS:
            set_user_provider(user.id, new_provider)
            provider_name = AVAILABLE_PROVIDERS[new_provider]
            await query.edit_message_text(
                f"✅ **Proveedor cambiado a {provider_name}**\n\n"
                "Usa `/model` para elegir ahora un modelo de este proveedor.",
                parse_mode="Markdown"
            )
        else:
            await query.answer("❌ Proveedor no válido", show_alert=True)

    elif data.startswith("model_"):
        new_model = data.replace("model_", "")
        provider = get_user_provider(user.id)
        if new_model in AVAILABLE_MODELS.get(provider, {}):
            set_user_model(user.id, new_model)
            if provider == "gemini":
                model = get_model_instance(new_model)
                chat_sessions[user.id] = model.start_chat(history=[])
            model_info = AVAILABLE_MODELS[provider][new_model]
            await query.edit_message_text(
                f"✅ **Modelo cambiado a {model_info['name']}**\n\n"
                f"Límite: {model_info['limit']}\n"
                f"Velocidad: {model_info['speed']}\n"
                f"Ideal para: {model_info['best_for']}",
                parse_mode="Markdown"
            )
        else:
            await query.answer("❌ Modelo no válido para este proveedor", show_alert=True)
    else:
        await query.answer("Acción desconocida", show_alert=True)

async def process_groq_request(update: Update, prompt: str) -> str:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY no configurada")

    user_id = update.effective_user.id
    model_name = get_user_model(user_id)
    groq_model = model_name if model_name in AVAILABLE_MODELS["groq"] else list(AVAILABLE_MODELS["groq"].keys())[0]
    
    # Obtener historial de Groq (limitado a últimos 10 mensajes)
    history = groq_chat_history.setdefault(user_id, [])
    history.append({"role": "user", "content": prompt})
    if len(history) > 10:
        history.pop(0)

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": groq_model,
        "messages": history,
        "max_tokens": 500,
        "temperature": 0.7
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=30.0)
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        logger.error(f"Error de conexión con Groq: {e}", exc_info=True)
        raise RuntimeError(f"Error al conectar con Groq: {str(e)}")

    if "choices" in data and len(data["choices"]) > 0:
        assistant_content = data["choices"][0].get("message", {}).get("content", "")
        if assistant_content:
            # Añadir respuesta del asistente al historial
            history.append({"role": "assistant", "content": assistant_content})
            return assistant_content
    return ""

async def process_gemini_request(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: any) -> None:
    """Procesar cualquier solicitud (texto, imagen, audio) con Gemini"""
    user = update.effective_user
    provider = get_user_provider(user.id)
    current_model = get_user_model(user.id) if provider == "gemini" else "gemini-2.5-flash"

    try:
        chat = get_chat_session(user.id)
        response = chat.send_message(prompt)
        increment_usage(user.id, current_model)

        if response.candidates and response.candidates[0].content.parts:
            assistant_text = response.text
        else:
            assistant_text = "⚠️ Lo siento, no puedo procesar esto por razones de seguridad o formato."

        await update.message.reply_text(assistant_text, parse_mode=None)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error en Gemini: {error_msg}", exc_info=True)
        if "429" in error_msg or "quota" in error_msg.lower() or "exceeded" in error_msg.lower():
            model_info = AVAILABLE_MODELS["gemini"][current_model]
            other_models = [AVAILABLE_MODELS["gemini"][m]["name"] for m in AVAILABLE_MODELS["gemini"] if m != current_model]
            response_text = (
                f"⚠️ **Cuota agotada en {model_info['name']}**\n\n"
                f"La solicitud ha excedido el límite diario ({model_info['limit']}).\n\n"
                f"**Opciones:**\n"
                f"1️⃣ Usa /model para cambiar a otro modelo\n"
                f"2️⃣ Intenta mañana\n"
                f"3️⃣ Suscríbete a un plan de pago\n\n"
                f"Otros modelos disponibles: {', '.join(other_models)}"
            )
        else:
            response_text = f"❌ Error: {error_msg[:200]}"
        await update.message.reply_text(response_text, parse_mode=None)

async def process_user_request(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str) -> None:

    """Procesar mensajes de texto por el proveedor seleccionado"""
    user = update.effective_user
    provider = get_user_provider(user.id)
    model_name = get_user_model(user.id)

    try:
        if provider == "groq":
            assistant_text = await process_groq_request(update, prompt)
        else:
            await process_gemini_request(update, context, prompt)
            return

        increment_usage(user.id, model_name)
        if not assistant_text:
            assistant_text = "⚠️ No obtuve respuesta del modelo Groq. Intenta de nuevo."
        await update.message.reply_text(assistant_text, parse_mode=None)
    except Exception as e:
        logger.error(f"Error en {provider}: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {str(e)[:200]}", parse_mode=None)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manejar mensajes de texto del usuario"""
    user = update.effective_user
    user_message = update.message.text

    if not user_message:
        return

    await process_user_request(update, context, user_message)


async def recordatorio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /recordatorio - Crear un nuevo recordatorio."""
    user = update.effective_user
    args = context.args

    if not args:
        await update.message.reply_text(
            "Uso: /recordatorio YYYY-MM-DD HH:MM | Texto del recordatorio | minutos_antes\n"
            "Ejemplo: /recordatorio 2026-04-07 19:00 | Pagar facturas | 10"
        )
        return

    parts = " ".join(args).split("|")
    if len(parts) < 2:
        await update.message.reply_text(
            "Por favor usa el formato: `YYYY-MM-DD HH:MM | Texto del recordatorio | minutos_antes`",
            parse_mode=None
        )
        return

    time_part = parts[0].strip()
    text = parts[1].strip()
    notify_before = parse_notify_before(parts[2].strip()) if len(parts) > 2 else 10
    target_time = parse_datetime(time_part)

    if not target_time:
        await update.message.reply_text("No pude leer la fecha/hora. Usa `YYYY-MM-DD HH:MM`.")
        return

    # Localizar el tiempo objetivo a la zona horaria del bot
    target_time = tz.localize(target_time)
    now_tz = datetime.now(tz)

    if target_time < now_tz:
        await update.message.reply_text("La fecha ya pasó. Elige un momento futuro.")
        return

    reminder_id = add_reminder(user.id, text, target_time, notify_before)
    await update.message.reply_text(
        f"✅ Recordatorio creado:\nID: {reminder_id}\n" +
        f"Cuando: {target_time.strftime('%Y-%m-%d %H:%M')}\n" +
        f"Te avisaré {notify_before} minutos antes."
    )


async def misrecordatorios_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /misrecordatorios - Mostrar recordatorios activos."""
    user = update.effective_user
    user_reminders = reminders.get(user.id, [])

    if not user_reminders:
        await update.message.reply_text("No tienes recordatorios activos.")
        return

    lines = [format_reminder(rem) for rem in user_reminders]
    await update.message.reply_text("\n\n".join(lines))


async def borrarrecordatorio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /borrarrecordatorio - Eliminar un recordatorio."""
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("Uso: /borrarrecordatorio <id>")
        return

    reminder_id = context.args[0].strip()
    user_reminders = reminders.get(user.id, [])
    remaining = [rem for rem in user_reminders if rem["id"] != reminder_id]
    if len(remaining) == len(user_reminders):
        await update.message.reply_text("No encontré ese ID de recordatorio.")
        return

    reminders[user.id] = remaining
    save_reminders()
    await update.message.reply_text("✅ Recordatorio eliminado.")


async def check_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    now_tz = datetime.now(tz)
    # logger.debug(f"Verificando recordatorios en {now_tz}") # Comentar si es muy ruidoso
    
    for user_id, user_reminders in list(reminders.items()):
        updated = False
        for reminder in user_reminders:
            if reminder.get("notified"):
                continue
            
            try:
                # Parsear el tiempo guardado
                dt_raw = datetime.fromisoformat(reminder["time"])
                
                # Si no tiene zona horaria (naive), la localizamos. 
                # Si ya tiene (aware), la usamos directamente.
                if dt_raw.tzinfo is None:
                    reminder_time = tz.localize(dt_raw)
                else:
                    reminder_time = dt_raw
                    
                notify_before = int(reminder.get("notify_before", 0))
                notify_at = reminder_time - timedelta(minutes=notify_before)
                
                if notify_at <= now_tz:
                    chat_id = user_id
                    message = (
                        f"⏰ *Recordatorio*: {reminder['text']}\n"
                        f"Hora: {reminder_time.strftime('%Y-%m-%d %H:%M')}"
                    )
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
                        reminder["notified"] = True
                        updated = True
                        logger.info(f"Recordatorio enviado a {user_id}: {reminder['text']}")
                    except Exception as e:
                        logger.error(f"Error al enviar mensaje de recordatorio a {user_id}: {e}")
            except Exception as e:
                logger.error(f"Error procesando recordatorio individual para {user_id}: {e}")
                
        if updated:
            save_reminders()

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manejar fotos enviadas por el usuario"""
    user = update.effective_user
    photo_file = await update.message.photo[-1].get_file()
    caption = update.message.caption or "¿Qué hay en esta imagen?"
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    # Descargar la foto en memoria
    photo_bytes = await photo_file.download_as_bytearray()
    img = Image.open(io.BytesIO(photo_bytes))
    
    await process_gemini_request(update, context, [img, caption])

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manejar notas de voz enviadas por el usuario"""
    user = update.effective_user
    voice_file = await update.message.voice.get_file()
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    # Gemini soporta OGG/Opus. Descargamos a un archivo temporal.
    with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as tmp_file:
        await voice_file.download_to_drive(custom_path=tmp_file.name)
        tmp_path = tmp_file.name

    try:
        # Nota: Subir archivo a la API de Gemini (File API)
        logger.info(f"Subiendo archivo de voz: {tmp_path}")
        media_file = genai.upload_file(path=tmp_path, mime_type="audio/ogg")
        
        # Esperar a que el archivo esté listo (ACTIVE)
        # Esto es necesario para que el modelo pueda "escucharlo"
        max_retries = 10
        retries = 0
        while media_file.state.name == "PROCESSING" and retries < max_retries:
            logger.info(f"Procesando audio... (intento {retries+1})")
            time.sleep(1)
            media_file = genai.get_file(media_file.name)
            retries += 1
            
        if media_file.state.name == "FAILED":
            raise Exception("El procesamiento del audio falló en los servidores de Gemini.")
            
        logger.info(f"Audio listo. Estado: {media_file.state.name}")
        
        prompt = [
            media_file, 
            "He compartido contigo una nota de voz. Por favor, escúchala atentamente, transcribe su contenido si es necesario y responde a lo que se dice en ella."
        ]
        await process_gemini_request(update, context, prompt)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def main() -> None:
    """Punto de entrada principal para el bot"""
    # Cargar preferencias al iniciar
    load_user_preferences()
    load_reminders()
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not token:
        logger.error("Error: TELEGRAM_BOT_TOKEN no encontrado en el archivo .env")
        return

    # Crear la aplicación de Telegram
    app = Application.builder().token(token).build()

    # Registrar manejadores de comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("provider", provider_command))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("recordatorio", recordatorio_command))
    app.add_handler(CommandHandler("misrecordatorios", misrecordatorios_command))
    app.add_handler(CommandHandler("borrarrecordatorio", borrarrecordatorio_command))
    app.add_handler(CommandHandler("eventos", eventos_command))
    app.add_handler(CommandHandler("agendar", agendar_command))
    
    # Manejador de callbacks para cambio de proveedor/modelo
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Manejador para cualquier mensaje de texto (que no sea comando)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Manejadores para fotos y notas de voz
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # Scheduler de recordatorios
    app.job_queue.run_repeating(check_reminders, interval=60, first=10)

    # --- SERVIDOR DE SALUD PARA RENDER ---
    def run_health_check():
        class HealthCheckHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Bot is alive!")
                logger.info(f"Ping de salud recibido desde {self.client_address[0]}")

            def log_message(self, format, *args):
                pass

        port = int(os.environ.get("PORT", "10000"))
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        logger.info(f"Iniciando servidor de salud en puerto {port}...")
        server.serve_forever()

    health_thread = threading.Thread(target=run_health_check, daemon=True)
    health_thread.start()
    # -------------------------------------

    # Iniciar el bot (polling)
    logger.info("El bot está en línea y escuchando mensajes...")
    
    # app.run_polling() es bloqueante y maneja su propio bucle de eventos.
    # En Render, esto es lo más estable.
    app.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

if __name__ == "__main__":
    main()
