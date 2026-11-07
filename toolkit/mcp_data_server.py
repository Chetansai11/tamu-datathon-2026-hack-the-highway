"""Minimal MCP server exposing a folder of CSVs to an AI assistant through read-only SQL.

    python toolkit/mcp_data_server.py data/demo

Register it with a client, for example:
    claude mcp add datathon -- .venv/Scripts/python.exe toolkit/mcp_data_server.py data/demo

Skeleton only. A strong MCP entry replaces these with tools built around one workflow,
with descriptions written for the model that has to choose between them.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import duckdb
from mcp.server.mcpserver import MCPServer  # called FastMCP before SDK 2.x

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "data/demo")
mcp = MCPServer("datathon-data")
con = duckdb.connect(":memory:")
TABLES: dict[str, Path] = {}
for f in sorted(DATA.glob("*.csv")):
    name = re.sub(r"\W+", "_", f.stem).lower()
    path = str(f).replace("'", "''")
    con.execute(f"""CREATE TABLE "{name}" AS SELECT * FROM read_csv_auto('{path}')""")
    TABLES[name] = f
# Queries run after this can't reach other files on disk.
con.execute("SET enable_external_access = false")
con.execute("SET lock_configuration = true")


@mcp.tool()
def list_tables() -> list[str]:
    """List the tables available to query."""
    return sorted(TABLES)


@mcp.tool()
def describe_table(table: str) -> list[dict]:
    """Get a table's column names and types. Call this before writing SQL."""
    if table not in TABLES:
        raise ValueError(f"Unknown table {table!r}. Available: {sorted(TABLES)}")
    rows = con.execute(f'DESCRIBE "{table}"').fetchall()
    return [{"column": r[0], "type": r[1]} for r in rows]


@mcp.tool()
def run_sql(query: str, limit: int = 100) -> list[dict]:
    """Run one read-only DuckDB SELECT and return up to `limit` rows as JSON objects."""
    q = query.strip().rstrip(";")
    if ";" in q or not re.match(r"(?is)^\s*(select|with)\b", q):
        raise ValueError("Only a single SELECT or WITH statement is allowed.")
    cur = con.execute(q)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchmany(min(limit, 1000))]


if __name__ == "__main__":
    mcp.run()
