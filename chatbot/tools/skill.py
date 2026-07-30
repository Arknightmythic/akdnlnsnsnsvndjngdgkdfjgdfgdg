import os
from langchain.tools import tool

SKILLS_DIR = os.path.join("chatbot", "skills")

@tool
def load_skills(skill_names: list[str]) -> str:
    """Dynamically loads domain business rules and instructions for one or more specific analysis tasks.

    Use this tool whenever you need authoritative business logic, schema guardrails,
    grade criteria, sync status rules, or mismatch analysis procedures.

    Args:
        skill_names (list[str]): List of skill domain identifiers to load simultaneously.
            Supported items in skill_names:

            - 'database_schema_context':
                Context for core database tables (uploaded_files, master, manual_matches,
                institution, ref tables), schema discovery procedures, and critical SQL
                performance constraints (mandatory WHERE/LIMIT clauses for master table).

            - 'sync_and_link_tracker':
                Rules for evaluating batch upload synchronization status (PROCESSING vs SUCCESS)
                and applying action link routing (Grade A = preview link only, Non-Grade A =
                investigate link only).

            - 'data_quality_grading':
                Quality classification thresholds for Grade A through Grade E based on
                completeness across 6 core identity fields (NIK 16 digits, Name, POB, DOB,
                Gender, Mother's Name).

            - 'mismatch_reasoning':
                Protocols for investigating records in MANUAL_REVIEW or AUTO_UNMATCH,
                inspecting manual_matches schemas, performing side-by-side field discrepancy
                comparisons, and formatting corrective recommendations.

    Returns:
        str: The combined full text instructions and guidelines of all requested skills.
    """
    if not isinstance(skill_names, list) or not skill_names:
        return "Error: skill_names must be a non-empty list of skill names."

    loaded_contents = []

    for name in skill_names:
        clean_name = name.strip()
        skill_file = os.path.join(SKILLS_DIR, clean_name, "SKILL.md")

        if os.path.exists(skill_file):
            with open(skill_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                loaded_contents.append(f"=== SKILL: {clean_name} ===\n{content}")
        else:
            loaded_contents.append(
                f"=== SKILL ERROR: {clean_name} ===\n"
                f"Skill '{clean_name}' not found. Available skills: 'database_schema_context', "
                f"'sync_and_link_tracker', 'data_quality_grading', 'mismatch_reasoning'."
            )

    return "\n\n".join(loaded_contents)
