from sqlalchemy import text
from typing import Any
from dotenv import load_dotenv
import os

from ingestion.starrocks_connection import engine

load_dotenv()

class MySQLDatabase:
    def get_table_names(self)-> list[str]:
        try:
            with engine.connect() as conn:
                cursor_result  = conn.execute(text("SHOW TABLES;"))
                table_names = [result[0] for result in cursor_result.fetchall()]
                return table_names
        except Exception as e:
            print(f"Error: {e}")
            
    def get_table_schema(self, table_name: str)-> str:
        try:
            with engine.connect() as conn:
                cursor_result =  conn.execute((text(f"SHOW CREATE TABLE `{table_name}`")))
                schema = cursor_result.fetchone()[1]
                
                cursor_result = conn.execute(text(f"SELECT * FROM {table_name} LIMIT 3"))
                column_names = cursor_result.keys()
                records = cursor_result.fetchall()
                
                sample_data = "\t".join(column_names)
                for record in records:
                    record = "\t".join([str(cell) for cell in list(record)])
                    sample_data = sample_data + "\n" + record 
                
                schema = f"### TABLE {table_name} DDL\n{schema}\n\n### SAMPLE DATA\n{sample_data}"
                
                return schema
        except Exception as e:
            print(f"Error: {e}")
            
    def execute(self, query: str)-> Any:
        try:
            with engine.connect() as conn:
                cursor_result = conn.execute(text(query))
                column_names = cursor_result.keys()
                records = cursor_result.fetchall()
                
                results = "\t".join(column_names)
                for record in records:
                    record = "\t".join([str(cell) for cell in list(record)])
                    results = results + "\n" + record
                print(results) 
                return results
            
        except Exception as e:
            print(f"Error: {e}")
                   