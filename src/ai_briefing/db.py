import psycopg
from .config import Settings

def get_conn(settings: Settings):
    return psycopg.connect(settings.database_url)
