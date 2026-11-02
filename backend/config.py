import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Load local development settings while allowing explicitly exported shell
# variables to take precedence over values in the project .env file.
load_dotenv(ROOT / ".env", override=False)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'modelstump.db'}")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", "qwen3:4b")
TARGET_MODEL = os.getenv("TARGET_MODEL", "qwen3:1.7b")
EXECUTION_TIMEOUT = float(os.getenv("EXECUTION_TIMEOUT", "3"))
MAX_OUTPUT_BYTES = int(os.getenv("MAX_OUTPUT_BYTES", "65536"))
EXECUTION_BACKEND = os.getenv(
    "EXECUTION_BACKEND",
    "unsafe_subprocess",
).strip().lower()
MOCK_PROVIDER = os.getenv("MODELSTUMP_PROVIDER", "ollama") == "mock"
