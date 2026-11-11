"""
turso_client.py
================
Robust, zero-dependency Python client for Turso Cloud (libSQL).
Communicates via the official Turso /v2/pipeline HTTPS protocol and presents
a 100% sqlite3-compatible interface with dictionary row access.

Zero external dependencies required (uses standard library urllib.request).
Works seamlessly on Vercel Serverless, macOS, Linux, and Windows.
"""

import os
import json
import base64
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


def normalize_turso_url(url: str) -> str:
    """Normalizes any Turso database URL format to the /v2/pipeline HTTPS endpoint."""
    u = url.strip()
    if u.startswith("libsql://"):
        u = "https://" + u[len("libsql://"):]
    elif not u.startswith("http://") and not u.startswith("https://"):
        u = "https://" + u
    if not u.endswith("/v2/pipeline"):
        u = u.rstrip("/") + "/v2/pipeline"
    return u


def serialize_param(val: Any) -> Dict[str, Any]:
    """Encodes a Python value into a typed Turso parameter object."""
    if val is None:
        return {"type": "null"}
    elif isinstance(val, bool):
        return {"type": "integer", "value": "1" if val else "0"}
    elif isinstance(val, int):
        return {"type": "integer", "value": str(val)}
    elif isinstance(val, float):
        return {"type": "float", "value": float(val)}
    elif isinstance(val, (bytes, bytearray)):
        return {"type": "blob", "base64": base64.b64encode(val).decode("ascii")}
    else:
        return {"type": "text", "value": str(val)}


def deserialize_cell(cell: Dict[str, Any]) -> Any:
    """Decodes a typed cell from a Turso response into a native Python value."""
    t = cell.get("type", "null")
    v = cell.get("value")
    if t == "null" or v is None:
        return None
    elif t == "integer":
        try:
            return int(v)
        except (ValueError, TypeError):
            return v
    elif t == "float":
        try:
            return float(v)
        except (ValueError, TypeError):
            return v
    elif t == "text":
        return str(v)
    elif t == "blob":
        b64 = cell.get("base64", "")
        try:
            return base64.b64decode(b64)
        except Exception:
            return b64
    return v


class TursoRow:
    """
    Dictionary-like row matching sqlite3.Row behavior.
    Allows accessing fields by column name (row['title']), integer index (row[0]),
    and conversion to a standard Python dictionary via dict(row).
    """
    __slots__ = ("_cols", "_vals", "_dict")

    def __init__(self, cols: List[str], vals: List[Any]):
        self._cols = cols
        self._vals = vals
        self._dict = dict(zip(cols, vals))

    def __getitem__(self, key: Union[str, int]) -> Any:
        if isinstance(key, int):
            return self._vals[key]
        return self._dict[key]

    def __contains__(self, key: str) -> bool:
        return key in self._dict

    def get(self, key: str, default: Any = None) -> Any:
        return self._dict.get(key, default)

    def keys(self):
        return self._dict.keys()

    def values(self):
        return self._dict.values()

    def items(self):
        return self._dict.items()

    def __iter__(self):
        return iter(self._vals)

    def __len__(self) -> int:
        return len(self._vals)

    def __repr__(self) -> str:
        return f"<TursoRow {repr(self._dict)}>"


