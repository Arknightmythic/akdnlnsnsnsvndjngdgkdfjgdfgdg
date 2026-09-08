# DATABASE SCHEMA & QUERY SAFETY SKILL

## Purpose
Authoritative schema reference for the `synchrono` database (StarRocks, MySQL dialect).
Every column name, join key, and reference value below is verified against the live
database. **Trust this document over your own guesses** — several tables contain legacy
or always-empty columns whose names look more natural than the correct ones.

---

## 0. Tables You Can Query

Eleven tables are reachable:

| Table | Rows | Purpose |
|---|---|---|
| `uploaded_files` | 141 | one row per uploaded file — the status hub |
| `institution` | 21.4M | incoming rows paired with match results |
| `master` | 299,088 | population reference registry |
| `manual_matches` | 868,562 | rows needing human review + AI explanations |
| `custom_field_mapping` | 36 | Grade F column pairings |
| `grade_rules` | 6 | scoring thresholds per grade |
| `reasoning_patterns` | 1 | AI reason template cache (nearly empty) |
| `ref_grades` | 6 | lookup |
| `ref_match_results` | 5 | lookup |
| `ref_process` | 2 | lookup |
| `ref_sync_statuses` | 3 | lookup |

Audit, chat-history, and internal checkpoint tables are intentionally out of scope.

---

## 1. Reference Tables — Memorise These, Never Query Them

Each lookup table names its columns **differently**. Do not pattern-match; use exactly these:

| Table | ID column | Label column |
|---|---|---|
| `ref_grades` | `grade_id` | `grade_code` |
| `ref_match_results` | `match_result_id` | `match_result_name` |
| `ref_process` | `process_id` | `process_name` |
| `ref_sync_statuses` | `sync_status_id` | `status_code` |

There is **no** `ref_match_results.id`, no `grade_name`, no `status_name`.

Full contents — small and stable, so resolve labels yourself instead of joining when
you only need to filter:

```
ref_grades          1=A  2=B  3=C  4=D  5=E  6=F
ref_process         1=UPLOADED   2=GRADED
ref_sync_statuses   1='In Progress'   2='Awaiting Action'   3='Completed'
ref_match_results   1=AUTO_MATCH   2=MANUAL_REVIEW   3=AUTO_UNMATCH
                    4=MANUAL_MATCH  5=MANUAL_UNMATCH
```

### Foreign keys into these tables

```
uploaded_files.grade             → ref_grades.grade_id
uploaded_files.processing_status → ref_process.process_id
uploaded_files.sync_status       → ref_sync_statuses.sync_status_id
institution.match_result         → ref_match_results.match_result_id
```

### CRITICAL: always LEFT JOIN, never INNER JOIN

`uploaded_files.sync_status` is **NULL for 63 of 141 files** (files that have never been
matched), and `institution.match_result` is **NULL for 3.1M rows**. An `INNER JOIN` to a
reference table silently discards every one of those rows.

Measured on the live database:

| Query shape | Rows returned |
|---|---|
| `uploaded_files` INNER JOIN all three ref tables | **78** ❌ |
| `uploaded_files` LEFT JOIN all three ref tables | **141** ✅ |

Use `LEFT JOIN` plus `COALESCE(rs.status_code, 'Belum Disinkronkan')` so unmatched files
still appear with an honest label.

---

## 2. Table Schemas

### `uploaded_files` — 141 rows · PK `file_id` (varchar)
The status hub. One row per uploaded file. Small, safe to scan.

