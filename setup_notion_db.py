import os
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

def setup_database():
    notion = Client(auth=NOTION_TOKEN)
    print("Configurando base de datos de Notion...")
    
    # Intentamos actualizar la base de datos para asegurar las propiedades necesarias
    properties = {
        "Name": {
            "title": {}
        },
        "Fecha": {
            "date": {}
        },
        "Estado": {
            "select": {
                "options": [
                    {"name": "Pendiente", "color": "yellow"},
                    {"name": "Notificado", "color": "green"}
                ]
            }
        },
        "NotificarAntes": {
            "number": {
                "format": "number"
            }
        },
        "TelegramUserID": {
            "number": {
                "format": "number"
            }
        }
    }
    
    try:
        notion.databases.update(
            database_id=NOTION_DATABASE_ID,
            properties=properties
        )
        print("✅ Base de datos configurada correctamente con las columnas necesarias.")
    except Exception as e:
        print(f"❌ Error configurando la base de datos: {e}")

if __name__ == "__main__":
    setup_database()
