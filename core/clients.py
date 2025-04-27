import os
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv() # Load variables from .env file

# --- Supabase Client --- 
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

if not supabase_url or not supabase_key:
    raise ValueError("Supabase URL and Service Key must be set in environment variables.")

supabase_client: Client = create_client(supabase_url, supabase_key)

# --- Google Gemini Client --- 
google_api_key = os.getenv("GOOGLE_API_KEY")

if not google_api_key:
    raise ValueError("Google API Key must be set in environment variables.")

genai.configure(api_key=google_api_key)

gemini_model = genai.GenerativeModel('gemini-1.5-flash') # Or other suitable model 