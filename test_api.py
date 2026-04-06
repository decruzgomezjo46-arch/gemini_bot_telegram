import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

def test_gemini():
    api_key = os.getenv("GEMINI_API_KEY")
    print(f"Testing with API Key: {api_key[:10]}...")
    genai.configure(api_key=api_key)
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content("Hola, ¿estás funcionando?")
        print("Response:", response.text)
    except Exception as e:
        print("Error details:", str(e))

if __name__ == "__main__":
    test_gemini()
