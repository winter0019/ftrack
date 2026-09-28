import os, sqlite3, sys
import psycopg
from psycopg.rows import dict_row

DATABASE_URL=os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise SystemExit("Set DATABASE_URL to the Render PostgreSQL External Database URL before running this migration.")

SQLITE_PATH=os.environ.get("SQLITE_PATH", os.path.join(os.path.dirname(__file__),"filetrack.db"))
if not os.path.exists(SQLITE_PATH): raise SystemExit(f"SQLite database not found: {SQLITE_PATH}")

conn_sql=sqlite3.connect(SQLITE_PATH); conn_sql.row_factory=sqlite3.Row
conn_pg=psycopg.connect(DATABASE_URL, row_factory=dict_row)

def table(name): return [dict(r) for r in conn_sql.execute(f"SELECT * FROM {name}").fetchall()]

def ensure_schema():
    # Import the same schema as app.py by importing it with DATABASE_URL already set.
    import app
    app.init_db()

ensure_schema()
cur=conn_pg.cursor()
# Order matters because movements/audits reference file IDs conceptually.
for name, cols in {
 'files':['id','file_id','title','reference_no','lga','lgi_name','received_by','received_at','priority','description','attachment','status','current_location','created_at'],
 'movements':['id','file_id','from_location','to_location','forwarded_by','receiving_officer','action','forwarded_at','acknowledged_at','status','remarks','submitted_by','submitted_at'],
 'audit_logs':['id','file_id','action','official','details','created_at'],
 'users':['id','full_name','username','password_hash','role','office','lga','active','created_at'],
 'inspections':['id','inspection_id','lga','ppa_employer','corps_member','subject','findings','recommendations','inspected_by','inspected_at','status'],
 'reports':['id','report_id','lga','report_type','ppa_employer','corps_member','subject','report_body','issued_by','issued_at','status']
}.items():
    rows=table(name)
    if not rows: continue
    for row in rows:
        cols2=', '.join(cols); vals=', '.join(['%s']*len(cols)); updates=', '.join([f'{c}=EXCLUDED.{c}' for c in cols if c!='id'])
        cur.execute(f'INSERT INTO {name} ({cols2}) VALUES ({vals}) ON CONFLICT DO NOTHING', [row.get(c) for c in cols])
    print(f'{name}: {len(rows)} rows processed')
conn_pg.commit()
# Reset identity sequences after preserving explicit IDs.
for name in ['files','movements','audit_logs','users','inspections','reports']:
    cur.execute(f"SELECT setval(pg_get_serial_sequence('{name}','id'), COALESCE(MAX(id),1), MAX(id) IS NOT NULL) FROM {name}")
conn_pg.commit()
cur.close(); conn_pg.close(); conn_sql.close()
print('Migration complete.')
