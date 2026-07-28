# DATABASE SCHEMA & QUERY SAFETY SKILL

## Purpose
This skill provides authoritative domain context for database tables and enforces strict performance guardrails for SQL query generation.

## 1. Core Tables Overview

### `uploaded_files` (Upload Batch Tracker)
- **Purpose:** Stores metadata for each uploaded file batch (one row per file).
- **Safety:** Small table. Safe to query frequently.
- **Join Requirement:** Always join `ref_grades`, `ref_sync_statuses`, and `ref_process` for readable labels.

### `master` (National Population Master Registry)
- **Purpose:** Source-of-truth identity registry containing full national population data (~1 billion rows).
- **CRITICAL SAFETY RULE:** NEVER execute a query against `master` without a selective `WHERE` clause (e.g., `WHERE nik = '...'` or `WHERE id = '...'`) OR a strict `LIMIT` clause (e.g., `LIMIT 5`).
- Full table scans degrade system performance severely.
- Prefer joining via `nik_master` from `institution` table.

### `manual_matches` (Mismatch Review Queue)
- **Purpose:** Holds records requiring manual review and details WHY automatic matching failed.
- **Action:** Call `get_table_detail` on `manual_matches` before writing queries to inspect schema.

### `institution` (Incoming Data & Match Results)
- **Purpose:** Synchronized incoming records paired with potential matches from `master` (millions of rows).
- **Safety:** Always filter by `file_id` or `id_incoming`. Avoid scanning full table.
- **Human Readable Labels:** Join `institution i JOIN ref_match_results r ON i.match_result = r.id`.

### Reference Lookup Tables
Static lookup tables mapping numeric codes to human labels. Always JOIN these:
- `ref_grades`: Grade codes to quality labels ('A' through 'E').
- `ref_match_results`: `AUTO_MATCH`, `AUTO_UNMATCH`, `MANUAL_REVIEW`, `MANUAL_MATCH`, `MANUAL_UNMATCH`.
- `ref_process`: `UPLOADED`, `GRADED`.
- `ref_sync_statuses`: `In Progress`, `Awaiting Action`, `Completed`.

## 2. Schema Discovery Protocol for Other Tables
If a query involves tables outside the 5 main tables listed above:
1. Call `get_table_names` first to identify available tables.
2. Call `get_table_detail` to retrieve DDL schema and sample rows before writing SQL. Do not guess column names.

## 3. Mandatory LIMIT Guardrail (CRITICAL)
- **STRICT REQUIREMENT:** Every `SELECT` query MUST include an explicit `LIMIT` clause (e.g., `LIMIT 20` or `LIMIT 50`), unless it is performing an explicit aggregate function (`COUNT(*)`, `SUM()`, `AVG()`, etc.).
- **NEVER** execute unbounded queries like `SELECT * FROM manual_matches WHERE ...` without a `LIMIT`. Unbounded queries degrade database performance and overflow system memory context.
