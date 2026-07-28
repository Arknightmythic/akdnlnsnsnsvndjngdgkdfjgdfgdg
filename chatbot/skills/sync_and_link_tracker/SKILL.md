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
- **Non-Grade 'A' (Grade B, C, D, or E):**
  - Provide **Investigate Link only**.

## 3. Mandatory Link Constraints
- **NEVER** provide both preview and investigate links simultaneously for the same file.
- **NEVER** provide any links if synchronization has not reached completion status.
