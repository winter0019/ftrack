from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session
import sqlite3, os
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

BASE=os.path.dirname(os.path.abspath(__file__))
DB=os.path.join(BASE,"filetrack.db")
UPLOADS=os.path.join(BASE,"uploads")
os.makedirs(UPLOADS,exist_ok=True)

app=Flask(__name__)
app.secret_key=os.environ.get("FILETRACK_SECRET","change-this-secret-key")

LGAS=["Katsina A","Katsina B","Batagarawa","Kaita","Jibia","Rimi","Charanchi"]
BRANCHES=["CIM","CW&HS","CDS"]
PRIORITIES=["Normal","High","Urgent"]
ROLES=["Administrator","Zonal Inspector","LGI Officer","Branch Official","Supporting Staff"]

DATABASE_URL=os.environ.get("DATABASE_URL","").strip()
USING_POSTGRES=bool(DATABASE_URL)

if USING_POSTGRES:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        raise RuntimeError("DATABASE_URL is set, but psycopg is not installed. Add psycopg[binary] to requirements.txt.")

class DBConnection:
    """Small compatibility wrapper so the existing FileTrack SQL can run on SQLite locally
    and PostgreSQL on Render without changing the application workflow."""
    def __init__(self):
        if USING_POSTGRES:
            self.conn=psycopg.connect(DATABASE_URL, row_factory=dict_row)
        else:
            self.conn=sqlite3.connect(DB)
            self.conn.row_factory=sqlite3.Row

    def execute(self, sql, params=()):
        if USING_POSTGRES:
            sql=sql.replace("?", "%s")
        return self.conn.execute(sql, params)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    def executescript(self, sql):
        if USING_POSTGRES:
            # PostgreSQL supports multiple statements in a single execute.
            self.conn.execute(sql)
        else:
            self.conn.executescript(sql)

