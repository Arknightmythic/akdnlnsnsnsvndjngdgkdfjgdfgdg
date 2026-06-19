from typing import Any, AsyncIterator, Dict, Iterator, Optional, Sequence, Tuple, cast
from sqlalchemy import text
from langchain.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    SerializerProtocol,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from langgraph.checkpoint.serde.types import ChannelProtocol
import json
import random
import threading
import binascii
import hashlib

from ingestion.starrocks_connection import engine

def _load_metadata_with_fallback(serde: "SerializerProtocol", metadata: Any, metadata_type: str) -> "CheckpointMetadata":
    if metadata is None:
        return {}

    try:
        return serde.loads_typed((metadata_type, metadata))
    except Exception:
        pass

    try:
        if isinstance(metadata, str):
            return json.loads(metadata)
        elif isinstance(metadata, bytes):
            return json.loads(metadata.decode("utf-8"))
    except Exception:
        pass

    return {}

JsonDict = Dict[str, Any]

def _ensure_bytes(data: Any) -> Any:
    if isinstance(data, str):
        try:
            return binascii.unhexlify(data)
        except Exception:
            return data.encode("utf-8", errors="surrogateescape")
    return data

def _to_hex(data: Any) -> str:
    if isinstance(data, (bytes, bytearray)):
        return binascii.hexlify(data).decode("ascii")
    return data

def _generate_pk(*args: Any) -> str:
    combined = ":".join(str(arg) for arg in args)
    return hashlib.sha256(combined.encode()).hexdigest()


