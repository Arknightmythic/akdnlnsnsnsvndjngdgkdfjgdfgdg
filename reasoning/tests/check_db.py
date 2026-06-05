import os
from sqlalchemy import create_engine, inspect
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = f"mysql+pymysql://{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}@{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/{os.getenv('STARROCKS_DATABASE')}"
engine = create_engine(DATABASE_URL)
inspector = inspect(engine)
print('Tables:', inspector.get_table_names())
if 'institution' in inspector.get_table_names():
    print('institution columns:', [c['name'] for c in inspector.get_columns('institution')])
if 'master' in inspector.get_table_names():
    print('master columns:', [c['name'] for c in inspector.get_columns('master')])
if 'uploaded_files' in inspector.get_table_names():
    print('uploaded_files columns:', [c['name'] for c in inspector.get_columns('uploaded_files')])
