from sqlalchemy import text
from typing import Any
from dotenv import load_dotenv
import uuid
import re

from ingestion.starrocks_connection import engine

load_dotenv()

EXLUDED_TABLES = [
    "access_event",
    "audit_event",
    "checkpoint",
    "conversation",
    "matching_queries",
    "message",
    "retention_action",
    "retention_policy",
    "write",
]

class MySQLDatabase:
    def get_table_names(self)-> list[str]:
        try:
            with engine.connect() as conn:
                cursor_result  = conn.execute(text("SHOW TABLES;"))
                table_names = [result[0] for result in cursor_result.fetchall()]
                allowed_tables = [table for table in table_names if table not in EXLUDED_TABLES]
                return allowed_tables
        except Exception as e:
            print(f"Error: {e}")
            
    def get_table_schema(self, table_name: str)-> str:
        if table_name in EXLUDED_TABLES:
            return f"Not allowed to read table {table_name}"
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
        if query in EXLUDED_TABLES:
            return f"Not allowed to execute with table {re.findall(r'FROM\s+`?(\w+)`?', query, re.IGNORECASE)[0]}"
        try:
            with engine.connect() as conn:
                cursor_result = conn.execute(text(query))
                column_names = cursor_result.keys()
                records = cursor_result.fetchall()
                
                results = "\t".join(column_names)
                for record in records:
                    record = "\t".join([str(cell) for cell in list(record)])
                    results = results + "\n" + record
                return results
            
        except Exception as e:
            print(f"Error: {e}")
                   
    def _ensure_tables(self) -> None:
        with engine.connect() as conn:
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS `conversation` (
                    `id` STRING NOT NULL,
                    `user_id` STRING NOT NULL,
                    `title` STRING NOT NULL,
                    `created_at` DATETIME NOT NULL,
                    `updated_at` DATETIME NOT NULL
                ) ENGINE=OLAP
                PRIMARY KEY(`id`)
                PROPERTIES ("replication_num" = "1")
                """
            ))
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS `message` (
                    `id` STRING NOT NULL,
                    `conversation_id` STRING NOT NULL,
                    `role` STRING NOT NULL,
                    `content` STRING NOT NULL,
                    `created_at` DATETIME NOT NULL
                ) ENGINE=OLAP
                PRIMARY KEY(`id`)
                PROPERTIES ("replication_num" = "1")
                """
            ))
            conn.commit()

    def insert_conversation(self, user_id: str, conversation_id: str, title: str) -> None:
        try:
            self._ensure_tables()
            with engine.connect() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO `conversation` (id, user_id, title, created_at, updated_at)
                        VALUES (:id, :user_id, :title, NOW(), NOW())
                        """
                    ),
                    {"id": conversation_id, "user_id": user_id, "title": title},
                )
                conn.commit()
        except Exception as e:
            print(f"Error inserting conversation: {e}")


    def insert_message(self, conversation_id: str, role: str, content: str) -> None:
        try:
            self._ensure_tables()
            with engine.connect() as conn:
                msg_id = str(uuid.uuid4())
                conn.execute(
                    text(
                        """
                        INSERT INTO `message` (id, conversation_id, role, content, created_at)
                        VALUES (:id, :cid, :role, :content, NOW())
                        """
                    ),
                    {"id": msg_id, "cid": conversation_id, "role": role, "content": content},
                )
                conn.commit()
        except Exception as e:
            print(f"Error inserting message: {e}")

    def conversation_exists(self, user_id: str, conversation_id: str) -> bool:
        try:
            self._ensure_tables()
            with engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                        SELECT 1 FROM conversation
                        WHERE id = :cid AND user_id = :uid LIMIT 1
                        """
                    ),
                    {"cid": conversation_id, "uid": user_id},
                ).fetchone()
                return result is not None
        except Exception as e:
            print(f"Error checking conversation existence: {e}")
            return False

    def get_messages(self, conversation_id: str) -> list[dict] | None:
        try:
            self._ensure_tables()
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT * FROM `message`
                        WHERE `conversation_id` = :cid
                        ORDER BY `created_at` ASC
                        """
                    ),
                    {"cid": conversation_id},
                ).fetchall()
                if not rows:
                    return None
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            print(f"Error fetching messages: {e}")
            return None

    def get_conversations(self, user_id: str) -> list[dict]:
        try:
            self._ensure_tables()
            with engine.connect() as conn:
                query = "SELECT * FROM `conversation` WHERE `user_id` = :uid"
                params = {"uid": user_id}
                rows = conn.execute(text(query), params).fetchall()
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            print(f"Error fetching conversations: {e}")
            return []

    def update_conversation_timestamp(self, conversation_id: str) -> None:
        try:
            self._ensure_tables()
            with engine.connect() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE `conversation`
                        SET `updated_at` = NOW()
                        WHERE `id` = :cid
                        """
                    ),
                    {"cid": conversation_id},
                )
                conn.commit()
        except Exception as e:
            print(f"Error updating conversation timestamp: {e}")

