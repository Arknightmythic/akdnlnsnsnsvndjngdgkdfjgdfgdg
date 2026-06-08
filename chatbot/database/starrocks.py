import json
import logging
import random
import threading
import binascii
import hashlib
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Dict, Iterator, Optional, Sequence, Tuple, cast
from urllib.parse import urlparse
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _load_metadata_with_fallback(
    serde: "SerializerProtocol",
    metadata: Any,
    metadata_type: str,
) -> "CheckpointMetadata":
    """Load metadata with fallback for legacy format.

    Args:
        serde: The serializer to use.
        metadata: The metadata to deserialize.
        metadata_type: The type of the metadata serialization.

    Returns:
        CheckpointMetadata: The deserialized metadata.
    """
    if metadata is None:
        return {}

    # Try new format first (msgpack bytes)
    try:
        return serde.loads_typed((metadata_type, metadata))
    except Exception:
        pass

    # Fallback for legacy format (JSON string)
    try:
        if isinstance(metadata, str):
            return json.loads(metadata)
        elif isinstance(metadata, bytes):
            return json.loads(metadata.decode("utf-8"))
    except Exception:
        pass

    # Return empty dict if all attempts fail
    logger.warning("Failed to deserialize metadata, returning empty dict")
    return {}

# Type alias for clarity
JsonDict = Dict[str, Any]


def _ensure_bytes(data: Any) -> Any:
    """Ensure that data is bytes. Handles hex-encoded strings from the database."""
    if isinstance(data, str):
        try:
            return binascii.unhexlify(data)
        except Exception:
            return data.encode("utf-8", errors="surrogateescape")
    return data


def _to_hex(data: Any) -> str:
    """Convert bytes to hex string for safe storage."""
    if isinstance(data, (bytes, bytearray)):
        return binascii.hexlify(data).decode("ascii")
    return data


def _generate_pk(*args: Any) -> str:
    """Generate a stable hash for composite primary keys to stay within StarRocks PK size limits."""
    combined = ":".join(str(arg) for arg in args)
    return hashlib.sha256(combined.encode()).hexdigest()


class CheckpointError(Exception):
    """Base exception for checkpoint operations."""

    def __init__(self, message: str, original_exception: Optional[Exception] = None):
        super().__init__(message)
        self.original_exception = original_exception


class CheckpointReadError(CheckpointError):
    """Raised when there's an error reading checkpoint data."""

    pass


class CheckpointSaveError(CheckpointError):
    """Raised when there's an error saving checkpoint data."""

    pass


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

from ingestion.starrocks_connection import engine


