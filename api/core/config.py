import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    MONGODB_URL = os.getenv("MONGODB_URL")
    DB_NAME = os.getenv("DB_NAME")
    META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID")
    META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
    META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN")
    ACCOUNT_SID = os.getenv("ACCOUNT_SID")
    AUTH_TOKEN = os.getenv("AUTH_TOKEN")
    FROM_WA_NUMBER = os.getenv("FROM_WA_NUMBER")

settings = Settings()