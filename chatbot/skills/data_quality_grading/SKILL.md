# DATA QUALITY GRADING SKILL

## Purpose
This skill defines classification rules and completeness thresholds for data quality grades (Grade A to Grade E) applied to uploaded population datasets.

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
