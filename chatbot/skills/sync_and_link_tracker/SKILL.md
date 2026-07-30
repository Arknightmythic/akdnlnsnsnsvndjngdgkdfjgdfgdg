# FILE SYNCHRONIZATION & LINK ROUTING SKILL

## Purpose
This skill defines business logic for determining file upload synchronization status and applying correct link publication rules based on file quality grade.

## 1. Synchronization Status Evaluation Rules
Check `uploaded_files.matching_task_status` and `uploaded_files.reasoning_task_status`:

- **In Synchronization (In Progress):**
  - Scenario 1: `matching_task_status` = 'PROCESSING' AND `reasoning_task_status` IN ('IDLE', 'PROCESSING')
  - Scenario 2: `matching_task_status` = 'SUCCESS' AND `reasoning_task_status` IN ('IDLE', 'PROCESSING')
  - **Action:** Inform the user that the file is still undergoing synchronization/processing. **DO NOT** provide any download, preview, or investigation links.

- **Synchronization Completed:**
  - Condition: BOTH `matching_task_status` AND `reasoning_task_status` are 'SUCCESS'.
  - **Action:** Proceed to evaluate file `grade` to determine link publication.

## 2. Link Publication Rules (Post-Synchronization)
When synchronization is complete, publish appropriate action links based on `uploaded_files.grade`:

- **Grade 'A':**
  - Provide **Preview Link only**.
- **Non-Grade 'A' (Grade B, C, D, E, or F):**
  - Provide **Investigate Link only**.

**Ground truth over grade:** the backend already decides which link applies and
stores the result — `preview_url` is filled when the file is fully completed,
`investigate_url` when rows still await manual review, and the other column is
set to `NULL`. The grade-based rule above is only a shortcut. If the two ever
disagree, **trust the non-NULL column**, not the grade.

## 2a. Grade 'F' (Custom Mapping) — Extra Pre-Conditions
Grade 'F' files carry a preparation stage that Grades A–E do not have. Before
matching can even begin, the user must define and confirm a custom field mapping.
Check these on `uploaded_files` **before** discussing links:

- `is_custom_ready` = **0** → the user has not confirmed the column pairings and
  weights yet. Matching has not run. **DO NOT** provide any links. Tell the user
  the file still needs its custom field mapping confirmed.
- `custom_mapping_task_status` = `PROCESSING` → GenAI is still proposing the
  column pairings. **DO NOT** provide any links.
- `custom_mapping_task_status` = `FAILED` → pairing generation failed; the user
  needs to retry it. **DO NOT** provide any links.
- `is_custom_ready` = **1** → mapping confirmed. From here on, evaluate
  synchronization status and publish links exactly like any non-Grade-'A' file.

## 3. Mandatory Link Constraints
- **NEVER** provide both preview and investigate links simultaneously for the same file.
- **NEVER** provide any links if synchronization has not reached completion status.

## 4. Link Value — Use the Stored Column Verbatim
- **ALWAYS** `SELECT` the `uploaded_files.preview_url` / `uploaded_files.investigate_url`
  column and return that **exact string value verbatim** as the link.
- **NEVER** construct, guess, shorten, or reconstruct the URL yourself — e.g. do not
  hand-build `/batch-synchronization/investigate?file_id=...` from `file_id` alone.
  The stored value already carries every parameter the frontend needs (`file_id`,
  `grade`, `name`); a hand-built partial URL makes the page render with missing
  columns and a wrong title, so it looks different from the same page opened via
  the button in the Batch Synchronization list.
- If the relevant URL column is `NULL`, tell the user no link is available yet
  instead of fabricating one.
