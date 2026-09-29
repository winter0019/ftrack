# FileTrack Inspection UI - integrated version

This version keeps the existing File Movement dashboard and adds Inspection server-side.

1. Back up your current `app.py`.
2. Replace `app.py` with this package version.
3. Copy the included `templates/inspection_*.html` files into your existing `templates` folder (they are already included under `templates/`).
4. Keep the existing PostgreSQL database. Do NOT drop or reset tables.
5. Ensure `openpyxl>=3.1.0` is in `requirements.txt`.
6. Stop Flask completely with Ctrl+C and start it again.
7. Hard-refresh the browser with Ctrl+F5.

After login as Administrator, the top navigation will contain **Inspection**, and the dashboard will show **Inspection & PPA Monitoring** with an **Open Inspection Module** button.

Direct URL: `http://127.0.0.1:5000/inspections`


### Corps Member Import — NYSC workbook format fix
The Inspection importer now accepts the standard NYSC workbook structure used by the Zonal Office:
- `Expected` sheet is read automatically.
- `Statecode` is mapped to State Code.
- `Surname` + `Othernames` are combined into the Corps Member name.
- `Company` is mapped to PPA/Establishment.
- `GSMNO`, `Gender`, `Stream`, and `course` are mapped to their corresponding fields.
- Batch is inferred from the State Code when available (`KT/25C/...`, `KT/26A/...`, `KT/26B/...`).
- `rimiC.xlsx`, `rimiA.xlsx`, `rimi.xlsx` and the equivalent filenames for Batagarawa, Kaita, Jibia and Charanchi automatically resolve to their LGA.
- Katsina filenames are intentionally not auto-assigned to Katsina A or Katsina B; select the correct component in the LGA field.
- Multiple Excel/CSV files can be selected in one import.
- Existing PostgreSQL records are updated by State Code; nothing is dropped or reset.

This fixes the previous `State Code, Name, PPA/Establishment and LGA are required` errors for the actual NYSC files.


## Import fix for the consolidated zonal workbook
This version accepts `Katsina_Zonal_Corps_Members_By_LGA.xlsx` directly. It reads `All Corps Members` and maps `State Code`, `Name`, `Establishment`, `LGA`, `Component`, `Gender`, `Course`, `Stream`, `GSM No.`, and `Batch`. In that workbook, Katsina A and Katsina B rows have `LGA=KATSINA`; the importer uses the `Component` column to normalize them to `Katsina A` and `Katsina B`.

Do not reset or recreate PostgreSQL. Replace the running `app.py` and `templates/inspection_import.html` with this package, restart Flask/Gunicorn, then import the workbook.
