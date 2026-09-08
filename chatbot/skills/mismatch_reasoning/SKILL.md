# MISMATCH REASONING & IDENTITY RESOLUTION SKILL

## Purpose
Investigate and explain records that failed automatic matching or were flagged for
manual review, and present a clear side-by-side comparison to the user.

---

## 1. Match Result Statuses

`institution.match_result` → `ref_match_results.match_result_id`
(label column is `match_result_name`):

| Value | Name | Meaning |
|---|---|---|
| 1 | `AUTO_MATCH` | system matched the identity against `master` |
| 2 | `MANUAL_REVIEW` | borderline confidence — flagged for human judgement |
| 3 | `AUTO_UNMATCH` | system found no confident match |
| 4 | `MANUAL_MATCH` | a human confirmed it is a valid match |
| 5 | `MANUAL_UNMATCH` | a human confirmed the records do not match |
| `NULL` | *(unclassified)* | 3.1M rows — matching ran but left no verdict |

Report `NULL` as "belum diklasifikasi", never silently drop it. Use
`LEFT JOIN ref_match_results`, because an `INNER JOIN` discards every NULL row.

---

## 2. The Correct Join Path — Read This Before Writing Any Query

To compare an incoming record against its master counterpart you need three tables.
**There is exactly one correct route:**

```
manual_matches --(file_id + id_incoming)--> institution --(nik_master = nik)--> master
```

### Do NOT join `manual_matches` directly to `master`

`manual_matches.nik_incoming` looks like the obvious join key. It is not — the matching
engine writes `NULL` into it, leaving it empty for **782,472 of 868,562 rows (90%)**.

| Route | Rows returned |
|---|---|
| `mm.nik_incoming = m.nik` ❌ | 86,090 |
| via `institution.nik_master` ✅ | 3,678,357 |

Taking the shortcut makes you report "data tidak ditemukan" for the majority of records
that actually do have a master counterpart.

### Canonical query

```sql
SELECT mm.id_incoming,
       mm.nama_incoming, mm.tempat_lahir_incoming,
       mm.tanggal_lahir_incoming, mm.jenis_kelamin_incoming, mm.nama_ibu_incoming,
       m.nama_lengkap  AS master_nama,
       m.tempat_lahir  AS master_tempat_lahir,
       m.tanggal_lahir AS master_tanggal_lahir,
       m.jenis_kelamin AS master_jenis_kelamin,
       m.nama_ibu      AS master_nama_ibu,
       i.match_score, mm.reason, mm.reasoning_status
FROM manual_matches AS mm
JOIN institution AS i
  ON i.file_id = mm.file_id AND i.id_incoming = mm.id_incoming
LEFT JOIN master AS m
  ON m.nik = i.nik_master
WHERE mm.file_id = '<file_id>'
LIMIT 20
```

Add `AND mm.id_incoming = '<id>'` when the user asks about one specific record.

---

## 3. Column Traps in This Workflow

| Column | Problem | Use instead |
|---|---|---|
| `manual_matches.nik_incoming` | 90% NULL | route via `institution.nik_master` |
| `manual_matches.area_incoming` | **100% NULL** | `master.provinsi` / `kabupaten` / `kecamatan` / `kelurahan` |
| `master.nama` | **100% NULL** (legacy) | `master.nama_lengkap` |
| `institution.match_result_desc` | legacy, 9% filled, contradicts `match_result` | join `ref_match_results` |
| `reasoning_patterns` | only 1 row; resolves 3% of `pattern_name` | read `manual_matches.reason` directly |

**The AI explanation already exists.** `manual_matches.reason` holds the generated
reason text. Do not attempt to reconstruct it from `reasoning_patterns` — read the
column.

`reasoning_status` tells you whether an explanation is ready:
`COMPLETED` (789,694) · `PENDING` (78,794) · `PROCESSING` (39) · `FAILED` (35).
If it is not `COMPLETED`, say the explanation is still being generated.

**Type mismatch:** `manual_matches.tanggal_lahir_incoming` is `varchar` while
`master.tanggal_lahir` is a real `date`. Never compare them directly — present both as
text and let the user see the difference.

**Duplicates:** `institution` contains repeated `(file_id, id_incoming)` pairs from
re-runs, so the join above can return a record more than once. Present each
`id_incoming` only once, and use `COUNT(DISTINCT id_incoming)` for any totals.

---

## 4. Presentation Protocol

1. Fetch the pair using the canonical query in §2.
2. Compare field by field and identify the exact differences — name spelling, date of
   birth, mother's name, place of birth, gender.
3. Present the result in **Bahasa Indonesia** as a Markdown comparison table with three
   columns: *Field*, *Data Institusi*, *Data Master*.
4. Quote `mm.reason` as the system's own explanation.
5. Recommend a concrete next step — correct the institutional spelling, or confirm the
   record manually via the investigate screen.

Never show raw SQL, internal IDs, or database error messages in the final answer.
