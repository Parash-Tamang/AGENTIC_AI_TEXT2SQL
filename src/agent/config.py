import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    ENV = os.getenv("ENV", "dev")

    DB_URL = os.getenv("DB_URL")
    DB_NAME = os.getenv("DB_NAME")
    DB_SERVER = os.getenv("DB_SERVER")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    VECTOR_DB_URL = os.getenv("VECTOR_DB_URL")
    DEFAULT_LLM_MODEL = os.getenv("DEFAULT_LLM_MODEL", "openai/gpt-oss-20b")

    # if not GROQ_API_KEY:
    #     print("API : ", GROQ_API_KEY)
    #     raise RuntimeError("GROQ_API_KEY is not set")
