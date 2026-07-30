# MISMATCH REASONING & IDENTITY RESOLUTION SKILL

## Purpose
This skill guides the agent in investigating, explaining, and presenting reasoning for data records that failed automatic matching or require manual review.

## 1. Schema Inspection Requirement
Before querying mismatch details or reason fields:
- Always call `get_table_detail` on table `manual_matches` to inspect its exact schema, column names, and sample rows.
- Do not assume column names for mismatch reasons.

## 2. Match Result Reference Statuses
Map `institution.match_result` via `ref_match_results`:
- `AUTO_MATCH`: System automatically matched identity to national registry (`master`).
- `AUTO_UNMATCH`: System determined no confident match exists.
- `MANUAL_REVIEW`: Records flagged for human judgment due to borderline confidence or field discrepancies.
- `MANUAL_MATCH`: Human judge confirmed a valid match.
- `MANUAL_UNMATCH`: Human judge confirmed records do not match.

## 3. Reasoning & Comparison Protocol
When explaining why a record is `UNMATCH` or in `MANUAL_REVIEW`:
1. Retrieve institutional data from `institution` and corresponding candidate data from `master` or discrepancy reasons from `manual_matches`.
2. Perform side-by-side field comparison identifying exact field differences (e.g., Name spelling discrepancy, Date of Birth mismatch, Mother's Name variation).
3. Present findings clearly in Bahasa Indonesia using a structured comparison table.
4. Recommend concrete corrective action (e.g., updating institutional spelling or proceeding with manual review confirmation).
