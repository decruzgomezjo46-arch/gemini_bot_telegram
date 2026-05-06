import os
import logging
from datetime import datetime
from notion_client import Client
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

logger = logging.getLogger(__name__)

def get_client():
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        return None
    return Client(auth=NOTION_TOKEN)

def initialize_database():
    """Initializes database properties if they don't exist."""
    notion = get_client()
    if not notion:
        return
        
    properties = {
        "Nombre": {"title": {}},
        "Fecha": {"date": {}},
        "Estado": {
            "select": {
                "options": [
                    {"name": "Pendiente", "color": "yellow"},
                    {"name": "Notificado", "color": "green"}
                ]
            }
        },
        "MinutosAntes": {"number": {"format": "number"}},
        "TelegramUserID": {"number": {"format": "number"}}
    }
    
    try:
        notion.databases.update(database_id=NOTION_DATABASE_ID, properties=properties)
        logger.info("Notion database properties updated successfully.")
    except Exception as e:
        logger.warning(f"Could not update Notion DB properties (might already exist): {e}")

def add_reminder(user_id: int, text: str, target_time: str, notify_before: int) -> str:
    notion = get_client()
    if not notion:
        raise ValueError("Notion no está configurado.")
        
    # target_time debe ser ISO 8601 (ej. "2026-05-05T15:00:00-06:00")
    new_page = {
        "Nombre": {"title": [{"text": {"content": text}}]},
        "Fecha": {"date": {"start": target_time}},
        "Estado": {"select": {"name": "Pendiente"}},
        "MinutosAntes": {"number": notify_before},
        "TelegramUserID": {"number": user_id}
    }
    
    res = notion.pages.create(parent={"database_id": NOTION_DATABASE_ID}, properties=new_page)
    return res["id"]

def get_pending_reminders():
    """Retorna todos los recordatorios pendientes para procesar."""
    notion = get_client()
    if not notion:
        return []
        
    res = notion.databases.query(
        database_id=NOTION_DATABASE_ID,
        filter={
            "property": "Estado",
            "select": {
                "equals": "Pendiente"
            }
        }
    )
    return res.get("results", [])

def get_user_reminders(user_id: int):
    """Retorna los recordatorios pendientes de un usuario específico."""
    notion = get_client()
    if not notion:
        return []
        
    res = notion.databases.query(
        database_id=NOTION_DATABASE_ID,
        filter={
            "and": [
                {
                    "property": "Estado",
                    "select": {
                        "equals": "Pendiente"
                    }
                },
                {
                    "property": "TelegramUserID",
                    "number": {
                        "equals": user_id
                    }
                }
            ]
        }
    )
    return res.get("results", [])

def mark_as_notified(page_id: str):
    notion = get_client()
    if not notion:
        return
        
    notion.pages.update(
        page_id=page_id,
        properties={
            "Estado": {"select": {"name": "Notificado"}}
        }
    )

def delete_reminder(page_id: str):
    notion = get_client()
    if not notion:
        return
    
    # En Notion "eliminar" es archivar
    notion.pages.update(
        page_id=page_id,
        archived=True
    )

# Inicializar propiedades al cargar si hay token
if NOTION_TOKEN:
    try:
        initialize_database()
    except Exception as e:
        logger.error(f"Error inicializando Notion: {e}")