def db():
    return DBConnection()

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def init_db():
    c=db()
    if USING_POSTGRES:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS files(
          id SERIAL PRIMARY KEY,
          file_id TEXT UNIQUE NOT NULL,
          title TEXT NOT NULL,
          reference_no TEXT,
          lga TEXT NOT NULL,
          lgi_name TEXT,
          received_by TEXT NOT NULL,
          received_at TEXT NOT NULL,
          priority TEXT DEFAULT 'Normal',
          description TEXT,
          attachment TEXT,
          status TEXT DEFAULT 'Received',
          current_location TEXT DEFAULT 'Katsina Zonal Office',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS movements(
          id SERIAL PRIMARY KEY,
          file_id TEXT NOT NULL,
          from_location TEXT NOT NULL,
          to_location TEXT NOT NULL,
          forwarded_by TEXT,
          receiving_officer TEXT,
          action TEXT,
          forwarded_at TEXT NOT NULL,
          acknowledged_at TEXT,
          status TEXT DEFAULT 'Forwarded',
          remarks TEXT,
          submitted_by TEXT,
          submitted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS audit_logs(
          id SERIAL PRIMARY KEY,
          file_id TEXT NOT NULL,
          action TEXT NOT NULL,
          official TEXT,
          details TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users(
          id SERIAL PRIMARY KEY,
          full_name TEXT NOT NULL,
          username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL,
          office TEXT,
          lga TEXT,
          active INTEGER DEFAULT 1,
          created_at TEXT NOT NULL
        );
        """)
    else:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS files(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          file_id TEXT UNIQUE NOT NULL,
          title TEXT NOT NULL,
          reference_no TEXT,
          lga TEXT NOT NULL,
          lgi_name TEXT,
          received_by TEXT NOT NULL,
          received_at TEXT NOT NULL,
          priority TEXT DEFAULT 'Normal',
          description TEXT,
          attachment TEXT,
          status TEXT DEFAULT 'Received',
          current_location TEXT DEFAULT 'Katsina Zonal Office',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS movements(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          file_id TEXT NOT NULL,
          from_location TEXT NOT NULL,
          to_location TEXT NOT NULL,
          forwarded_by TEXT,
          receiving_officer TEXT,
          action TEXT,
          forwarded_at TEXT NOT NULL,
          acknowledged_at TEXT,
          status TEXT DEFAULT 'Forwarded',
          remarks TEXT,
          submitted_by TEXT,
          submitted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS audit_logs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          file_id TEXT NOT NULL,
          action TEXT NOT NULL,
          official TEXT,
          details TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          full_name TEXT NOT NULL,
          username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL,
          office TEXT,
          lga TEXT,
          active INTEGER DEFAULT 1,
          created_at TEXT NOT NULL
        );
        """)
        # Phase 2 delivery-confirmation fields for existing local SQLite databases.
        for statement in [
            "ALTER TABLE movements ADD COLUMN submitted_by TEXT",
            "ALTER TABLE movements ADD COLUMN submitted_at TEXT",
        ]:
            try:
                c.execute(statement)
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    raise
    c.commit()
    c.close()

def migrate_bundled_sqlite_to_postgres_if_empty():
    """On the first Render startup, copy the bundled SQLite records into the new Postgres DB.
    This is deliberately one-time: it only runs when the Postgres users/files tables are empty.
    """
    if not USING_POSTGRES or not os.path.exists(DB):
        return
    c=db()
    counts={
        "users": c.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"],
        "files": c.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"],
    }
    c.close()
    if counts["users"] or counts["files"]:
        return

    src=sqlite3.connect(DB)
    src.row_factory=sqlite3.Row
    dst=db()
    try:
        for table, columns in [
            ("users", ["id","full_name","username","password_hash","role","office","lga","active","created_at"]),
            ("files", ["id","file_id","title","reference_no","lga","lgi_name","received_by","received_at","priority","description","attachment","status","current_location","created_at"]),
            ("movements", ["id","file_id","from_location","to_location","forwarded_by","receiving_officer","action","forwarded_at","acknowledged_at","status","remarks","submitted_by","submitted_at"]),
            ("audit_logs", ["id","file_id","action","official","details","created_at"]),
        ]:
            try:
                rows=src.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY id").fetchall()
            except sqlite3.OperationalError:
                # Older SQLite files may not have the new delivery columns.
                if table=="movements":
                    columns=["id","file_id","from_location","to_location","forwarded_by","receiving_officer","action","forwarded_at","acknowledged_at","status","remarks"]
                    rows=src.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY id").fetchall()
                else:
                    raise
            if not rows:
                continue
            marks=", ".join(["?"]*len(columns))
            # Use the wrapper so ? becomes %s for Postgres.
            sql=f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({marks}) ON CONFLICT DO NOTHING"
            for row in rows:
                dst.execute(sql, tuple(row[c] for c in columns))
        # Keep PostgreSQL SERIAL sequences ahead of the imported IDs.
        for table in ("users","files","movements","audit_logs"):
            dst.execute(f"SELECT setval(pg_get_serial_sequence('{table}','id'), COALESCE((SELECT MAX(id) FROM {table}), 1), true)")
        dst.commit()
    finally:
        dst.close(); src.close()

def user_count():
    c=db()
    n=c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    c.close()
    return n

def current_user():
    uid=session.get("user_id")
    if not uid:
        return None
    c=db()
    u=c.execute("SELECT * FROM users WHERE id=? AND active=1",(uid,)).fetchone()
    c.close()
    return u

@app.context_processor
def inject_user():
    return {"current_user": current_user()}

def login_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        if not current_user():
            return redirect(url_for("login",next=request.path))
        return view(*args,**kwargs)
    return wrapped

def admin_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        u=current_user()
        if not u:
            return redirect(url_for("login",next=request.path))
        if u["role"]!="Administrator":
            flash("Administrator access is required.","error")
            return redirect(url_for("dashboard"))
        return view(*args,**kwargs)
    return wrapped

def official_name():
    u=current_user()
    return u["full_name"] if u else ""

def role_is(role):
    u=current_user()
    return bool(u and u["role"] == role)

def can_receive_register():
    # Supporting Staff are the primary registry assistants for incoming LGI files.
    # Administrator and Zonal Inspector may also register a file when necessary.
    u=current_user()
    return bool(u and u["role"] in ("Administrator", "Zonal Inspector", "Supporting Staff"))

def can_operate_file_movement():
    # Only the Administrator or Zonal Inspector controls forwarding/returning.
    # Supporting Staff register incoming files and later confirm physical delivery.
    u=current_user()
    return bool(u and u["role"] in ("Administrator", "Zonal Inspector"))

def supporting_staff_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        if not current_user():
            return redirect(url_for("login",next=request.path))
        if current_user()["role"] != "Supporting Staff":
            flash("This action is reserved for Supporting Staff responsible for physical file delivery.","error")
            return redirect(url_for("detail",file_id=kwargs.get("file_id","")))
        return view(*args,**kwargs)
    return wrapped


def registry_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        if not current_user():
            return redirect(url_for("login",next=request.path))
        if not can_receive_register():
            flash("Only the Administrator, Zonal Inspector or Supporting Staff may register incoming LGI files.","error")
            return redirect(url_for("dashboard"))
        return view(*args,**kwargs)
    return wrapped

def movement_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        if not current_user():
            return redirect(url_for("login",next=request.path))
        if not can_operate_file_movement():
            flash("Only the Administrator or Zonal Inspector may forward or return files. Supporting Staff register incoming files and confirm physical delivery.","error")
            return redirect(url_for("dashboard"))
        return view(*args,**kwargs)
    return wrapped

def next_file_id():
    c=db()
    n=c.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
    c.close()
    return f"KZO-FM-{datetime.now().year}-{n+1:04d}"

@app.route("/login",methods=["GET","POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard"))
    if request.method=="POST":
        username=request.form.get("username","").strip()
        password=request.form.get("password","")
        c=db()
        u=c.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
        c.close()
        if u and u["active"] and check_password_hash(u["password_hash"],password):
            session.clear()
            session["user_id"]=u["id"]
            session["username"]=u["username"]
            session["full_name"]=u["full_name"]
            session["role"]=u["role"]
            nxt=request.args.get("next") or request.form.get("next") or url_for("dashboard")
            return redirect(nxt)
        flash("Invalid username or password, or the account is inactive.","error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.","success")
    return redirect(url_for("login"))

@app.route("/setup",methods=["GET","POST"])
def setup():
    if user_count()>0:
        flash("Initial setup has already been completed.","error")
        return redirect(url_for("login"))
    if request.method=="POST":
        full_name=request.form.get("full_name","").strip()
        username=request.form.get("username","").strip()
        password=request.form.get("password","")
        confirm=request.form.get("confirm_password","")
        if not full_name or not username or not password:
            flash("All required fields must be completed.","error")
        elif len(password)<8:
            flash("Password must be at least 8 characters.","error")
        elif password!=confirm:
            flash("Passwords do not match.","error")
        else:
            c=db()
            c.execute("""INSERT INTO users
                (full_name,username,password_hash,role,office,lga,active,created_at)
                VALUES(?,?,?,?,?,?,1,?)""",
                (full_name,username,generate_password_hash(password),
                 "Administrator","Katsina Zonal Office","",now()))
            c.commit()
            c.close()
            flash("Administrator account created. Please log in.","success")
            return redirect(url_for("login"))
    return render_template("setup.html")

@app.route("/users",methods=["GET","POST"])
@admin_required
def users():
    if request.method=="POST":
        full_name=request.form.get("full_name","").strip()
        username=request.form.get("username","").strip()
        password=request.form.get("password","")
        role=request.form.get("role","").strip()
        office=request.form.get("office","").strip()
        lga=request.form.get("lga","").strip()
        if not full_name or not username or not password or role not in ROLES:
            flash("Full name, username, password and valid role are required.","error")
        elif len(password)<8:
            flash("Password must be at least 8 characters.","error")
        else:
            c=db()
            try:
                c.execute("""INSERT INTO users
                    (full_name,username,password_hash,role,office,lga,active,created_at)
                    VALUES(?,?,?,?,?,?,1,?)""",
                    (full_name,username,generate_password_hash(password),
                     role,office,lga,now()))
                c.commit()
                flash(f"{full_name} account created successfully.","success")
            except Exception as e:
                if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                    flash("That username already exists.","error")
                else:
                    raise
            finally:
                c.close()
        return redirect(url_for("users"))
    c=db()
    rows=c.execute("SELECT * FROM users ORDER BY full_name").fetchall()
    c.close()
    return render_template("users.html",users=rows,roles=ROLES,lgas=LGAS)

@app.route("/users/<int:user_id>/toggle",methods=["POST"])
@admin_required
def toggle_user(user_id):
    if user_id==current_user()["id"]:
        flash("You cannot deactivate your own account.","error")
        return redirect(url_for("users"))
    c=db()
    c.execute("UPDATE users SET active=CASE WHEN active=1 THEN 0 ELSE 1 END WHERE id=?",(user_id,))
    c.commit()
    c.close()
    flash("Account status updated.","success")
    return redirect(url_for("users"))

@app.route("/")
@login_required
def dashboard():
    c=db()
    total=c.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    received=c.execute("SELECT COUNT(*) FROM files WHERE status='Received'").fetchone()[0]
    forwarded=c.execute("SELECT COUNT(*) FROM files WHERE status='Forwarded'").fetchone()[0]
    submitted=c.execute("SELECT COUNT(*) FROM files WHERE status='Submitted'").fetchone()[0]
    acknowledged=c.execute("SELECT COUNT(*) FROM files WHERE status='Acknowledged'").fetchone()[0]
    returned=c.execute("SELECT COUNT(*) FROM files WHERE status='Returned'").fetchone()[0]
    stats={"total":total,"received":received,"forwarded":forwarded,"submitted":submitted,"ack":acknowledged,
           "returned":returned,"Total":total,"Received":received,"Forwarded":forwarded,
           "Submitted":submitted,"Acknowledged":acknowledged,"Returned":returned}
    branch_counts={}
    for branch in BRANCHES:
        branch_counts[branch]=c.execute(
            "SELECT COUNT(*) FROM files WHERE current_location=?",(branch,)).fetchone()[0]
    branches=[(branch,branch_counts[branch]) for branch in BRANCHES]
    recent=c.execute("SELECT * FROM files ORDER BY id DESC LIMIT 8").fetchall()
    c.close()
    return render_template("dashboard.html",stats=stats,branches=branches,
                           branch_counts=branch_counts,recent=recent)

@app.route("/files")
@login_required
def files_page():
    q=request.args.get("q","").strip()
    status=request.args.get("status","").strip()
    branch=request.args.get("branch","").strip()
    c=db()
    sql="SELECT * FROM files WHERE 1=1"; args=[]
    if q:
        sql += """ AND (file_id LIKE ? OR title LIKE ? OR reference_no LIKE ?
                    OR lga LIKE ? OR lgi_name LIKE ? OR current_location LIKE ?)"""
        args += [f"%{q}%"]*6
    if status:
        sql+=" AND status=?"; args.append(status)
    if branch:
        sql+=" AND current_location=?"; args.append(branch)
    sql+=" ORDER BY id DESC"
    rows=c.execute(sql,args).fetchall()
    c.close()
    return render_template("files.html",rows=rows,q=q,status=status,
                           branch=branch,branches=BRANCHES)

@app.route("/receive",methods=["GET","POST"])
@registry_required
def receive():
    if request.method=="POST":
        title=request.form.get("title","").strip()
        if not title:
            flash("File/document title is required.","error")
            return redirect(url_for("receive"))
        t=now(); fid=next_file_id(); attachment=None
        uploaded=request.files.get("attachment")
        if uploaded and uploaded.filename:
            attachment=f"{fid}_{os.path.basename(uploaded.filename)}"
            uploaded.save(os.path.join(UPLOADS,attachment))
        official=official_name()
        c=db()
        c.execute("""INSERT INTO files
        (file_id,title,reference_no,lga,lgi_name,received_by,received_at,priority,
         description,attachment,status,current_location,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (fid,title,request.form.get("reference_no"),request.form["lga"],
         request.form.get("lgi_name"),official,t,request.form.get("priority","Normal"),
         request.form.get("description"),attachment,"Received",
         "Katsina Zonal Office",t))
        c.execute("""INSERT INTO audit_logs
        (file_id,action,official,details,created_at) VALUES(?,?,?,?,?)""",
        (fid,"FILE RECEIVED",official,"Received from "+request.form["lga"],t))
        c.commit(); c.close()
        flash(fid+" registered successfully.","success")
        return redirect(url_for("detail",file_id=fid))
    return render_template("receive.html",lgas=LGAS,priorities=PRIORITIES)

@app.route("/file/<file_id>")
@login_required
def detail(file_id):
    c=db()
    f=c.execute("SELECT * FROM files WHERE file_id=?",(file_id,)).fetchone()
    if not f:
        c.close(); return "File not found",404
    movements=c.execute("SELECT * FROM movements WHERE file_id=? ORDER BY id DESC",(file_id,)).fetchall()
    audit=c.execute("SELECT * FROM audit_logs WHERE file_id=? ORDER BY id DESC",(file_id,)).fetchall()
    c.close()
    return render_template("detail.html",f=f,movements=movements,audit=audit,branches=BRANCHES)

@app.route("/forward/<file_id>",methods=["POST"])
@movement_required
def forward(file_id):
    t=now(); c=db()
    f=c.execute("SELECT * FROM files WHERE file_id=?",(file_id,)).fetchone()
    if not f:
        c.close(); return "File not found",404
    official=official_name(); to=request.form["to_location"]
    c.execute("""INSERT INTO movements
    (file_id,from_location,to_location,forwarded_by,receiving_officer,
     action,forwarded_at,status,remarks) VALUES(?,?,?,?,?,?,?,?,?)""",
    (file_id,f["current_location"],to,official,request.form.get("receiving_officer"),
     request.form.get("action"),t,"Forwarded",request.form.get("remarks")))
    c.execute("UPDATE files SET current_location=?,status='Forwarded' WHERE file_id=?",(to,file_id))
    c.execute("""INSERT INTO audit_logs
    (file_id,action,official,details,created_at) VALUES(?,?,?,?,?)""",
    (file_id,"FILE FORWARDED",official,f"{f['current_location']} → {to}",t))
    c.commit(); c.close()
    flash(f"{file_id} forwarded to {to}.","success")
    return redirect(url_for("detail",file_id=file_id))

@app.route("/ack/<file_id>",methods=["POST"])
@supporting_staff_required
def acknowledge(file_id):
    # This is a physical-delivery confirmation by the Supporting Staff member.
    # It confirms to the Administrator/Zonal Inspector that the file was physically
    # submitted to the selected Secretariat branch; it is not a branch receipt.
    t=now(); official=official_name(); c=db()
    m=c.execute("""SELECT * FROM movements WHERE file_id=? AND status='Forwarded'
                   ORDER BY id DESC LIMIT 1""",(file_id,)).fetchone()
    if not m:
        c.close(); flash("No pending forwarded file is awaiting physical-submission confirmation.","error")
        return redirect(url_for("detail",file_id=file_id))
    c.execute("""UPDATE movements SET status='Submitted', submitted_at=?, submitted_by=?,
                 acknowledged_at=? WHERE id=?""",
              (t,official,t,m["id"]))
    c.execute("UPDATE files SET status='Submitted' WHERE file_id=?",(file_id,))
    c.execute("""INSERT INTO audit_logs
    (file_id,action,official,details,created_at) VALUES(?,?,?,?,?)""",
    (file_id,"PHYSICAL FILE SUBMITTED",official,
     f"Physical file submitted to {m['to_location']}",t))
    c.commit(); c.close()
    flash(f"Physical submission of {file_id} to {m['to_location']} confirmed.","success")
    return redirect(url_for("detail",file_id=file_id))

@app.route("/return/<file_id>",methods=["POST"])
@movement_required
def return_file(file_id):
    t=now(); official=official_name(); c=db()
    f=c.execute("SELECT * FROM files WHERE file_id=?",(file_id,)).fetchone()
    if not f:
        c.close(); return "File not found",404
    c.execute("""UPDATE files SET current_location='Katsina Zonal Office',
                 status='Returned' WHERE file_id=?""",(file_id,))
    c.execute("""INSERT INTO movements
    (file_id,from_location,to_location,forwarded_by,action,forwarded_at,status,remarks)
    VALUES(?,?,?,?,?,?,?,?)""",
    (file_id,f["current_location"],"Katsina Zonal Office",official,
     "Returned",t,"Returned",request.form.get("remarks")))
    c.execute("""INSERT INTO audit_logs
    (file_id,action,official,details,created_at) VALUES(?,?,?,?,?)""",
    (file_id,"FILE RETURNED",official,
     request.form.get("remarks") or "Returned to Zonal Office",t))
    c.commit(); c.close()
    flash("File returned to Zonal Office.","success")
    return redirect(url_for("detail",file_id=file_id))

@app.route("/download/<name>")
@login_required
def download(name):
    return send_from_directory(UPLOADS,name,as_attachment=True)

init_db()
migrate_bundled_sqlite_to_postgres_if_empty()

if __name__=="__main__":
    app.run(debug=True)
