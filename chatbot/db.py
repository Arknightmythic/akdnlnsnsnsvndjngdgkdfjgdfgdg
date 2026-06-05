from sqlalchemy import MetaData, Table, text
from sqlalchemy.schema import CreateTable
from dotenv import load_dotenv

from ingestion.starrocks_connection import engine

load_dotenv()

metadata = MetaData()

class SQLDatabase:
    def get_table_info(self):
        metadata.reflect(bind=engine)
        full_schema_info = []
        
        for table_name, table in metadata.tables.items():
            ddl = str(CreateTable(table).compile(engine)).strip()
            if "ENGINE=" not in ddl:
                ddl += " ENGINE=OLAP"
            
            sample_data_block = ""
            try:
                with engine.connect() as conn:
                    result = conn.execute(text(f"SELECT * FROM `{table_name}` LIMIT 3"))
                    rows = result.fetchall()
                    column_names = result.keys()
                    
                    if rows:
                        sample_data_block = f"/*\n3 rows from {table_name} table:\n"
                        sample_data_block += "\t".join(column_names) + "\n"
                        for row in rows:
                            row_str = "\t".join(str(val) if val is not None else "None" for val in row)
                            sample_data_block += row_str + "\n"
                        sample_data_block += "*/"
                    else:
                        sample_data_block = f"/*\nTable {table_name} is empty.\n*/"
                        
            except Exception as e:
                sample_data_block = f"/*\nError fetching samples for {table_name}: {e}\n*/"

            full_schema_info.append(f"{ddl}\n\n{sample_data_block}")
        
        return "\n\n".join(full_schema_info)

    def run(self, query):
        with engine.connect() as conn:
            result = conn.execute(text(query))
            return str(result.fetchall())

db = SQLDatabase()