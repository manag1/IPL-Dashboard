import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError("Set GEMINI_API_KEY in .env")

GEMINI_MODEL = "gemini-3.5-flash-lite"
DOCUMENT_FOLDER = Path(r"C:\Users\rsrik\Desktop\My Programs\IPL\IPL\ipl_json")
BASE_DIR = Path(__file__).resolve().parent
DATA_FOLDER = BASE_DIR / "data"
DATA_FOLDER.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = DATA_FOLDER / "registry.db"
STORE_DISPLAY_NAME = "My Local RAG Knowledge Base"
STORE_CONFIG_FILE = DATA_FOLDER / "store_name.txt"

MAX_WORKERS = 10
MAX_RETRIES = 4
RETRY_BASE_SECONDS = 3

IGNORED_EXTENSIONS = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pyc",
    ".tmp",
    ".log",
}

IGNORED_DIRECTORIES = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
}
