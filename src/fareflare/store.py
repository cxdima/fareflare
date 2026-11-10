"""Small atomic document port with local SQLite and isolated DynamoDB adapters."""

from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

import boto3
from botocore.exceptions import ClientError


class Conflict(RuntimeError):
    """A competing operation changed an expected document revision."""


@dataclass(frozen=True)
class Document:
    key: str
    partition: str
    data: dict
    due: int = 0
    revision: int = 0  # Zero means the document must not already exist.
    expires_at: int | None = None

    def update(self, data: dict, **changes) -> Document:
        return replace(self, data=data, **changes)


@dataclass(frozen=True)
class Page:
    items: list[Document]
    cursor: str | None


def _cursor(partition: str, due_before: int | None, reverse: bool, position: dict) -> str:
    return base64.urlsafe_b64encode(
        json.dumps([partition, due_before, reverse, position]).encode()
    ).decode()


def _position(
    cursor: str | None, partition: str, due_before: int | None, reverse: bool
) -> dict | None:
    if cursor is None:
        return None
    try:
        if len(cursor) > 4096:
            raise ValueError
        value = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if (
            not isinstance(value, list)
            or len(value) != 4
            or value[:3] != [partition, due_before, reverse]
            or not isinstance(value[3], dict)
        ):
            raise ValueError
        return value[3]
    except (ValueError, TypeError, UnicodeError):
        raise ValueError("Invalid pagination cursor") from None