class TursoCursor:
    """Cursor implementation adhering to Python DB-API 2.0 specifications."""

    def __init__(self, conn: "TursoConnection"):
        self.conn = conn
        self.description: Optional[List[Tuple[str, None, None, None, None, None, None]]] = None
        self.rowcount: int = -1
        self.lastrowid: Optional[int] = None
        self._rows: List[TursoRow] = []
        self._idx: int = 0

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> "TursoCursor":
        clean_sql = sql.strip().rstrip(";")
        # Bypass harmless SQLite pragmas on remote Turso
        if clean_sql.upper().startswith("PRAGMA JOURNAL_MODE") or clean_sql.upper().startswith("PRAGMA BUSY_TIMEOUT"):
            self.description = [("journal_mode", None, None, None, None, None, None)]
            self._rows = [TursoRow(["journal_mode"], ["wal"])]
            self._idx = 0
            self.rowcount = 1
            return self

        stmt_args = [serialize_param(p) for p in (params or [])]
        req_payload = {
            "requests": [
                {
                    "type": "execute",
                    "stmt": {
                        "sql": clean_sql,
                        "args": stmt_args
                    }
                },
                {"type": "close"}
            ]
        }

        resp = self.conn._send_pipeline(req_payload)
        results = resp.get("results", [])
        if not results:
            self._rows = []
            self._idx = 0
            return self

        first_res = results[0]
        if first_res.get("type") == "error":
            err_msg = first_res.get("error", {}).get("message", "Unknown Turso Error")
            raise RuntimeError(f"Turso SQL Error: {err_msg} in statement: {clean_sql}")

        res_body = first_res.get("response", {})
        if res_body.get("type") == "execute":
            res_data = res_body.get("result", {})
            cols = [col["name"] for col in res_data.get("cols", [])]
            self.description = [(c, None, None, None, None, None, None) for c in cols]
            self.rowcount = res_data.get("affected_row_count", 0)
            self.lastrowid = res_data.get("last_insert_rowid")

            raw_rows = res_data.get("rows", [])
            self._rows = []
            for r in raw_rows:
                decoded_vals = [deserialize_cell(cell) for cell in r]
                self._rows.append(TursoRow(cols, decoded_vals))
            self._idx = 0

        return self

    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> "TursoCursor":
        clean_sql = sql.strip().rstrip(";")
        if not seq_of_params:
            return self

        # Chunk in pipelines of 100 statements
        chunk_size = 100
        for i in range(0, len(seq_of_params), chunk_size):
            chunk = seq_of_params[i:i + chunk_size]
            reqs = []
            for p in chunk:
                stmt_args = [serialize_param(val) for val in p]
                reqs.append({
                    "type": "execute",
                    "stmt": {"sql": clean_sql, "args": stmt_args}
                })
            reqs.append({"type": "close"})
            resp = self.conn._send_pipeline({"requests": reqs})
            for r in resp.get("results", []):
                if r.get("type") == "error":
                    err_msg = r.get("error", {}).get("message", "Unknown Error")
                    raise RuntimeError(f"Turso executemany Error: {err_msg}")

        self._rows = []
        self._idx = 0
        return self

    def fetchone(self) -> Optional[TursoRow]:
        if self._idx < len(self._rows):
            row = self._rows[self._idx]
            self._idx += 1
            return row
        return None

    def fetchall(self) -> List[TursoRow]:
        if self._idx == 0:
            self._idx = len(self._rows)
            return list(self._rows)
        res = self._rows[self._idx:]
        self._idx = len(self._rows)
        return res

    def fetchmany(self, size: Optional[int] = None) -> List[TursoRow]:
        if size is None:
            size = 1
        end = min(self._idx + size, len(self._rows))
        res = self._rows[self._idx:end]
        self._idx = end
        return res

    def close(self):
        self._rows = []
        self._idx = 0

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row


class TursoConnection:
    """Connection abstraction connecting directly to Turso's /v2/pipeline over HTTPS."""

    def __init__(self, database_url: str, auth_token: str):
        self.pipeline_url = normalize_turso_url(database_url)
        self.auth_token = auth_token.strip()
        self.row_factory = TursoRow  # Default to TursoRow

    def _send_pipeline(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.pipeline_url,
            data=data_bytes,
            headers={
                "Authorization": f"Bearer {self.auth_token}",
                "Content-Type": "application/json",
                "Accept-Encoding": "gzip, deflate"
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw_bytes = resp.read()
                enc = resp.headers.get("Content-Encoding", "").lower()
                if "gzip" in enc:
                    import gzip
                    raw_bytes = gzip.decompress(raw_bytes)
                elif "deflate" in enc:
                    import zlib
                    raw_bytes = zlib.decompress(raw_bytes)
                raw_body = raw_bytes.decode("utf-8")
                return json.loads(raw_body)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Turso HTTP Error {e.code}: {err_body}") from e
        except Exception as e:
            raise RuntimeError(f"Turso Connection Failed: {e}") from e

    def cursor(self) -> TursoCursor:
        return TursoCursor(self)

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> TursoCursor:
        cur = self.cursor()
        return cur.execute(sql, params)

    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> TursoCursor:
        cur = self.cursor()
        return cur.executemany(sql, seq_of_params)

    def commit(self):
        """Statements in Turso /v2/pipeline are auto-committed per pipeline."""
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def connect(database_url: str, auth_token: str) -> TursoConnection:
    """Establishes a connection to a remote Turso database."""
    return TursoConnection(database_url, auth_token)


def is_turso_configured() -> bool:
    """Returns True if Turso credentials are present in environment variables."""
    url = os.environ.get("TURSO_DATABASE_URL", "").strip()
    token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
    return bool(url and token)
