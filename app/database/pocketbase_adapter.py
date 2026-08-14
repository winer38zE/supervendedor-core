"""
Adaptador estilo Supabase sobre PocketBase — minimiza cambios en el resto del código.
"""

from __future__ import annotations

from typing import Any, Optional

from app.database import pocketbase_client as pb


class PocketBaseResponse:
    def __init__(self, data: list[dict] | dict | None):
        if isinstance(data, dict):
            self.data = [data]
        elif isinstance(data, list):
            self.data = data
        else:
            self.data = []


class PocketBaseTableQuery:
    def __init__(self, collection: str):
        self.collection = collection
        self._select_fields = "*"
        self._filters: list[str] = []
        self._sort = "-created"
        self._limit = 50
        self._single = False
        self._pending_update: Optional[dict] = None
        self._pending_upsert: Optional[dict] = None
        self._upsert_conflict: list[str] = []
        self._pending_insert: Optional[dict] = None

    def select(self, fields: str = "*") -> "PocketBaseTableQuery":
        self._select_fields = fields
        return self

    def eq(self, field: str, value: Any) -> "PocketBaseTableQuery":
        self._filters.append(f"({field}={pb._quote(value)})")
        return self

    def gte(self, field: str, value: Any) -> "PocketBaseTableQuery":
        self._filters.append(f"({field}>={pb._quote(value)})")
        return self

    def lt(self, field: str, value: Any) -> "PocketBaseTableQuery":
        self._filters.append(f"({field}<{pb._quote(value)})")
        return self

    def in_(self, field: str, values: list[Any]) -> "PocketBaseTableQuery":
        if not values:
            return self
        ors = "||".join(f"({field}={pb._quote(v)})" for v in values)
        self._filters.append(f"({ors})")
        return self

    def order(self, field: str, desc: bool = False) -> "PocketBaseTableQuery":
        self._sort = f"{'-' if desc else '+'}{field}"
        return self

    def limit(self, n: int) -> "PocketBaseTableQuery":
        self._limit = n
        return self

    def single(self) -> "PocketBaseTableQuery":
        self._single = True
        self._limit = 1
        return self

    def upsert(self, row: dict, on_conflict: str = "") -> "PocketBaseTableQuery":
        self._pending_upsert = row
        self._upsert_conflict = [f.strip() for f in on_conflict.split(",") if f.strip()]
        return self

    def update(self, row: dict) -> "PocketBaseTableQuery":
        self._pending_update = row
        return self

    def insert(self, row: dict) -> "PocketBaseTableQuery":
        self._pending_insert = row
        return self

    def execute(self) -> PocketBaseResponse:
        if self._pending_insert is not None:
            rec = pb.create_record(self.collection, self._pending_insert)
            return PocketBaseResponse(rec)

        if self._pending_upsert is not None:
            keys = self._upsert_conflict or ["id"]
            rec = pb.upsert_by_filter(self.collection, self._pending_upsert, keys)
            return PocketBaseResponse(rec)

        if self._pending_update is not None:
            items = self._fetch()
            updated = []
            for item in items:
                rec = pb.update_record(self.collection, item["id"], self._pending_update)
                if rec:
                    updated.append(rec)
            return PocketBaseResponse(updated)

        items = self._fetch()
        if self._single:
            return PocketBaseResponse(items[0] if items else None)
        return PocketBaseResponse(items)

    def _fetch(self) -> list[dict]:
        filt = "&&".join(self._filters) if self._filters else ""
        return pb.list_records(
            self.collection,
            filter_expr=filt,
            sort=self._sort,
            per_page=self._limit,
        )


class PocketBaseClient:
    """API mínima compatible: client.table('x').select().eq().execute()"""

    def table(self, name: str) -> PocketBaseTableQuery:
        return PocketBaseTableQuery(name)


def get_pocketbase_client() -> PocketBaseClient:
    return PocketBaseClient()
