# DATA QUALITY GRADING SKILL

## Purpose
This skill defines classification rules and completeness thresholds for data quality grades (Grade A to Grade F) applied to uploaded population datasets.

## 1. Six Core Identity Elements
Identity completeness is evaluated across six individual data fields:
1. National ID Number (NIK) - 16 valid digits
2. Full Name
3. Place of Birth
4. Date of Birth
5. Gender
6. Mother's Name

## 2. Quality Grade Classification Rules

### Grade A (Very Complete)
- All 6 core data elements fully filled and strictly validated.
- NIK must be exactly 16 valid digits.
- Full Name, Place of Birth, Date of Birth, Gender, and Mother's Name 100% complete.
- High consistency and zero validation errors across all fields.

### Grade B (Almost Complete)
- Full Name: 100% complete.
- NIK: At least 70% complete/correct.
- Place of Birth, Date of Birth, and Gender: Each at least 70% complete.
- Mother's Name: At least 60% complete.
- Minor gaps or minor field inconsistencies present.

### Grade C (Fairly Complete)
- Five core identity fields present (Full Name, Place of Birth, Date of Birth, Gender, Mother's Name).
- NIK is not required for Grade C classification.
- Core identity fields are filled, even if not fully verified against master registry.

### Grade D (Less Complete with Minimum Requirement)
- Five core identity elements present with minimum completeness threshold:
  - Full Name: 100% complete.
  - Place of Birth, Date of Birth, Gender: Each at least 70% complete.
  - Mother's Name: At least 60% complete.
- Reflects partially incomplete or inconsistently filled records.

### Grade E (Very Incomplete / Variable)
- Minimum of 3 data elements available in flexible combinations, e.g.:
  - Name + Date of Birth + Gender
  - Name + Place of Birth + Date of Birth
  - Name + Place of Birth + Mother's Name
  - Name + Date of Birth + Regional Info (Province/Regency/District/Village)
- Highly variable completeness, non-standard date formats, or name variations.

### Grade F (Custom / User-Defined Mapping)
- **Fallback grade.** Assigned automatically when a file does not satisfy the
  criteria of Grade A through E — typically because its column names are
  non-standard, so the grader cannot recognise the six core identity elements.
- Grade F is **not** a statement that the data is the worst quality. It means
  the file cannot be graded by the standard patterns and therefore requires a
  **custom field mapping** defined by the user before it can be matched.
- Numeric code in `uploaded_files.grade` is **6** (`ref_grades.grade_code` = 'F').

**Custom mapping workflow (unique to Grade F):**
1. User activates custom grading; GenAI proposes pairings between master columns
   and the file's own column names, stored in the `custom_field_mapping` table.
   Progress is tracked in `uploaded_files.custom_mapping_task_status`
   (`IDLE` | `PROCESSING` | `SUCCESS` | `FAILED`).
2. User reviews the pairings and assigns a **weight** to each one. Weights
   (excluding `nik`) must total exactly **1.0**. `nik` carries no weight because
   it is only a blocking key, never scored.
3. The pairing set must include at least one blocking anchor — `nik`,
   `jenis_kelamin`, `nama_lengkap`, or `tanggal_lahir` — otherwise matching is
   rejected to avoid an expensive full cross join.
4. Once confirmed, `uploaded_files.is_custom_ready` becomes **1** and matching
   may run. While it is still **0**, matching cannot start at all.

**Matching behaviour:** identical in structure to Grade A–E (Jaro-Winkler,
`MANUAL_REVIEW` rows, AI reasoning, export), except the join condition and the
similarity score are built dynamically from the user's pairings and weights
instead of a fixed per-grade formula.