class StarRocksSaver(BaseCheckpointSaver[str]):
    is_setup: bool

    def __init__(self, url: str, database: str, user: str, password: str, *, serde: Optional[SerializerProtocol] = None) -> None:
        super().__init__(serde=serde)
        self.url = url
        self.database = database
        self.user = user
        self.password = password
        self.is_setup = False
        self.lock = threading.Lock()

    def setup(self) -> None:
        with engine.connect() as connection:
            # Table for checkpoint state
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS `checkpoint` (
                    `pk` VARCHAR(128) NOT NULL,
                    `thread_id` VARCHAR(255) NOT NULL,
                    `checkpoint_ns` VARCHAR(255) NOT NULL,
                    `checkpoint_id` VARCHAR(255) NOT NULL,
                    `parent_checkpoint_id` VARCHAR(255),
                    `type` VARCHAR(50),
                    `checkpoint` STRING,
                    `metadata` STRING,
                    `metadata_type` VARCHAR(50)
                ) ENGINE=OLAP
                PRIMARY KEY (`pk`)
                DISTRIBUTED BY HASH(`pk`) BUCKETS 10
                PROPERTIES("replication_num" = "1");
            """))
            
            # Table for writes/state changes
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS `write` (
                    `pk` VARCHAR(128) NOT NULL,
                    `thread_id` VARCHAR(255) NOT NULL,
                    `checkpoint_ns` VARCHAR(255) NOT NULL,
                    `checkpoint_id` VARCHAR(255) NOT NULL,
                    `task_id` VARCHAR(255) NOT NULL,
                    `idx` INT NOT NULL,
                    `channel` VARCHAR(255) NOT NULL,
                    `type` VARCHAR(50),
                    `value` STRING,
                    `task_path` VARCHAR(1024)
                ) ENGINE=OLAP
                PRIMARY KEY (`pk`)
                DISTRIBUTED BY HASH(`pk`) BUCKETS 10
                PROPERTIES("replication_num" = "1");
            """))
            connection.commit()
        self.is_setup = True

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        with engine.connect() as connection:
            try:
                thread_id = str(config["configurable"]["thread_id"])
                query = """
                SELECT thread_id, checkpoint_id, parent_checkpoint_id, type,
                checkpoint, metadata, metadata_type
                FROM checkpoint WHERE
                thread_id = :thread_id AND checkpoint_ns = :checkpoint_ns
                """
                vars = {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}
                if checkpoint_id := get_checkpoint_id(config):
                    vars["pk"] = _generate_pk(thread_id, checkpoint_ns, checkpoint_id)
                    query += " AND pk = :pk"
                else:
                    query += " ORDER BY checkpoint_id DESC limit 1"
                try:
                    result = connection.execute(text(query), vars).mappings().fetchone()
                except Exception:
                    raise

                if result:
                    thread_id = result["thread_id"]
                    checkpoint_id = result["checkpoint_id"]
                    parent_checkpoint_id = result["parent_checkpoint_id"]
                    type_ = result["type"]
                    checkpoint = _ensure_bytes(result["checkpoint"])
                    metadata = _ensure_bytes(result["metadata"])
                    metadata_type = result.get("metadata_type", type_)
                    if not get_checkpoint_id(config):
                        config = {
                            "configurable": {
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": checkpoint_id,
                            }
                        }
                    query = """
                    SELECT task_id, channel, type, value, idx
                    FROM write
                    WHERE thread_id = :thread_id
                    AND checkpoint_ns = :checkpoint_ns
                    AND checkpoint_id = :checkpoint_id
                    ORDER BY task_id, idx
                    """
                    vars = {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id,
                    }
                    try:
                        results = connection.execute(text(query), vars).mappings()
                    except Exception:
                        pass

                    try:
                        checkpoint_data = self.serde.loads_typed((type_, checkpoint))
                        metadata_dict = cast(
                            CheckpointMetadata,
                            _load_metadata_with_fallback(
                                self.serde, metadata, metadata_type
                            ),
                        )
                        writes = [
                            (
                                r["task_id"],
                                r["channel"],
                                self.serde.loads_typed((type_, _ensure_bytes(r["value"]))),
                            )
                            for r in results
                        ]
                    except Exception:
                        raise

                    return CheckpointTuple(
                        config,
                        checkpoint_data,
                        metadata_dict,
                        (
                            {
                                "configurable": {
                                    "thread_id": thread_id,
                                    "checkpoint_ns": checkpoint_ns,
                                    "checkpoint_id": parent_checkpoint_id,
                                }
                            }
                            if parent_checkpoint_id
                            else None
                        ),
                        writes,
                    )
                else:
                    return None
            except Exception as e:
                raise e

    def list(self, config: Optional[RunnableConfig], *, filter: Optional[Dict[str, Any]] = None, before: Optional[RunnableConfig] = None, limit: Optional[int] = None) -> Iterator[CheckpointTuple]:
        thread_id = (
            str(config.get("configurable", {}).get("thread_id", "")) if config else ""
        )
        checkpoint_ns = (
            config.get("configurable", {}).get("checkpoint_ns", "") if config else ""
        )
        query = """
        SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata, metadata_type
        FROM checkpoint
        WHERE thread_id = :thread_id AND checkpoint_ns = :checkpoint_ns
        ORDER BY checkpoint_id DESC
        """
        vars = {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
        }
        if limit:
            vars["limit"] = limit
            query += " LIMIT :limit"
        with engine.connect() as connection:
            try:
                results = connection.execute(text(query), vars).mappings()
            except Exception:
                raise

            for r in results:
                try:
                    thread_id = r["thread_id"]
                    checkpoint_ns = r["checkpoint_ns"]
                    checkpoint_id = r["checkpoint_id"]
                    parent_checkpoint_id = r["parent_checkpoint_id"]
                    type_ = r["type"]
                    checkpoint = _ensure_bytes(r["checkpoint"])
                    metadata = _ensure_bytes(r["metadata"])
                    metadata_type = r.get("metadata_type", type_)
                    query = """
                    SELECT task_id, channel, type, value, idx
                    FROM write
                    WHERE thread_id = :thread_id
                    AND checkpoint_ns = :checkpoint_ns
                    AND checkpoint_id = :checkpoint_id
                    ORDER BY task_id, idx
                    """
                    vars = {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id,
                    }
                    try:
                        task_results = connection.execute(text(query), vars).mappings()
                    except Exception:
                        raise

                    try:
                        checkpoint_data = self.serde.loads_typed((type_, checkpoint))
                        metadata_dict = cast(
                            CheckpointMetadata,
                            _load_metadata_with_fallback(
                                self.serde, metadata, metadata_type
                            ),
                        )
                        writes = [
                            (
                                tr["task_id"],
                                tr["channel"],
                                self.serde.loads_typed((type_, _ensure_bytes(tr["value"])))
                                if tr["value"] not in (None, "", b"") else None,
                            )
                            for tr in task_results
                        ]
                    except Exception:
                        raise

                    yield CheckpointTuple(
                        {
                            "configurable": {
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": checkpoint_id,
                            }
                        },
                        checkpoint_data,
                        metadata_dict,
                        (
                            {
                                "configurable": {
                                    "thread_id": thread_id,
                                    "checkpoint_ns": checkpoint_ns,
                                    "checkpoint_id": parent_checkpoint_id,
                                }
                            }
                            if parent_checkpoint_id
                            else None
                        ),
                        writes,
                    )
                except Exception as e:
                    raise e

    def put(self, config: RunnableConfig, checkpoint: Checkpoint, metadata: CheckpointMetadata, new_versions: ChannelVersions) -> RunnableConfig:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"]["checkpoint_ns"]
        checkpoint_id = checkpoint["id"]
        try:
            type_, serialized_checkpoint = self.serde.dumps_typed(checkpoint)
            metadata_type, serialized_metadata = self.serde.dumps_typed(
                get_checkpoint_metadata(config, metadata)
            )
        except Exception:
            raise

        with engine.connect() as connection:
            try:
                query = text("""
                    INSERT INTO `checkpoint` 
                    (`pk`, `thread_id`, `checkpoint_ns`, `checkpoint_id`, `parent_checkpoint_id`, `type`, `checkpoint`, `metadata`, `metadata_type`)
                    VALUES 
                    (:pk, :thread_id, :checkpoint_ns, :checkpoint_id, :parent_checkpoint_id, :type, :checkpoint, :metadata, :metadata_type)
                """)
                merge_data = {
                    "pk": _generate_pk(thread_id, checkpoint_ns, checkpoint_id),
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                    "parent_checkpoint_id": config["configurable"].get("checkpoint_id"),
                    "type": type_,
                    "checkpoint": _to_hex(serialized_checkpoint),
                    "metadata": _to_hex(serialized_metadata),
                    "metadata_type": metadata_type,
                }
                connection.execute(query, merge_data)
                connection.commit()
            except Exception as e:
                if "Insert has filtered data" in str(e):
                    print(f"StarRocks Filtered Data Warning (checkpoint): {e}")
                else:
                    raise e

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(self, config: RunnableConfig, writes: Sequence[Tuple[str, Any]], task_id: str, task_path: str = "") -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"]["checkpoint_ns"]
        checkpoint_id = config["configurable"]["checkpoint_id"]
        with engine.connect() as connection:
            try:
                for idx, (channel, value) in enumerate(writes):
                    try:
                        type_, serialized_value = self.serde.dumps_typed(value)
                    except Exception:
                        raise

                    channel_idx = WRITES_IDX_MAP.get(channel, idx)
                    merge_data = {
                        "pk": _generate_pk(thread_id, checkpoint_ns, checkpoint_id, task_id, channel_idx, channel),
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id,
                        "task_id": task_id,
                        "idx": channel_idx,
                        "channel": channel,
                        "type": type_,
                        "value": _to_hex(serialized_value),
                        "task_path": task_path,
                    }
                    query = text("""
                        INSERT INTO `write` 
                        (`pk`, `thread_id`, `checkpoint_ns`, `checkpoint_id`, `task_id`, `idx`, `channel`, `type`, `value`, `task_path`)
                        VALUES 
                        (:pk, :thread_id, :checkpoint_ns, :checkpoint_id, :task_id, :idx, :channel, :type, :value, :task_path)
                    """)
                    connection.execute(query, merge_data)
                connection.commit()
            except Exception as e:
                if "Insert has filtered data" in str(e):
                    print(f"StarRocks Filtered Data Warning (writes): {e}")
                else:
                    raise e

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        with engine.connect() as connection:
            try:
                thread_id = str(config["configurable"]["thread_id"])
                query = """
                SELECT thread_id, checkpoint_id, parent_checkpoint_id, type,
                checkpoint, metadata, metadata_type
                FROM checkpoint WHERE
                thread_id = :thread_id AND checkpoint_ns = :checkpoint_ns
                """
                vars = {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}
                if checkpoint_id := get_checkpoint_id(config):
                    vars["pk"] = _generate_pk(thread_id, checkpoint_ns, checkpoint_id)
                    query += " AND pk = :pk"
                else:
                    query += " ORDER BY checkpoint_id DESC limit 1"
                try:
                    result = connection.execute(text(query), vars).mappings().fetchone()
                except Exception:
                    raise

                if result:
                    thread_id = result["thread_id"]
                    checkpoint_id = result["checkpoint_id"]
                    parent_checkpoint_id = result["parent_checkpoint_id"]
                    type_ = result["type"]
                    checkpoint = _ensure_bytes(result["checkpoint"])
                    metadata = _ensure_bytes(result["metadata"])
                    metadata_type = result.get("metadata_type", type_)
                    if not get_checkpoint_id(config):
                        config = {
                            "configurable": {
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": checkpoint_id,
                            }
                        }
                    query = """
                    SELECT task_id, channel, type, value, idx
                    FROM write
                    WHERE thread_id = :thread_id
                    AND checkpoint_ns = :checkpoint_ns
                    AND checkpoint_id = :checkpoint_id
                    ORDER BY task_id, idx
                    """
                    vars = {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id,
                    }
                    try:
                        results = connection.execute(text(query), vars).mappings()
                    except Exception:
                        raise

                    try:
                        checkpoint_data = self.serde.loads_typed((type_, checkpoint))
                        metadata_dict = cast(
                            CheckpointMetadata,
                            _load_metadata_with_fallback(
                                self.serde, metadata, metadata_type
                            ),
                        )
                        writes = [
                            (
                                r["task_id"],
                                r["channel"],
                                self.serde.loads_typed((type_, _ensure_bytes(r["value"]))),
                            )
                            for r in results
                        ]
                    except Exception:
                        raise

                    return CheckpointTuple(
                        config,
                        checkpoint_data,
                        metadata_dict,
                        (
                            {
                                "configurable": {
                                    "thread_id": thread_id,
                                    "checkpoint_ns": checkpoint_ns,
                                    "checkpoint_id": parent_checkpoint_id,
                                }
                            }
                            if parent_checkpoint_id
                            else None
                        ),
                        writes,
                    )
                else:
                    return None
            except Exception as e:
                raise e

    async def alist(self, config: Optional[RunnableConfig], *, filter: Optional[Dict[str, Any]] = None, before: Optional[RunnableConfig] = None, limit: Optional[int] = None) -> AsyncIterator[CheckpointTuple]:
        thread_id = (
            str(config.get("configurable", {}).get("thread_id", "")) if config else ""
        )
        checkpoint_ns = (
            config.get("configurable", {}).get("checkpoint_ns", "") if config else ""
        )
        query = """
        SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata, metadata_type
        FROM checkpoint
        WHERE thread_id = :thread_id AND checkpoint_ns = :checkpoint_ns
        ORDER BY checkpoint_id DESC
        """
        vars = {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
        }
        if limit:
            vars["limit"] = limit
            query += " LIMIT :limit"
        with engine.connect() as connection:
            try:
                results = connection.execute(text(query), vars).mappings()
            except Exception:
                raise

            for r in results:
                try:
                    thread_id = r["thread_id"]
                    checkpoint_ns = r["checkpoint_ns"]
                    checkpoint_id = r["checkpoint_id"]
                    parent_checkpoint_id = r["parent_checkpoint_id"]
                    type_ = r["type"]
                    checkpoint = _ensure_bytes(r["checkpoint"])
                    metadata = _ensure_bytes(r["metadata"])
                    metadata_type = r.get("metadata_type", type_)
                    query = """
                    SELECT task_id, channel, type, value, idx
                    FROM write
                    WHERE thread_id = :thread_id
                    AND checkpoint_ns = :checkpoint_ns
                    AND checkpoint_id = :checkpoint_id
                    ORDER BY task_id, idx
                    """
                    vars = {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id,
                    }
                    try:
                        task_results = connection.execute(text(query), vars).mappings()
                    except Exception:
                        raise

                    try:
                        checkpoint_data = self.serde.loads_typed((type_, checkpoint))
                        metadata_dict = cast(
                            CheckpointMetadata,
                            _load_metadata_with_fallback(
                                self.serde, metadata, metadata_type
                            ),
                        )
                        writes = [
                            (
                                tr["task_id"],
                                tr["channel"],
                                self.serde.loads_typed((type_, _ensure_bytes(tr["value"]))),
                            )
                            for tr in task_results
                        ]
                    except Exception:
                        raise

                    yield CheckpointTuple(
                        {
                            "configurable": {
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": checkpoint_id,
                            }
                        },
                        checkpoint_data,
                        metadata_dict,
                        (
                            {
                                "configurable": {
                                    "thread_id": thread_id,
                                    "checkpoint_ns": checkpoint_ns,
                                    "checkpoint_id": parent_checkpoint_id,
                                }
                            }
                            if parent_checkpoint_id
                            else None
                        ),
                        writes,
                    )
                except Exception as e:
                    raise e

    async def aput(self, config: RunnableConfig, checkpoint: Checkpoint, metadata: CheckpointMetadata, new_versions: ChannelVersions) -> RunnableConfig:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"]["checkpoint_ns"]
        checkpoint_id = checkpoint["id"]
        try:
            type_, serialized_checkpoint = self.serde.dumps_typed(checkpoint)
            metadata_type, serialized_metadata = self.serde.dumps_typed(
                get_checkpoint_metadata(config, metadata)
            )
        except Exception:
            raise

        with engine.connect() as connection:
            try:
                query = text("""
                    INSERT INTO `checkpoint` 
                    (`pk`, `thread_id`, `checkpoint_ns`, `checkpoint_id`, `parent_checkpoint_id`, `type`, `checkpoint`, `metadata`, `metadata_type`)
                    VALUES 
                    (:pk, :thread_id, :checkpoint_ns, :checkpoint_id, :parent_checkpoint_id, :type, :checkpoint, :metadata, :metadata_type)
                """)
                merge_data = {
                    "pk": _generate_pk(thread_id, checkpoint_ns, checkpoint_id),
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                    "parent_checkpoint_id": config["configurable"].get("checkpoint_id"),
                    "type": type_,
                    "checkpoint": _to_hex(serialized_checkpoint),
                    "metadata": _to_hex(serialized_metadata),
                    "metadata_type": metadata_type,
                }
                connection.execute(query, merge_data)
                connection.commit()
            except Exception as e:
                if "Insert has filtered data" in str(e):
                    print(f"StarRocks Filtered Data Warning (checkpoint): {e}")
                else:
                    raise e

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def aput_writes(self, config: RunnableConfig, writes: Sequence[Tuple[str, Any]], task_id: str, task_path: str = "") -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"]["checkpoint_ns"]
        checkpoint_id = config["configurable"]["checkpoint_id"]
        with engine.connect() as connection:
            try:
                for idx, (channel, value) in enumerate(writes):
                    try:
                        type_, serialized_value = self.serde.dumps_typed(value)
                    except Exception:
                        raise

                    channel_idx = WRITES_IDX_MAP.get(channel, idx)
                    merge_data = {
                        "pk": _generate_pk(thread_id, checkpoint_ns, checkpoint_id, task_id, channel_idx, channel),
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id,
                        "task_id": task_id,
                        "idx": channel_idx,
                        "channel": channel,
                        "type": type_,
                        "value": _to_hex(serialized_value),
                        "task_path": task_path,
                    }
                    query = text("""
                        INSERT INTO `write` 
                        (`pk`, `thread_id`, `checkpoint_ns`, `checkpoint_id`, `task_id`, `idx`, `channel`, `type`, `value`, `task_path`)
                        VALUES 
                        (:pk, :thread_id, :checkpoint_ns, :checkpoint_id, :task_id, :idx, :channel, :type, :value, :task_path)
                    """)
                    connection.execute(query, merge_data)
                connection.commit()
            except Exception as e:
                if "Insert has filtered data" in str(e):
                    print(f"StarRocks Filtered Data Warning (writes): {e}")
                else:
                    raise e

    def get_next_version(self, current: Optional[str], channel: ChannelProtocol) -> str:
        if current is None:
            current_v = 0
        elif isinstance(current, int):
            current_v = current
        else:
            current_v = int(current.split(".")[0])
        next_v = current_v + 1
        next_h = random.random()
        return f"{next_v:032}.{next_h:016}"