def _page_limit(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Page limit must be 1–1000")


class Store(Protocol):
    def get(self, key: str) -> Document | None: ...
    def query(self, partition: str, due_before: int | None = None) -> list[Document]: ...
    def page(
        self,
        partition: str,
        due_before: int | None = None,
        *,
        limit: int = 100,
        cursor: str | None = None,
        reverse: bool = False,
    ) -> Page: ...
    def commit(self, documents: list[Document]) -> None: ...


def _validate_batch(documents: list[Document]) -> None:
    if not 1 <= len(documents) <= 100 or len({d.key for d in documents}) != len(documents):
        raise ValueError("Transactions require 1–100 distinct documents")
    if any(len(json.dumps(d.data).encode()) > 250_000 for d in documents):
        raise ValueError("Document exceeds the application size limit")


class SQLiteStore:
    """Durable local transactions; each operation has its own connection."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, partition_key TEXT NOT NULL, due INTEGER NOT NULL,
                revision INTEGER NOT NULL, payload TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS due_items ON documents(partition_key, due)")
            if "expires_at" not in {row[1] for row in db.execute("PRAGMA table_info(documents)")}:
                db.execute("ALTER TABLE documents ADD COLUMN expires_at INTEGER")
        os.chmod(self.path, 0o600)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _document(row) -> Document:
        return Document(row[0], row[1], json.loads(row[4]), row[2], row[3], row[5])

    def get(self, key: str) -> Document | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM documents WHERE id=?", (key,)).fetchone()
        return self._document(row) if row else None

    def query(self, partition: str, due_before: int | None = None) -> list[Document]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM documents WHERE partition_key=? AND due<=? ORDER BY due,id",
                (partition, due_before if due_before is not None else 2**63 - 1),
            ).fetchall()
        return [self._document(row) for row in rows]

    def page(
        self,
        partition: str,
        due_before: int | None = None,
        *,
        limit: int = 100,
        cursor: str | None = None,
        reverse: bool = False,
    ) -> Page:
        _page_limit(limit)
        position = _position(cursor, partition, due_before, reverse)
        parameters = [partition, due_before if due_before is not None else 2**63 - 1]
        clause = ""
        if position:
            if (
                set(position) != {"due", "id"}
                or type(position["due"]) is not int
                or not isinstance(position["id"], str)
            ):
                raise ValueError("Invalid pagination cursor")
            clause = " AND (due,id) " + ("<" if reverse else ">") + " (?,?)"
            parameters.extend([position["due"], position["id"]])
        order = "DESC" if reverse else "ASC"
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM documents WHERE partition_key=? AND due<=?"
                + clause
                + f" ORDER BY due {order},id {order} LIMIT ?",
                [*parameters, limit + 1],
            ).fetchall()
        items = [self._document(row) for row in rows[:limit]]
        next_cursor = (
            _cursor(partition, due_before, reverse, {"due": items[-1].due, "id": items[-1].key})
            if len(rows) > limit
            else None
        )
        return Page(items, next_cursor)

    def purge_expired(self, now: int, limit: int = 1000) -> int:
        _page_limit(limit)
        with self._connect() as db:
            result = db.execute(
                "DELETE FROM documents WHERE id IN (SELECT id FROM documents "
                "WHERE expires_at IS NOT NULL AND expires_at<=? LIMIT ?)",
                (now, limit),
            )
            return result.rowcount

    def commit(self, documents: list[Document]) -> None:
        _validate_batch(documents)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for doc in documents:
                row = db.execute("SELECT revision FROM documents WHERE id=?", (doc.key,)).fetchone()
                if (row[0] if row else 0) != doc.revision:
                    raise Conflict(doc.key)
                db.execute(
                    """INSERT INTO documents VALUES (?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET partition_key=excluded.partition_key,
                    due=excluded.due,revision=excluded.revision,payload=excluded.payload,expires_at=excluded.expires_at""",
                    (
                        doc.key,
                        doc.partition,
                        doc.due,
                        doc.revision + 1,
                        json.dumps(doc.data, sort_keys=True),
                        doc.expires_at,
                    ),
                )


class DynamoStore:
    """Accept explicit Fareflare tables and existing gfpt-next deployments.

    Schema: string primary key id; GSI partition-due (partition S, due N).
    GSI discovery is eventually consistent; get/commit enforce revisions.
    """

    def __init__(self, table: str, region: str = "us-east-1", client=None):
        if not re.fullmatch(r"(?:fareflare|gfpt-next)-[a-z0-9-]{3,50}", table):
            raise ValueError(
                "Table names must use a fareflare- or gfpt-next- prefix and a 3–50 character lowercase suffix"
            )
        self.table = table
        self.client = client or boto3.client("dynamodb", region_name=region)

    @staticmethod
    def _document(item: dict) -> Document:
        return Document(
            item["id"]["S"],
            item["partition"]["S"],
            json.loads(item["payload"]["S"]),
            int(item["due"]["N"]),
            int(item["revision"]["N"]),
            int(item["expires_at"]["N"]) if "expires_at" in item else None,
        )

    def get(self, key: str) -> Document | None:
        result = self.client.get_item(
            TableName=self.table, Key={"id": {"S": key}}, ConsistentRead=True
        )
        return self._document(result["Item"]) if "Item" in result else None

    def query(self, partition: str, due_before: int | None = None) -> list[Document]:
        args = {
            "TableName": self.table,
            "IndexName": "partition-due",
            "KeyConditionExpression": "#p = :p AND due <= :d",
            "ExpressionAttributeNames": {"#p": "partition"},
            "ExpressionAttributeValues": {
                ":p": {"S": partition},
                ":d": {"N": str(due_before if due_before is not None else 2**63 - 1)},
            },
        }
        documents = []
        while True:
            result = self.client.query(**args)
            documents.extend(self._document(item) for item in result.get("Items", []))
            if not result.get("LastEvaluatedKey"):
                return documents
            args["ExclusiveStartKey"] = result["LastEvaluatedKey"]

    def page(
        self,
        partition: str,
        due_before: int | None = None,
        *,
        limit: int = 100,
        cursor: str | None = None,
        reverse: bool = False,
    ) -> Page:
        _page_limit(limit)
        position = _position(cursor, partition, due_before, reverse)
        args = {
            "TableName": self.table,
            "IndexName": "partition-due",
            "Limit": limit,
            "ScanIndexForward": not reverse,
            "KeyConditionExpression": "#p = :p AND due <= :d",
            "ExpressionAttributeNames": {"#p": "partition"},
            "ExpressionAttributeValues": {
                ":p": {"S": partition},
                ":d": {"N": str(due_before if due_before is not None else 2**63 - 1)},
            },
        }
        if position:
            if (
                set(position) != {"id", "partition", "due"}
                or position.get("partition") != {"S": partition}
                or not isinstance(position.get("id", {}).get("S"), str)
                or not isinstance(position.get("due", {}).get("N"), str)
            ):
                raise ValueError("Invalid pagination cursor")
            args["ExclusiveStartKey"] = position
        result = self.client.query(**args)
        next_cursor = (
            _cursor(partition, due_before, reverse, result["LastEvaluatedKey"])
            if result.get("LastEvaluatedKey")
            else None
        )
        return Page([self._document(item) for item in result.get("Items", [])], next_cursor)

    def commit(self, documents: list[Document]) -> None:
        _validate_batch(documents)
        writes = []
        for doc in documents:
            put = {
                "TableName": self.table,
                "Item": {
                    "id": {"S": doc.key},
                    "partition": {"S": doc.partition},
                    "due": {"N": str(doc.due)},
                    "revision": {"N": str(doc.revision + 1)},
                    "payload": {"S": json.dumps(doc.data, sort_keys=True)},
                },
                "ConditionExpression": "attribute_not_exists(id)"
                if doc.revision == 0
                else "revision = :r",
            }
            if doc.expires_at is not None:
                put["Item"]["expires_at"] = {"N": str(doc.expires_at)}
            if doc.revision:
                put["ExpressionAttributeValues"] = {":r": {"N": str(doc.revision)}}
            writes.append({"Put": put})
        try:
            self.client.transact_write_items(TransactItems=writes)
        except ClientError as exc:
            reasons = exc.response.get("CancellationReasons", [])
            if exc.response["Error"]["Code"] == "TransactionCanceledException" and any(
                r.get("Code") in ("ConditionalCheckFailed", "TransactionConflict") for r in reasons
            ):
                raise Conflict("Concurrent transaction") from exc
            raise