```
file_id                     varchar   PK — 8 hex chars, e.g. '5621ca9b'
original_filename           varchar
institution_name            varchar
minio_path                  varchar
upload_timestamp            datetime
row_count                   int
grading_time_ms             int
matching_time_ms            int
is_sync                     boolean   0/1
sync_status                 tinyint   → ref_sync_statuses   ⚠ NULL for 63 files
processing_status           tinyint   → ref_process
grade                       tinyint   → ref_grades
matching_task_status        varchar   IDLE|PROCESSING|SUCCESS|FAILED
reasoning_task_status       varchar   IDLE|PROCESSING|SUCCESS|FAILED
custom_mapping_task_status  varchar   IDLE|PROCESSING|SUCCESS|FAILED
export_status               varchar   IDLE|PROCESSING|READY|FAILED
export_match_path           varchar
export_unmatch_path         varchar
matching_task_id            varchar
reasoning_task_id           varchar
custom_mapping_task_id      varchar
investigate_url             varchar(1024)   only 7 files have this
preview_url                 varchar(1024)   only 8 files have this
is_custom_ready             tinyint   0/1 — Grade F only
```

⚠⚠ **"Completed" / "In Progress" / "Awaiting Action" are values of `sync_status` — NOT
task statuses.** When a user asks how many files are completed, done, finished, still
running, or awaiting action, the answer comes from `sync_status` via
`ref_sync_statuses`. **Never answer those questions with `matching_task_status`.**

The two columns disagree, and the task-status shortcut gives the wrong number:

| Way of counting "Completed" | Result |
|---|---|
| `sync_status = 3` (`status_code = 'Completed'`) ✅ | **41** |
| `matching_task_status = 'SUCCESS'` ❌ | 35 |

`matching_task_status` and `reasoning_task_status` describe individual background
workers. Use them only when the user asks specifically why a file is stuck, or to add
detail to a "still processing" answer — never as the file's overall stage.

### `institution` — 21.4M rows · PK `id` (bigint)
Match results, one row per incoming record per matching run.

```
id                 bigint    PK — internal surrogate key
id_incoming        varchar   row number from the user's CSV  ⚠ see §3
nik_master         varchar   → master.nik  (the matched identity)
file_id            varchar   → uploaded_files.file_id
match_score        double    0–100
match_result       tinyint   → ref_match_results   ⚠ NULL for 3,165,064 rows
upload_date        datetime
inserted_date      datetime
match_result_desc  varchar   ⚠⚠ LEGACY — DO NOT USE (see below)
```

**Join key to `manual_matches` is the pair `file_id` + `id_incoming`** — never `id`.

⚠ **`match_result_desc` is forbidden.** Only 9% populated and its values contradict
`match_result`: rows with `match_result = 1` are labelled `MATCHED` instead of
`AUTO_MATCH`, some rows carry `NO_NIK_MATCH` which is not a valid status at all, and
1.36M rows have a label while `match_result` itself is NULL. Always derive the label by
joining `ref_match_results` on `match_result`.

⚠ **This table contains duplicates.** 21,397,000 rows cover only 14,200,835 distinct
`(file_id, id_incoming)` pairs, because re-running a match appends rows rather than
replacing them. One file has a 15× duplication ratio. Never count with plain `COUNT(*)`
— totals come out inflated several-fold.

⚠⚠ **`id_incoming` is NOT globally unique — it is the row number inside one CSV file.**
Every file restarts at 1, so values collide massively across files: all 74 files together
use only **456,975 distinct `id_incoming` values** to represent **14,200,835 distinct
records**. Choosing the wrong dedup key breaks counts in opposite directions:

| Scope of the question | Correct counting expression |
|---|---|
| **One file** (`WHERE file_id = '...'`) | `COUNT(DISTINCT id_incoming)` |
| **Across files** (totals, summaries, "last year") | `COUNT(DISTINCT CONCAT(file_id, '#', id_incoming))` |

Using `COUNT(DISTINCT id_incoming)` on a cross-file question **under-counts by roughly
20×** — e.g. AUTO_MATCH in the last year is 7,934,044 records, but the id-only version
reports 398,805. Always include `file_id` in the dedup key unless you have filtered to a
single file.

