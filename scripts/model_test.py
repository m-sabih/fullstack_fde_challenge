import os

from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client()
print(client.models.generate_content(model=os.environ["GEMINI_MODEL"], contents="Hello").text)
