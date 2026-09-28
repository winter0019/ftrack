Katsina Zonal FileTrack — Inspection & LGI Reporting Update

Purpose
- Supporting Staff can create and submit field inspection records to the Zonal Inspector.
- LGI Officers cannot create or access inspections.
- LGI Officers have report-only access.
- Administrator/Zonal Inspector can issue reports to a selected LGA.
- LGI Officers can see only reports issued for their own assigned LGA.
- Reports can be about the LGA generally, a PPA/employer, or a Corps Member.
- LGI Officers are blocked from the File Register, file details and file downloads.

Changed files
- app.py
- templates/base.html
- templates/dashboard.html
- templates/users.html
- templates/inspections.html
- templates/inspection_form.html
- templates/reports.html
- templates/report_form.html

Database
- New SQLite tables (inspections and reports) are created automatically by app.py.
- Existing filetrack.db data is preserved; do not replace filetrack.db with a blank database.

Deployment
1. Stop the local Flask server if running.
2. Back up app.py and filetrack.db.
3. Replace the changed files listed above.
4. Commit/push to GitHub main.
5. Render will redeploy.
6. Test with Supporting Staff: Dashboard > Inspections > New Inspection.
7. Test with Administrator/Zonal Inspector: Dashboard > Inspections and Reports > Issue Report.
8. Test with LGI Officer: Dashboard > Reports. Confirm only reports matching the LGI account's LGA are visible.

Important
The current project still uses SQLite. This update does not migrate the application to the Render PostgreSQL database. That should be handled separately so existing records are not lost.
