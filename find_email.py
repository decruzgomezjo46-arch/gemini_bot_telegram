import os
import json
from dotenv import load_dotenv

load_dotenv()

json_data = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
file_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")

print("--- Buscando correo del Service Account ---")

if json_data:
    try:
        data = json.loads(json_data)
        print(f"Correo encontrado (vía JSON): {data.get('client_email')}")
    except Exception as e:
        print(f"Error al leer GOOGLE_SERVICE_ACCOUNT_JSON: {e}")

elif file_path and os.path.exists(file_path):
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
            print(f"Correo encontrado (vía Archivo): {data.get('client_email')}")
    except Exception as e:
        print(f"Error al leer {file_path}: {e}")
else:
    print("No se encontraron credenciales de Google (JSON o Archivo) en las variables de entorno.")
    print("Asegúrate de tener GOOGLE_SERVICE_ACCOUNT_JSON o GOOGLE_SERVICE_ACCOUNT_FILE configurado.")
