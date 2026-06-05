from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()
engine = create_engine(
    f"mysql+pymysql://"
    f"{os.getenv('STARROCKS_USER')}:"
    f"{os.getenv('STARROCKS_PASSWORD')}@"
    f"{os.getenv('STARROCKS_HOST')}:"
    f"{os.getenv('STARROCKS_PORT')}/"
    f"{os.getenv('STARROCKS_DATABASE')}"
)

with engine.connect() as conn:
    row = conn.execute(text("SELECT * FROM manual_matches WHERE id_institution = 8466278")).mappings().first()
    print("manual_matches data:", row)
    
    # Let's also check if there is gender column
    # Just in case we missed it