class StarRocksSaver(BaseCheckpointSaver[str]):
    is_setup: bool

    def __init__(
        self,
        url: str,
        database: str,
        user: str,
        password: str,
        *,
        serde: Optional[SerializerProtocol] = None,
    ) -> None:
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
        """Get a checkpoint tuple from the database.

        Args:
            config: The configuration containing thread and checkpoint information.

        Returns:
            Optional[CheckpointTuple]: The checkpoint tuple if found, None otherwise.

        Raises:
            CheckpointReadError: If there's an error reading from the database.
        """
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
                except Exception as e:
                    logger.error(
                        "Failed to query checkpoint data",
                        extra={
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "error": str(e),
                        },
                    )
                    raise CheckpointReadError(
                        f"Unable to retrieve checkpoint data: {str(e)}"
                    ) from e

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

                    # find any pending writes
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
                    except Exception as e:
                        logger.error(
                            "Failed to query write data",
                            extra={
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": checkpoint_id,
                                "error": str(e),
                            },
                        )
                        raise CheckpointReadError(
                            f"Unable to retrieve write data: {str(e)}"
                        ) from e

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
                    except Exception as e:
                        logger.error(
                            "Failed to deserialize checkpoint or write data",
                            extra={
                                "thread_id": thread_id,
                                "checkpoint_id": checkpoint_id,
                                "error": str(e),
                            },
                        )
                        raise CheckpointReadError(
                            f"Unable to deserialize checkpoint data: {str(e)}"
                        ) from e

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
                    logger.debug(
                        "No checkpoint found",
                        extra={
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                        },
                    )
                    return None
            except Exception as e:
                if not isinstance(e, CheckpointReadError):
                    logger.error(
                        "Unexpected error retrieving checkpoint",
                        extra={
                            "error": str(e),
                            "error_type": type(e).__name__,
                        },
                    )
                    raise CheckpointReadError(
                        f"Unexpected error retrieving checkpoint: {str(e)}"
                    ) from e
                raise

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """List checkpoints from the database.

        Args:
            config: Optional configuration containing thread and checkpoint information.
            filter: Optional filter criteria.
            before: Optional configuration to list checkpoints before.
            limit: Optional maximum number of checkpoints to return.

        Returns:
            Iterator[CheckpointTuple]: Iterator of checkpoint tuples.

        Raises:
            CheckpointReadError: If there's an error reading from the database.
        """
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
            except Exception as e:
                logger.error(
                    "Failed to query checkpoints",
                    extra={
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "error": str(e),
                    },
                )
                raise CheckpointReadError(
                    f"Unable to retrieve checkpoints: {str(e)}"
                ) from e

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
                    except Exception as e:
                        logger.error(
                            "Failed to query write data",
                            extra={
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": checkpoint_id,
                                "error": str(e),
                            },
                        )
                        raise CheckpointReadError(
                            f"Unable to retrieve write data: {str(e)}"
                        ) from e

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
                    except Exception as e:
                        logger.error(
                            "Failed to deserialize checkpoint or write data",
                            extra={
                                "thread_id": thread_id,
                                "checkpoint_id": checkpoint_id,
                                "error": str(e),
                            },
                        )
                        raise CheckpointReadError(
                            f"Unable to deserialize checkpoint data: {str(e)}"
                        ) from e

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
                    if not isinstance(e, CheckpointReadError):
                        logger.error(
                            "Unexpected error processing checkpoint",
                            extra={
                                "thread_id": thread_id,
                                "checkpoint_id": checkpoint_id,
                                "error": str(e),
                                "error_type": type(e).__name__,
                            },
                        )
                        raise CheckpointReadError(
                            f"Unexpected error processing checkpoint: {str(e)}"
                        ) from e
                    raise

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Save a checkpoint to the database.

        Args:
            config: The configuration containing thread and checkpoint information.
            checkpoint: The checkpoint data to save.
            metadata: Metadata associated with the checkpoint.
            new_versions: Version information for channels.

        Returns:
            RunnableConfig: Updated configuration.

        Raises:
            CheckpointSaveError: If there's an error saving to the database.
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"]["checkpoint_ns"]
        checkpoint_id = checkpoint["id"]
        
        try:
            type_, serialized_checkpoint = self.serde.dumps_typed(checkpoint)
            metadata_type, serialized_metadata = self.serde.dumps_typed(
                get_checkpoint_metadata(config, metadata)
            )
        except Exception as e:
            logger.error(
                "Failed to serialize checkpoint data",
                extra={
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "error": str(e),
                },
            )
            raise CheckpointSaveError(
                f"Unable to serialize checkpoint data: {str(e)}"
            ) from e

        with engine.connect() as connection:
            try:
                # StarRocks Primary Key model performs upsert on INSERT
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
                logger.error(
                    "Failed to save checkpoint",
                    extra={
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint["id"],
                        "error": str(e),
                    },
                )
                raise CheckpointSaveError(
                    f"Unable to save checkpoint data: {str(e)}"
                ) from e

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Save writes to the database.

        Args:
            config: The configuration containing thread and checkpoint information.
            writes: Sequence of writes to save.
            task_id: ID of the task.
            task_path: Optional path of the task.

        Raises:
            CheckpointSaveError: If there's an error saving to the database.
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"]["checkpoint_ns"]
        checkpoint_id = config["configurable"]["checkpoint_id"]

        with engine.connect() as connection:
            try:
                for idx, (channel, value) in enumerate(writes):
                    try:
                        type_, serialized_value = self.serde.dumps_typed(value)
                    except Exception as e:
                        logger.error(
                            "Failed to serialize write data",
                            extra={
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": checkpoint_id,
                                "task_id": task_id,
                                "channel": channel,
                                "error": str(e),
                            },
                        )
                        raise CheckpointSaveError(
                            f"Unable to serialize write data: {str(e)}"
                        ) from e

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
                logger.error(
                    "Failed to save write data",
                    extra={
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id,
                        "task_id": task_id,
                        "channel": channel,
                        "error": str(e),
                    },
                )
                raise CheckpointSaveError(
                    f"Unable to save write data: {str(e)}"
                ) from e

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Get a checkpoint tuple from the database asynchronously.

        Args:
            config: The configuration containing thread and checkpoint information.

        Returns:
            Optional[CheckpointTuple]: The checkpoint tuple if found, None otherwise.

        Raises:
            CheckpointReadError: If there's an error reading from the database.
        """
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
                except Exception as e:
                    logger.error(
                        "Failed to query checkpoint data",
                        extra={
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "error": str(e),
                        },
                    )
                    raise CheckpointReadError(
                        f"Unable to retrieve checkpoint data: {str(e)}"
                    ) from e

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

                    # find any pending writes
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
                    except Exception as e:
                        logger.error(
                            "Failed to query write data",
                            extra={
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": checkpoint_id,
                                "error": str(e),
                            },
                        )
                        raise CheckpointReadError(
                            f"Unable to retrieve write data: {str(e)}"
                        ) from e

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
                    except Exception as e:
                        logger.error(
                            "Failed to deserialize checkpoint or write data",
                            extra={
                                "thread_id": thread_id,
                                "checkpoint_id": checkpoint_id,
                                "error": str(e),
                            },
                        )
                        raise CheckpointReadError(
                            f"Unable to deserialize checkpoint data: {str(e)}"
                        ) from e

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
                    logger.debug(
                        "No checkpoint found",
                        extra={
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                        },
                    )
                    return None
            except Exception as e:
                if not isinstance(e, CheckpointReadError):
                    logger.error(
                        "Unexpected error retrieving checkpoint",
                        extra={
                            "error": str(e),
                            "error_type": type(e).__name__,
                        },
                    )
                    raise CheckpointReadError(
                        f"Unexpected error retrieving checkpoint: {str(e)}"
                    ) from e
                raise

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """List checkpoints from the database asynchronously.

        Args:
            config: Optional configuration containing thread and checkpoint information.
            filter: Optional filter criteria.
            before: Optional configuration to list checkpoints before.
            limit: Optional maximum number of checkpoints to return.

        Returns:
            AsyncIterator[CheckpointTuple]: Iterator of checkpoint tuples.

        Raises:
            CheckpointReadError: If there's an error reading from the database.
        """
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
            except Exception as e:
                logger.error(
                    "Failed to query checkpoints",
                    extra={
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "error": str(e),
                    },
                )
                raise CheckpointReadError(
                    f"Unable to retrieve checkpoints: {str(e)}"
                ) from e

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
                    except Exception as e:
                        logger.error(
                            "Failed to query write data",
                            extra={
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": checkpoint_id,
                                "error": str(e),
                            },
                        )
                        raise CheckpointReadError(
                            f"Unable to retrieve write data: {str(e)}"
                        ) from e

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
                    except Exception as e:
                        logger.error(
                            "Failed to deserialize checkpoint or write data",
                            extra={
                                "thread_id": thread_id,
                                "checkpoint_id": checkpoint_id,
                                "error": str(e),
                            },
                        )
                        raise CheckpointReadError(
                            f"Unable to deserialize checkpoint data: {str(e)}"
                        ) from e

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
                    if not isinstance(e, CheckpointReadError):
                        logger.error(
                            "Unexpected error processing checkpoint",
                            extra={
                                "thread_id": thread_id,
                                "checkpoint_id": checkpoint_id,
                                "error": str(e),
                                "error_type": type(e).__name__,
                            },
                        )
                        raise CheckpointReadError(
                            f"Unexpected error processing checkpoint: {str(e)}"
                        ) from e
                    raise

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Save a checkpoint to the database asynchronously.

        Args:
            config: The configuration containing thread and checkpoint information.
            checkpoint: The checkpoint data to save.
            metadata: Metadata associated with the checkpoint.
            new_versions: Version information for channels.

        Returns:
            RunnableConfig: Updated configuration.

        Raises:
            CheckpointSaveError: If there's an error saving to the database.
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"]["checkpoint_ns"]
        checkpoint_id = checkpoint["id"]
        
        try:
            type_, serialized_checkpoint = self.serde.dumps_typed(checkpoint)
            metadata_type, serialized_metadata = self.serde.dumps_typed(
                get_checkpoint_metadata(config, metadata)
            )
        except Exception as e:
            logger.error(
                "Failed to serialize checkpoint data",
                extra={
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "error": str(e),
                },
            )
            raise CheckpointSaveError(
                f"Unable to serialize checkpoint data: {str(e)}"
            ) from e

        with engine.connect() as connection:
            try:
                # StarRocks Primary Key model performs upsert on INSERT
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
                logger.error(
                    "Failed to save checkpoint",
                    extra={
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint["id"],
                        "error": str(e),
                    },
                )
                raise CheckpointSaveError(
                    f"Unable to save checkpoint data: {str(e)}"
                ) from e

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Save writes to the database asynchronously.

        Args:
            config: The configuration containing thread and checkpoint information.
            writes: Sequence of writes to save.
            task_id: ID of the task.
            task_path: Optional path of the task.

        Raises:
            CheckpointSaveError: If there's an error saving to the database.
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"]["checkpoint_ns"]
        checkpoint_id = config["configurable"]["checkpoint_id"]

        with engine.connect() as connection:
            try:
                for idx, (channel, value) in enumerate(writes):
                    try:
                        type_, serialized_value = self.serde.dumps_typed(value)
                    except Exception as e:
                        logger.error(
                            "Failed to serialize write data",
                            extra={
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": checkpoint_id,
                                "task_id": task_id,
                                "channel": channel,
                                "error": str(e),
                            },
                        )
                        raise CheckpointSaveError(
                            f"Unable to serialize write data: {str(e)}"
                        ) from e

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
                logger.error(
                    "Failed to save write data",
                    extra={
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id,
                        "task_id": task_id,
                        "channel": channel,
                        "error": str(e),
                    },
                )
                raise CheckpointSaveError(
                    f"Unable to save write data: {str(e)}"
                ) from e

    def get_next_version(self, current: Optional[str], channel: ChannelProtocol) -> str:
        """Generate the next version ID for a channel.

        This method creates a new version identifier for a channel based on its current version.

        Args:
            current (Optional[str]): The current version identifier of the channel.
            channel (BaseChannel): The channel being versioned.

        Returns:
            str: The next version identifier, which is guaranteed to be monotonically increasing.
        """
        if current is None:
            current_v = 0
        elif isinstance(current, int):
            current_v = current
        else:
            current_v = int(current.split(".")[0])
        next_v = current_v + 1
        next_h = random.random()
        return f"{next_v:032}.{next_h:016}"