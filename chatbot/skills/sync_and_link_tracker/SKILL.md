# FILE SYNCHRONIZATION & LINK ROUTING SKILL

## Purpose
Determine whether an uploaded file has finished synchronising, and decide which action
link (preview or investigate) may be published to the user.

---

## 1. `sync_status` Is the Single Source of Truth

The backend writes the file's lifecycle stage into **`uploaded_files.sync_status`**.
This is the authoritative signal — it is what the Batch Synchronization screen displays,
and it is the only column whose values are guaranteed consistent.

| `sync_status` | `ref_sync_statuses.status_code` | Meaning | Links allowed |
|---|---|---|---|
| `NULL` | *(no label — use 'Belum Disinkronkan')* | file uploaded and graded, matching never started | **none** |
| `1` | `In Progress` | matching done, AI reasoning still running | **none** |
| `2` | `Awaiting Action` | reasoning finished, rows await human review | **investigate only** |
| `3` | `Completed` | file fully finished | **preview only** |

Always resolve the label with a `LEFT JOIN` to `ref_sync_statuses`, and always
`COALESCE` the NULL case — 63 of 141 files currently have `sync_status = NULL` and an
`INNER JOIN` would make them vanish from your answer entirely.

```sql
LEFT JOIN ref_sync_statuses AS rs ON uf.sync_status = rs.sync_status_id
...
COALESCE(rs.status_code, 'Belum Disinkronkan') AS sync_status
```

### Task status columns are diagnostics, not the verdict

`matching_task_status` and `reasoning_task_status` describe *individual background
workers*, not the file's overall stage. Use them only when the user asks specifically
why something is stuck, or to add detail to a "still processing" answer.

Do **not** derive completion from them. Real combinations currently in the database
include `matching_task_status = 'SUCCESS'` with `reasoning_task_status = 'IDLE'` (26
files) and `matching_task_status = 'PROCESSING'` with `reasoning_task_status = 'SUCCESS'`
(3 files) — states that no simple two-column rule predicts correctly. `sync_status`
already reflects the true outcome of all of them.

Likewise `is_sync` is a coarse legacy flag and can disagree with `sync_status`
(2 files have `is_sync = 0` while `sync_status = 2`). **Prefer `sync_status`.**

---

## 2. Which Link to Publish

The backend has already decided this and stored the result. **Read the columns; do not
infer.**

- `preview_url` is filled when the file is completed (`sync_status = 3`);
  `investigate_url` is set to `NULL`.
- `investigate_url` is filled when rows still await manual review (`sync_status = 2`);
  `preview_url` is set to `NULL`.

**Rule: publish whichever of the two columns is non-NULL.** If both are NULL, no link is
available yet — say so plainly instead of constructing one.

> Note: file `grade` does **not** determine which link applies. Any older guidance
> tying "Grade A → preview" is a rough heuristic only; `sync_status` and the stored URL
> columns override it in every case.

Only 8 files currently have a `preview_url` and 7 have an `investigate_url`, so "no link
available yet" is a common and correct answer.

---

## 3. Grade F (Custom Mapping) — Extra Pre-Conditions

Grade F files have a preparation stage that Grades A–E do not. Matching cannot start
until the user confirms a custom field mapping. Check these on `uploaded_files`
**before** discussing links:

- `is_custom_ready = 0` → column pairings and weights are not confirmed. Matching has
  not run. **No links.** Tell the user the file still needs its custom field mapping
  confirmed.
- `custom_mapping_task_status = 'PROCESSING'` → GenAI is still proposing pairings.
  **No links.**
- `custom_mapping_task_status = 'FAILED'` → pairing generation failed; the user needs to
  retry it. **No links.**
- `is_custom_ready = 1` → mapping confirmed. From here evaluate `sync_status` exactly
  like any other file.

To show the confirmed pairings, query `custom_field_mapping` with `is_active = 1`.

---

## 4. Mandatory Link Constraints

- **NEVER** publish both preview and investigate links for the same file.
- **NEVER** publish any link while `sync_status` is `NULL` or `1`.
- **ALWAYS** return the stored column value **verbatim**. Never construct, guess,
  shorten, or rebuild a URL — e.g. do not hand-build
  `/batch-synchronization/investigate?file_id=...` from `file_id` alone. The stored value
  already carries every parameter the frontend needs (`file_id`, `grade`, `name`); a
  hand-built partial URL renders the page with missing columns and a wrong title.
- If the relevant URL column is `NULL`, state that no link is available yet rather than
  fabricating one.

---

## 5. Reference Query

```sql
SELECT uf.file_id, uf.original_filename, uf.institution_name,
       rg.grade_code AS grade,
       COALESCE(rs.status_code, 'Belum Disinkronkan') AS sync_status,
       uf.matching_task_status, uf.reasoning_task_status,
       uf.custom_mapping_task_status, uf.is_custom_ready,
       uf.preview_url, uf.investigate_url
FROM uploaded_files AS uf
LEFT JOIN ref_grades AS rg        ON uf.grade       = rg.grade_id
LEFT JOIN ref_sync_statuses AS rs ON uf.sync_status = rs.sync_status_id
WHERE uf.file_id = '<file_id>'
LIMIT 1
```
