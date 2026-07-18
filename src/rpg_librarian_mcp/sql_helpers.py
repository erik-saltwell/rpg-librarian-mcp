from __future__ import annotations

import json
import sqlite3
from typing import Any

from .schema import TableSchema


def row_to_dict(row: sqlite3.Row, table: TableSchema) -> dict[str, Any]:
    data = dict(row)
    for column in table.bool_columns:
        if data.get(column) is not None:
            data[column] = bool(data[column])
    for column in table.json_columns:
        if data.get(column) is not None:
            data[column] = json.loads(data[column])
    return data


def dict_to_values(data: dict[str, Any], table: TableSchema) -> list[Any]:
    values: list[Any] = []
    for column in table.columns:
        value = data.get(column)
        if column in table.bool_columns and value is not None:
            value = int(value)
        if column in table.json_columns:
            value = json.dumps(value if value is not None else [])
        values.append(value)
    return values


def upsert(conn: sqlite3.Connection, table_name: str, table: TableSchema, data: dict[str, Any]) -> None:
    column_list = ", ".join(table.columns)
    placeholders = ", ".join("?" for _ in table.columns)
    conn.execute(
        f"INSERT OR REPLACE INTO {table_name} ({column_list}) VALUES ({placeholders})",  # noqa: S608 (table_name/columns are from our fixed internal schema, not user input)
        dict_to_values(data, table),
    )