**Time filters:** use `upload_date` (when the user's file was uploaded), not
`inserted_date` (when the matching worker wrote the row).

### `master` — 299,088 rows · key `nik`
Population reference registry.

```
id               bigint   PK
nik              varchar  16 digits — the join key
nama_lengkap     varchar  ✅ THE NAME COLUMN — use this
nama             varchar  ⚠⚠ 100% NULL (0 of 299,088) — NEVER USE
tempat_lahir     varchar
tanggal_lahir    date     ← real DATE type
jenis_kelamin    varchar  'L' or 'P' only
nama_ibu         varchar
status_kematian  varchar  'hidup' or 'meninggal' only
provinsi         varchar  uppercase, e.g. 'JAWA TIMUR'
kabupaten        varchar
kecamatan        varchar
kelurahan        varchar
```

⚠ **`nama` is a dead legacy column and appears before `nama_lengkap` in `DESCRIBE`.**
Searching `WHERE nama LIKE '%...%'` always returns zero rows and will make you wrongly
report that a person does not exist. Search `nama_lengkap`.

**Sizing:** ~300 thousand rows, not billions. Aggregates (`COUNT`, `GROUP BY provinsi`,
`AVG`) run fine and are allowed. Only listing queries need a `LIMIT`.

### `manual_matches` — 868,562 rows · PK `id` (bigint)
Rows flagged `MANUAL_REVIEW`, plus the AI-generated explanation.

```
id                      bigint   PK
file_id                 varchar  ┐ join pair to institution
id_incoming             varchar  ┘
nama_incoming           varchar
tempat_lahir_incoming   varchar
tanggal_lahir_incoming  varchar  ⚠ VARCHAR, while master.tanggal_lahir is DATE
jenis_kelamin_incoming  varchar
nama_ibu_incoming       varchar
reason                  varchar  ✅ the AI explanation — this is what users want
pattern_name            varchar
reasoning_source        varchar  'CACHE' or 'LLM'
reasoning_status        varchar  PENDING|PROCESSING|COMPLETED|FAILED
nik_incoming            varchar  ⚠⚠ 90% NULL — see below
area_incoming           varchar  ⚠⚠ 100% NULL — never use
```

Current `reasoning_status` distribution: COMPLETED 789,694 · PENDING 78,794 ·
PROCESSING 39 · FAILED 35.

⚠ **Never join `manual_matches` to `master` via `nik_incoming`.** That column is NULL for
782,472 of 868,562 rows. The correct route goes through `institution`:

```
manual_matches --(file_id + id_incoming)--> institution --(nik_master = nik)--> master
```

Measured difference: the `nik_incoming` shortcut returns 86,090 rows; the correct route
returns 3,678,357 — **43× more data**. Using the shortcut makes you report "data not
found" for the majority of records.

⚠ For regional data (province/regency/district) use `master`, not `area_incoming`.

### `custom_field_mapping` — 36 rows · PK `id`
Grade F column pairings only.

```
id, file_id, master_column, incoming_column,
weight      double   user-assigned; excluding nik they total 1.0
confidence  double   GenAI confidence
source      varchar  'GENAI' or 'USER_EDITED'
is_active   boolean  ⚠ filter is_active = 1 — inactive rows are audit history
created_at, updated_at
```

### `grade_rules` — 6 rows · PK `grade_code` (tinyint)
Classification thresholds. `grade_code` here is the **numeric** 1–6, matching
`uploaded_files.grade`.

```
grade_code, auto_missing_max, auto_score_min,
review_missing_count, review_score_min, review_score_max
```

### `reasoning_patterns` — 1 row · PK `pattern_hash`
Template cache for AI reasons. ⚠ **Practically empty.** Only 24,011 of 789,694 completed
`manual_matches` rows have a `pattern_name` that resolves here. Never join through it to
retrieve explanations — read `manual_matches.reason` directly.

---

## 3. Data Type Traps

**`id_incoming` is `varchar`, not a number.** `ORDER BY id_incoming` sorts
lexicographically and produces `1, 10, 100, 1000, 10000…`. For numeric ordering:

```sql
ORDER BY CAST(id_incoming AS BIGINT)
```

**`institution.id` is not `id_incoming`.** `id` is an internal surrogate key
(e.g. 6499994); `id_incoming` is the user's CSV row number (e.g. 2519). When a user
mentions "ID 8302843", they almost always mean **`id_incoming`**. If a filter on
`id_incoming` returns nothing, try `id` before concluding the record does not exist.

**Dates:** `manual_matches.tanggal_lahir_incoming` is `varchar` while
`master.tanggal_lahir` is `date`. Never compare them directly — cast explicitly, and
expect mixed formats in the varchar side.

**`is_sync` vs `sync_status`:** `sync_status` is authoritative. Current distribution —
`is_sync=0 / sync_status=NULL`: 63 · `is_sync=1 / sync_status=2`: 32 ·
`is_sync=1 / sync_status=3`: 41 · `is_sync=1 / sync_status=1`: 3 ·
`is_sync=0 / sync_status=2`: 2.

---

## 4. Mandatory LIMIT Guardrail

- Every listing `SELECT` **MUST** carry an explicit `LIMIT` (e.g. `LIMIT 20`).
- Aggregate queries (`COUNT`, `SUM`, `AVG`, `GROUP BY` summaries) do **not** need a LIMIT
  and are allowed on every table, including `master` and `institution`.
- Always filter `institution` and `manual_matches` by `file_id` when the question is
  about a specific file.
- Use explicit aliases with `AS`.

---

## 5. Verified Query Recipes

Adapt these rather than composing from scratch. They are known-correct.

### R1 — List recent uploads with readable labels
```sql
SELECT uf.file_id, uf.original_filename, uf.institution_name,
       uf.upload_timestamp, uf.row_count,
       rg.grade_code AS grade,
       rp.process_name AS processing_status,
       COALESCE(rs.status_code, 'Belum Disinkronkan') AS sync_status
FROM uploaded_files AS uf
LEFT JOIN ref_grades AS rg        ON uf.grade             = rg.grade_id
LEFT JOIN ref_process AS rp       ON uf.processing_status = rp.process_id
LEFT JOIN ref_sync_statuses AS rs ON uf.sync_status       = rs.sync_status_id
ORDER BY uf.upload_timestamp DESC
LIMIT 20
```

### R2 — Overall file counts by synchronisation status
```sql
SELECT COALESCE(rs.status_code, 'Belum Disinkronkan') AS status,
       COUNT(*) AS jumlah_file
FROM uploaded_files AS uf
LEFT JOIN ref_sync_statuses AS rs ON uf.sync_status = rs.sync_status_id
GROUP BY status
ORDER BY jumlah_file DESC
```

### R3 — Match result breakdown for one file (duplicate-safe)
```sql
SELECT COALESCE(rm.match_result_name, 'BELUM_DIKLASIFIKASI') AS hasil,
       COUNT(DISTINCT i.id_incoming) AS jumlah
FROM institution AS i
LEFT JOIN ref_match_results AS rm ON i.match_result = rm.match_result_id
WHERE i.file_id = '<file_id>'
GROUP BY hasil
ORDER BY jumlah DESC
```

### R4 — Manual review detail with its master counterpart
```sql
SELECT mm.id_incoming,
       mm.nama_incoming, mm.tempat_lahir_incoming,
       mm.tanggal_lahir_incoming, mm.nama_ibu_incoming,
       m.nama_lengkap  AS master_nama,
       m.tempat_lahir  AS master_tempat_lahir,
       m.tanggal_lahir AS master_tanggal_lahir,
       m.nama_ibu      AS master_nama_ibu,
       i.match_score, mm.reason
FROM manual_matches AS mm
JOIN institution AS i
  ON i.file_id = mm.file_id AND i.id_incoming = mm.id_incoming
LEFT JOIN master AS m
  ON m.nik = i.nik_master
WHERE mm.file_id = '<file_id>'
  AND mm.reasoning_status = 'COMPLETED'
LIMIT 20
```
> Because `institution` holds duplicates, a record may appear more than once here.
> Present each `id_incoming` only once in your answer.

### R5 — Find a person in the master registry
```sql
SELECT nik, nama_lengkap, tempat_lahir, tanggal_lahir,
       jenis_kelamin, nama_ibu, provinsi, kabupaten, status_kematian
FROM master
WHERE nama_lengkap LIKE '%<keyword>%'
LIMIT 20
```

### R6 — Status and action link for one file
```sql
SELECT uf.file_id, uf.institution_name,
       rg.grade_code AS grade,
       COALESCE(rs.status_code, 'Belum Disinkronkan') AS sync_status,
       uf.matching_task_status, uf.reasoning_task_status,
       uf.is_custom_ready, uf.preview_url, uf.investigate_url
FROM uploaded_files AS uf
LEFT JOIN ref_grades AS rg        ON uf.grade       = rg.grade_id
LEFT JOIN ref_sync_statuses AS rs ON uf.sync_status = rs.sync_status_id
WHERE uf.file_id = '<file_id>'
LIMIT 1
```

### R7 — Grade F column pairings for one file
```sql
SELECT master_column, incoming_column, weight, confidence, source
FROM custom_field_mapping
WHERE file_id = '<file_id>' AND is_active = 1
ORDER BY weight DESC
LIMIT 20
```

### R8 — Match result summary ACROSS all files (e.g. "last year")
Note the dedup key includes `file_id`. This is the shape to use for any total,
summary, or period-based question.
```sql
SELECT COALESCE(rm.match_result_name, 'BELUM_DIKLASIFIKASI') AS hasil,
       COUNT(DISTINCT CONCAT(i.file_id, '#', i.id_incoming)) AS jumlah
FROM institution AS i
LEFT JOIN ref_match_results AS rm ON i.match_result = rm.match_result_id
WHERE i.upload_date >= DATE_SUB(NOW(), INTERVAL 1 YEAR)
GROUP BY hasil
ORDER BY jumlah DESC
```
> Do not sum these group totals to produce a grand total. A record that was re-matched
> can carry different results across runs, so the groups overlap slightly
> (≈17,700 records). For a true total, count the distinct pairs in one separate query.

### R9 — File counts by stage (uses `sync_status`, not task status)
```sql
SELECT COALESCE(rs.status_code, 'Belum Disinkronkan') AS status,
       COUNT(*) AS jumlah_file
FROM uploaded_files AS uf
LEFT JOIN ref_sync_statuses AS rs ON uf.sync_status = rs.sync_status_id
GROUP BY status
ORDER BY jumlah_file DESC
```
Current correct answer: Belum Disinkronkan 63 · Completed 41 · Awaiting Action 34 ·
In Progress 3 (total 141).

---

## 6. Self-Check Before Running Any Query

1. Did I use `LEFT JOIN` for every reference table?
2. Is my `institution` dedup key right for the scope? One file →
   `COUNT(DISTINCT id_incoming)`. Across files →
   `COUNT(DISTINCT CONCAT(file_id, '#', id_incoming))`. Never plain `COUNT(*)`.
3. Is this a question about file stage (completed / in progress / awaiting action)? Then
   it must come from `sync_status`, never `matching_task_status`.
4. Am I using `nama_lengkap` (not `nama`) for master names?
5. Am I reaching `master` from `manual_matches` **via `institution`**, not via
   `nik_incoming`?
6. Did I avoid `match_result_desc` and `area_incoming` entirely?
7. For a time-based question, did I filter on `upload_date`?
8. Does the listing query have a `LIMIT`?
