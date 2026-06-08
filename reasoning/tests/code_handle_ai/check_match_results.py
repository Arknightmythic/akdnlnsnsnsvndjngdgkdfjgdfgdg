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
    res = conn.execute(text("SELECT match_result, COUNT(*) as cnt FROM institution WHERE file_id = '558f1a53' GROUP BY match_result")).mappings().all()
    print("Match Results for 558f1a53:")
    for r in res:
        print(f"- {r['match_result']}: {r['cnt']}")
    
    # Let's also check ALL match_results in the whole table to find ANY MANUAL_REVIEW
    all_res = conn.execute(text("SELECT match_result, COUNT(*) as cnt FROM institution GROUP BY match_result")).mappings().all()
    print("\nMatch Results globally:")
    for r in all_res:
        print(f"- {r['match_result']}: {r['cnt']}")
