# FileTrack Inspection Module

This update adds controlled PPA/Establishment inspection to the existing PostgreSQL FileTrack application.

## Rules
- PPA/Establishment is the single posting field. `place_of_posting` and `ppa_employer` are not separate fields in the new inspection workflow.
- Administrator/Zonal Inspector can upload CSV/XLSX corps-member data and assign each PPA to a Supporting Staff member.
- Supporting Staff can see only actively assigned PPAs.
- A Supporting Staff member can search a State Code only inside the selected assigned PPA.
- Status options: Present, Absent, Leave, Sick Leave, Maternity Leave, Others.
- Absent automatically sets Query Issued = YES.
- Existing FileTrack tables and the legacy `inspections`/`reports` tables are preserved.

## Excel/CSV required columns
State Code, Corps Member Name, PPA / Establishment, LGA

Optional: Gender, Discipline, Batch, Stream, Phone, Status.

## Installation
1. Back up the existing `app.py`.
2. Replace it with the supplied updated `app.py`.
3. Copy the four templates into the existing project's `templates` directory.
4. Add `openpyxl>=3.1.0` to requirements.txt for XLSX support. CSV works without it.
5. Start the application. The PostgreSQL `init_db()` migration creates the new tables automatically; it does not drop existing data.
