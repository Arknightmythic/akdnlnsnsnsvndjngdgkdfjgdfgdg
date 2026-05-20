from sqlalchemy import create_engine
import os


DATABASE_URL = (
    f"mysql+pymysql://"
    f"{os.getenv('STARROCKS_USER')}:"
    f"{os.getenv('STARROCKS_PASSWORD')}@"
    f"{os.getenv('STARROCKS_HOST')}:"
    f"{os.getenv('STARROCKS_PORT')}/"
    f"{os.getenv('STARROCKS_DATABASE')}"
)


engine = create_engine(
    DATABASE_URL,

    pool_size=10, # numbers of persistent db connection
    max_overflow=20, # numbers of temporary extra connection on high spike
    pool_pre_ping=True, # check connection before hit
    pool_recycle=3600, # every specifie seconds, connection is rebuild

    echo=False
)