from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session
import os
import csv
import io
import json
import re
import psycopg
from psycopg.rows import dict_row
from psycopg.errors import UniqueViolation
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

BASE=os.path.dirname(os.path.abspath(__file__))
UPLOADS=os.path.join(BASE,"uploads")
os.makedirs(UPLOADS,exist_ok=True)

app=Flask(__name__)
app.secret_key=os.environ.get("FILETRACK_SECRET","change-this-secret-key")

LGAS=["Katsina A","Katsina B","Batagarawa","Kaita","Jibia","Rimi","Charanchi"]
BRANCHES=["CIM","CW&HS","CDS"]
PRIORITIES=["Normal","High","Urgent"]
ROLES=["Administrator","Zonal Inspector","LGI Officer","Branch Official","Supporting Staff"]

def db():
    database_url=os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not configured.")

    # Render PostgreSQL external connections use SSL. Add this only when
    # the supplied DATABASE_URL does not already specify an sslmode.
    if "sslmode=" not in database_url.lower():
        separator = "&" if "?" in database_url else "?"
        database_url += separator + "sslmode=require"

    last_error = None
    for attempt in range(3):
        try:
            return psycopg.connect(
                database_url,
                row_factory=dict_row,
                connect_timeout=10,
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=3,
            )
        except psycopg.OperationalError as exc:
            last_error = exc
            if attempt < 2:
                import time
                time.sleep(1)

    raise last_error



@app.after_request
def integrate_inspection_ui(response):
    """Server-side integration of Inspection into the existing FileTrack UI."""
    try:
        if not session.get("user_id") or "text/html" not in (response.content_type or ""):
            return response
        if request.path in ("/login", "/setup") or request.path.startswith("/admin/db-inspection"):
            return response
        html=response.get_data(as_text=True)

        # Show a clear confirmation after a Supporting Staff member successfully
        # confirms physical delivery of a file. The detail template belongs to
        # the core FileTrack UI, so this enhancement avoids replacing it.
        if request.args.get("submitted") == "1" and request.path.startswith("/file/"):
            confirmation = (
                '<div data-filetrack-submission-confirmed="1" style="margin:18px 0;padding:16px 18px;'
                'border:1px solid #86efac;border-left:5px solid #16a34a;border-radius:12px;'
                'background:#f0fdf4;color:#166534;font-family:Arial,sans-serif;">'
                '<div style="font-weight:800;font-size:17px;margin-bottom:4px;">'
                '✓ Physical Submission Confirmed</div>'
                '<div>The file has been recorded as physically submitted to the selected Secretariat branch.</div>'
                '</div>'
            )
            html = html.replace('</main>', confirmation + '</main>', 1) if '</main>' in html else confirmation + html
            confirmation_script = (
                '<script>document.addEventListener("DOMContentLoaded",function(){'
                'document.querySelectorAll("button,input[type=submit]").forEach(function(el){'
                'var t=(el.innerText||el.value||"").trim().toLowerCase();'
                'if(t.indexOf("confirm physical submission")!==-1){'
                'el.disabled=true;el.style.opacity=".65";el.style.cursor="not-allowed";'
                'if(el.tagName.toLowerCase()==="input")el.value="✓ Physical Submission Confirmed";'
                'else el.innerText="✓ Physical Submission Confirmed";}});});</script>'
            )
            html = html.replace('</body>', confirmation_script + '</body>', 1) if '</body>' in html else html + confirmation_script

        # Zonal Inspector/Admin live PPA clearance panel on the main dashboard.
        # It is intentionally read-only and refreshes from PostgreSQL every 10 seconds.
        if request.path=="/" and session.get("role") in ("Administrator","Zonal Inspector") and 'data-filetrack-live-clearance="1"' not in html:
            live_card='''\n<section data-filetrack-live-clearance="1" style="margin:24px 0;padding:22px 24px;border:1px solid #dfe8e4;border-radius:16px;background:#fff;box-shadow:0 8px 24px rgba(15,81,61,.07);">\n  <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">\n    <div>\n      <div style="font-size:12px;font-weight:800;letter-spacing:.08em;color:#12865f;text-transform:uppercase;margin-bottom:6px;">LIVE FIELD MONITORING</div>\n      <h2 style="margin:0 0 6px;color:#17262f;font-size:24px;">PPA Clearance Dashboard</h2>\n      <p style="margin:0;color:#6b7c84;">Real-time progress reported by assigned Supporting Staff. Cleared = latest status is Present.</p>\n    </div>\n    <div id="ft-live-updated" style="font-size:12px;color:#6b7280;">Loading…</div>\n  </div>\n  <div id="ft-live-summary" style="margin-top:16px;">\n    <div style="padding:14px;border:1px solid #e5e7eb;border-radius:10px;color:#6b7280;">Loading current PPA clearance status…</div>\n  </div>\n</section>\n<script>\n(function(){\n  function esc(v){return String(v==null?'':v).replace(/[&<>\"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c];});}\n  function badge(text,bg,fg){return '<span style="display:inline-block;padding:5px 9px;border-radius:999px;background:'+bg+';color:'+fg+';font-weight:800;font-size:12px;">'+esc(text)+'</span>';}\n  async function refresh(){\n    var box=document.getElementById('ft-live-summary'),stamp=document.getElementById('ft-live-updated');\n    if(!box)return;\n    try{\n      var r=await fetch('/inspection/live-dashboard',{cache:'no-store'});\n      var d=await r.json();\n      if(!r.ok) throw new Error(d.error||'Unable to load live dashboard');\n      var rows=d.ppas||[];\n      if(!rows.length){box.innerHTML='<div style="padding:14px;border:1px solid #e5e7eb;border-radius:10px;color:#6b7280;">No active PPA assignments yet.</div>';}\n      else{\n        var html='<div style="overflow:auto"><table style="width:100%;border-collapse:collapse;min-width:820px"><thead><tr>'+\n          '<th style="padding:10px;text-align:left;border-bottom:1px solid #e5e7eb">PPA</th>'+\n          '<th style="padding:10px;text-align:left;border-bottom:1px solid #e5e7eb">LGA</th>'+\n          '<th style="padding:10px;text-align:left;border-bottom:1px solid #e5e7eb">Assigned Staff</th>'+\n          '<th style="padding:10px;text-align:center;border-bottom:1px solid #e5e7eb">Total</th>'+\n          '<th style="padding:10px;text-align:center;border-bottom:1px solid #e5e7eb">Cleared</th>'+\n          '<th style="padding:10px;text-align:center;border-bottom:1px solid #e5e7eb">Not Cleared</th>'+\n          '<th style="padding:10px;text-align:left;border-bottom:1px solid #e5e7eb">Last Update</th>'+\n          '</tr></thead><tbody>';\n        rows.forEach(function(x){\n          var pct=x.total?Math.round((x.cleared/x.total)*100):0;\n          html+='<tr>'+\n            '<td style="padding:10px;border-bottom:1px solid #f0f2f4;font-weight:700">'+esc(x.ppa_name)+'</td>'+\n            '<td style="padding:10px;border-bottom:1px solid #f0f2f4">'+esc(x.lga)+'</td>'+\n            '<td style="padding:10px;border-bottom:1px solid #f0f2f4">'+esc(x.staff_name)+'</td>'+\n            '<td style="padding:10px;text-align:center;border-bottom:1px solid #f0f2f4">'+esc(x.total)+'</td>'+\n            '<td style="padding:10px;text-align:center;border-bottom:1px solid #f0f2f4">'+badge(x.cleared+' ('+pct+'%)','#dcfce7','#166534')+'</td>'+\n            '<td style="padding:10px;text-align:center;border-bottom:1px solid #f0f2f4">'+badge(x.not_cleared,'#fee2e2','#991b1b')+'</td>'+\n            '<td style="padding:10px;border-bottom:1px solid #f0f2f4;font-size:12px;color:#6b7280">'+esc(x.last_update||'Not yet updated')+'</td>'+\n            '</tr>';\n        });\n        html+='</tbody></table></div>';\n        box.innerHTML=html;\n      }\n      stamp.textContent='Updated: '+esc(d.updated_at)+' • auto-refresh 10s';\n    }catch(e){box.innerHTML='<div style="padding:14px;border:1px solid #fecaca;border-radius:10px;background:#fef2f2;color:#991b1b;">Live clearance data could not be loaded. The rest of the dashboard remains available.</div>';stamp.textContent='Update unavailable';}\n  }\n  refresh();\n  setInterval(refresh,10000);\n})();\n</script>\n'''
            m_live=re.search(r'(<h1[^>]*>\s*File Movement Dashboard\s*</h1>)',html,flags=re.I)
            if m_live:
                pos=m_live.end(); html=html[:pos]+live_card+html[pos:]
            else:
                html=html.replace('</main>',live_card+'</main>',1)

        if 'data-filetrack-inspection="1"' in html:
            response.set_data(html)
            return response

        nav_link='<a href="/inspections" data-filetrack-inspection="1" style="margin-left:18px;font-weight:700;text-decoration:none;color:inherit;">Inspection</a>'
        inspection_card='''
<section data-filetrack-inspection="1" style="margin:24px 0;padding:22px 24px;border:1px solid #dfe8e4;border-radius:16px;background:#fff;box-shadow:0 8px 24px rgba(15,81,61,.07);">
  <div style="font-size:12px;font-weight:800;letter-spacing:.08em;color:#12865f;text-transform:uppercase;margin-bottom:6px;">FIELD MONITORING</div>
  <h2 style="margin:0 0 7px;color:#17262f;font-size:24px;">Inspection &amp; PPA Monitoring</h2>
  <p style="margin:0 0 15px;color:#6b7c84;">Manage PPA assignments, Corps Member records and attendance inspections.</p>
  <a href="/inspections" style="display:inline-block;background:#129b68;color:#fff;padding:11px 17px;border-radius:10px;text-decoration:none;font-weight:700;">Open Inspection Module -&gt;</a>
</section>'''
        import re
        html2=re.sub(r'(<a\b[^>]*>\s*Officials\s*</a>)', r'\1'+nav_link, html, count=1, flags=re.I)
        if html2==html:
            html2=html.replace('</nav>',nav_link+'</nav>',1)
        if html2==html:
            html2=html.replace('</header>',nav_link+'</header>',1)
        html=html2
        if request.path=="/" and "Inspection &amp; PPA Monitoring" not in html:
            m=re.search(r'(<h1[^>]*>\s*File Movement Dashboard\s*</h1>)',html,flags=re.I)
            if m:
                pos=m.end(); html=html[:pos]+inspection_card+html[pos:]
            else:
                html=html.replace('</main>',inspection_card+'</main>',1)
        response.set_data(html)
        response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"]="no-cache"
    except Exception:
        pass
    return response

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def init_db():
    """Create/upgrade the PostgreSQL schema used by FileTrack."""
    with db() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS files(
          id BIGSERIAL PRIMARY KEY,
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
          id BIGSERIAL PRIMARY KEY,
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
          id BIGSERIAL PRIMARY KEY,
          file_id TEXT NOT NULL,
          action TEXT NOT NULL,
          official TEXT,
          details TEXT,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users(
          id BIGSERIAL PRIMARY KEY,
          full_name TEXT NOT NULL,
          username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL,
          office TEXT,
          lga TEXT,
          active INTEGER DEFAULT 1,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS inspections(
          id BIGSERIAL PRIMARY KEY,
          inspection_id TEXT UNIQUE NOT NULL,
          lga TEXT NOT NULL,
          ppa_employer TEXT,
          corps_member TEXT,
          subject TEXT NOT NULL,
          findings TEXT NOT NULL,
          recommendations TEXT,
          inspected_by TEXT NOT NULL,
          inspected_at TEXT NOT NULL,
          status TEXT DEFAULT 'Submitted to ZI'
        );

        CREATE TABLE IF NOT EXISTS reports(
          id BIGSERIAL PRIMARY KEY,
          report_id TEXT UNIQUE NOT NULL,
          lga TEXT NOT NULL,
          report_type TEXT NOT NULL,
          ppa_employer TEXT,
          corps_member TEXT,
          subject TEXT NOT NULL,
          report_body TEXT NOT NULL,
          issued_by TEXT NOT NULL,
          issued_at TEXT NOT NULL,
          status TEXT DEFAULT 'Issued'
        );

        CREATE TABLE IF NOT EXISTS ppa_establishments(
          id BIGSERIAL PRIMARY KEY,
          name TEXT NOT NULL,
          lga TEXT NOT NULL,
          active INTEGER DEFAULT 1,
          created_by TEXT,
          created_at TEXT NOT NULL,
          UNIQUE(name,lga)
        );

        CREATE TABLE IF NOT EXISTS corps_members(
          id BIGSERIAL PRIMARY KEY,
          state_code TEXT UNIQUE NOT NULL,
          full_name TEXT NOT NULL,
          gender TEXT,
          discipline TEXT,
          ppa_id BIGINT REFERENCES ppa_establishments(id) ON DELETE SET NULL,
          batch TEXT,
          stream TEXT,
          phone TEXT,
          status TEXT DEFAULT 'Active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS inspection_assignments(
          id BIGSERIAL PRIMARY KEY,
          ppa_id BIGINT NOT NULL REFERENCES ppa_establishments(id) ON DELETE CASCADE,
          supporting_staff_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
          assigned_by BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
          assigned_at TEXT NOT NULL,
          status TEXT DEFAULT 'Active'
        );

        CREATE UNIQUE INDEX IF NOT EXISTS ux_active_inspection_ppa
          ON inspection_assignments(ppa_id) WHERE status='Active';

        CREATE TABLE IF NOT EXISTS inspection_records(
          id BIGSERIAL PRIMARY KEY,
          inspection_id TEXT UNIQUE NOT NULL,
          corps_member_id BIGINT NOT NULL REFERENCES corps_members(id) ON DELETE RESTRICT,
          ppa_id BIGINT NOT NULL REFERENCES ppa_establishments(id) ON DELETE RESTRICT,
          inspected_by BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
          attendance_status TEXT NOT NULL,
          query_issued INTEGER DEFAULT 0,
          other_reason TEXT,
          remarks TEXT,
          inspected_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS inspection_submissions(
          id BIGSERIAL PRIMARY KEY,
          ppa_id BIGINT NOT NULL REFERENCES ppa_establishments(id) ON DELETE RESTRICT,
          supporting_staff_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
          submitted_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'Submitted',
          reviewed_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
          reviewed_at TEXT,
          review_comment TEXT,
          total_count INTEGER DEFAULT 0,
          present_count INTEGER DEFAULT 0,
          absent_count INTEGER DEFAULT 0,
          pending_count INTEGER DEFAULT 0,
          other_count INTEGER DEFAULT 0,
          snapshot JSONB NOT NULL DEFAULT '[]'::jsonb
        );

        ALTER TABLE movements ADD COLUMN IF NOT EXISTS submitted_by TEXT;
        ALTER TABLE movements ADD COLUMN IF NOT EXISTS submitted_at TEXT;
        """)

def user_count():
    c=db()
    n=c.execute("SELECT COUNT(*) FROM users").fetchone()["count"]
    c.close()
    return n

def current_user():
    uid=session.get("user_id")
    if not uid:
        return None
    c=db()
    u=c.execute("SELECT * FROM users WHERE id=%s AND active=1",(uid,)).fetchone()
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


def lgi_report_only(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        if not current_user(): return redirect(url_for("login",next=request.path))
        if current_user()["role"] == "LGI Officer":
            flash("LGI Officers have report-only access. Reports are issued by the Zonal Inspector for their assigned LGA.","error")
            return redirect(url_for("reports"))
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

def next_inspection_id():
    c=db(); n=c.execute("SELECT COUNT(*) FROM inspections").fetchone()["count"]; c.close(); return f"KZO-INSP-{datetime.now().year}-{n+1:04d}"

def next_report_id():
    c=db(); n=c.execute("SELECT COUNT(*) FROM reports").fetchone()["count"]; c.close(); return f"KZO-RPT-{datetime.now().year}-{n+1:04d}"

def inspection_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        if not current_user(): return redirect(url_for("login",next=request.path))
        if current_user()["role"] != "Supporting Staff":
            flash("Inspection is assigned to Supporting Staff. LGI Officers receive Zonal reports instead.","error"); return redirect(url_for("dashboard"))
        return view(*args,**kwargs)
    return wrapped

def report_management_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        if not current_user(): return redirect(url_for("login",next=request.path))
        if current_user()["role"] not in ("Administrator", "Zonal Inspector"):
            flash("Only the Administrator or Zonal Inspector may issue reports to LGI Officers.","error"); return redirect(url_for("dashboard"))
        return view(*args,**kwargs)
    return wrapped

@app.route("/health")
def health():
    try:
        with db() as c:
            row = c.execute(
                "SELECT current_database() AS database_name, current_user AS database_user"
            ).fetchone()
        return {
            "status": "ok",
            "database": row["database_name"],
            "user": row["database_user"],
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}, 503


@app.route("/login",methods=["GET","POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard"))
    if request.method=="POST":
        username=request.form.get("username","").strip()
        password=request.form.get("password","")
        c=db()
        u=c.execute("SELECT * FROM users WHERE username=%s",(username,)).fetchone()
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
                VALUES(%s,%s,%s,%s,%s,%s,1,%s)""",
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
                    VALUES(%s,%s,%s,%s,%s,%s,1,%s)""",
                    (full_name,username,generate_password_hash(password),
                     role,office,lga,now()))
                c.commit()
                flash(f"{full_name} account created successfully.","success")
            except UniqueViolation:
                flash("That username already exists.","error")
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
    c.execute("UPDATE users SET active=CASE WHEN active=1 THEN 0 ELSE 1 END WHERE id=%s",(user_id,))
    c.commit()
    c.close()
    flash("Account status updated.","success")
    return redirect(url_for("users"))

@app.route("/")
@login_required
def dashboard():
    u=current_user(); c=db()
    if u["role"] == "LGI Officer":
        reports=c.execute("SELECT * FROM reports WHERE lga=%s ORDER BY id DESC LIMIT 20",(u["lga"],)).fetchall(); c.close()
        return render_template("dashboard.html",lgi_reports=reports)
    total=c.execute("SELECT COUNT(*) FROM files").fetchone()["count"]; received=c.execute("SELECT COUNT(*) FROM files WHERE status='Received'").fetchone()["count"]; forwarded=c.execute("SELECT COUNT(*) FROM files WHERE status='Forwarded'").fetchone()["count"]; submitted=c.execute("SELECT COUNT(*) FROM files WHERE status='Submitted'").fetchone()["count"]; acknowledged=c.execute("SELECT COUNT(*) FROM files WHERE status='Acknowledged'").fetchone()["count"]; returned=c.execute("SELECT COUNT(*) FROM files WHERE status='Returned'").fetchone()["count"]
    stats={"total":total,"received":received,"forwarded":forwarded,"submitted":submitted,"ack":acknowledged,"returned":returned,"Total":total,"Received":received,"Forwarded":forwarded,"Submitted":submitted,"Acknowledged":acknowledged,"Returned":returned}
    branch_counts={b:c.execute("SELECT COUNT(*) FROM files WHERE current_location=%s",(b,)).fetchone()["count"] for b in BRANCHES}; branches=[(b,branch_counts[b]) for b in BRANCHES]; recent=c.execute("SELECT * FROM files ORDER BY id DESC LIMIT 8").fetchall(); inspection_count=c.execute("SELECT COUNT(*) FROM inspections").fetchone()["count"]; pending_inspections=c.execute("SELECT COUNT(*) FROM inspections WHERE status='Submitted to ZI'").fetchone()["count"]; report_count=c.execute("SELECT COUNT(*) FROM reports").fetchone()["count"]; c.close()
    return render_template("dashboard.html",stats=stats,branches=branches,branch_counts=branch_counts,recent=recent,inspection_count=inspection_count,pending_inspections=pending_inspections,report_count=report_count)

@app.route("/files")
@login_required
@lgi_report_only
def files_page():
    q=request.args.get("q","").strip()
    status=request.args.get("status","").strip()
    branch=request.args.get("branch","").strip()
    c=db()
    sql="SELECT * FROM files WHERE 1=1"; args=[]
    if q:
        sql += """ AND (file_id LIKE %s OR title LIKE %s OR reference_no LIKE %s
                    OR lga LIKE %s OR lgi_name LIKE %s OR current_location LIKE %s)"""
        args += [f"%{q}%"]*6
    if status:
        sql+=" AND status=%s"; args.append(status)
    if branch:
        sql+=" AND current_location=%s"; args.append(branch)
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
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (fid,title,request.form.get("reference_no"),request.form["lga"],
         request.form.get("lgi_name"),official,t,request.form.get("priority","Normal"),
         request.form.get("description"),attachment,"Received",
         "Katsina Zonal Office",t))
        c.execute("""INSERT INTO audit_logs
        (file_id,action,official,details,created_at) VALUES(%s,%s,%s,%s,%s)""",
        (fid,"FILE RECEIVED",official,"Received from "+request.form["lga"],t))
        c.commit(); c.close()
        flash(fid+" registered successfully.","success")
        return redirect(url_for("detail",file_id=fid))
    return render_template("receive.html",lgas=LGAS,priorities=PRIORITIES)

@app.route("/file/<file_id>")
@login_required
@lgi_report_only
def detail(file_id):
    c=db()
    f=c.execute("SELECT * FROM files WHERE file_id=%s",(file_id,)).fetchone()
    if not f:
        c.close(); return "File not found",404
    movements=c.execute("SELECT * FROM movements WHERE file_id=%s ORDER BY id DESC",(file_id,)).fetchall()
    audit=c.execute("SELECT * FROM audit_logs WHERE file_id=%s ORDER BY id DESC",(file_id,)).fetchall()
    c.close()
    return render_template("detail.html",f=f,movements=movements,audit=audit,branches=BRANCHES)

@app.route("/forward/<file_id>",methods=["POST"])
@movement_required
def forward(file_id):
    t=now(); c=db()
    f=c.execute("SELECT * FROM files WHERE file_id=%s",(file_id,)).fetchone()
    if not f:
        c.close(); return "File not found",404
    official=official_name(); to=request.form["to_location"]
    c.execute("""INSERT INTO movements
    (file_id,from_location,to_location,forwarded_by,receiving_officer,
     action,forwarded_at,status,remarks) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
    (file_id,f["current_location"],to,official,request.form.get("receiving_officer"),
     request.form.get("action"),t,"Forwarded",request.form.get("remarks")))
    c.execute("UPDATE files SET current_location=%s,status='Forwarded' WHERE file_id=%s",(to,file_id))
    c.execute("""INSERT INTO audit_logs
    (file_id,action,official,details,created_at) VALUES(%s,%s,%s,%s,%s)""",
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
    m=c.execute("""SELECT * FROM movements WHERE file_id=%s AND status='Forwarded'
                   ORDER BY id DESC LIMIT 1""",(file_id,)).fetchone()
    if not m:
        c.close(); flash("No pending forwarded file is awaiting physical-submission confirmation.","error")
        return redirect(url_for("detail",file_id=file_id))
    c.execute("""UPDATE movements SET status='Submitted', submitted_at=%s, submitted_by=%s,
                 acknowledged_at=%s WHERE id=%s""",
              (t,official,t,m["id"]))
    c.execute("UPDATE files SET status='Submitted' WHERE file_id=%s",(file_id,))
    c.execute("""INSERT INTO audit_logs
    (file_id,action,official,details,created_at) VALUES(%s,%s,%s,%s,%s)""",
    (file_id,"PHYSICAL FILE SUBMITTED",official,
     f"Physical file submitted to {m['to_location']}",t))
    c.commit(); c.close()
    flash(f"Physical submission of {file_id} to {m['to_location']} confirmed.","success")
    return redirect(url_for("detail",file_id=file_id, submitted=1))

@app.route("/return/<file_id>",methods=["POST"])
@movement_required
def return_file(file_id):
    t=now(); official=official_name(); c=db()
    f=c.execute("SELECT * FROM files WHERE file_id=%s",(file_id,)).fetchone()
    if not f:
        c.close(); return "File not found",404
    c.execute("""UPDATE files SET current_location='Katsina Zonal Office',
                 status='Returned' WHERE file_id=%s""",(file_id,))
    c.execute("""INSERT INTO movements
    (file_id,from_location,to_location,forwarded_by,action,forwarded_at,status,remarks)
    VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
    (file_id,f["current_location"],"Katsina Zonal Office",official,
     "Returned",t,"Returned",request.form.get("remarks")))
    c.execute("""INSERT INTO audit_logs
    (file_id,action,official,details,created_at) VALUES(%s,%s,%s,%s,%s)""",
    (file_id,"FILE RETURNED",official,
     request.form.get("remarks") or "Returned to Zonal Office",t))
    c.commit(); c.close()
    flash("File returned to Zonal Office.","success")
    return redirect(url_for("detail",file_id=file_id))

def inspection_management_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        u=current_user()
        if not u:
            return redirect(url_for("login",next=request.path))
        if u["role"] not in ("Administrator","Zonal Inspector"):
            flash("Only the Administrator or Zonal Inspector may manage inspection assignments.","error")
            return redirect(url_for("dashboard"))
        return view(*args,**kwargs)
    return wrapped


def _norm_header(value):
    return "_".join(str(value or "").strip().lower().replace("/"," ").replace("-"," ").split())


def _read_corps_upload(upload):
    """Read CSV or XLSX upload and return normalized dictionaries.

    The NYSC source workbooks used by the Zonal Office have an Expected,
    Present and Absent sheet. For master Corps Member import we deliberately
    read the Expected sheet so Present/Absent sheets do not create duplicates.
    """
    filename=(upload.filename or "").lower()
    raw=upload.read()
    if filename.endswith(".csv"):
        text=raw.decode("utf-8-sig",errors="replace")
        return [{_norm_header(k): (v or "").strip() for k,v in row.items()} for row in csv.DictReader(io.StringIO(text))]
    if filename.endswith(".xlsx"):
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise RuntimeError("Excel upload requires openpyxl. Add openpyxl to requirements.txt and redeploy.")
        wb=load_workbook(io.BytesIO(raw),read_only=True,data_only=True)
        ws=(wb["Expected"] if "Expected" in wb.sheetnames else wb["All Corps Members"] if "All Corps Members" in wb.sheetnames else wb.active)
        values=list(ws.iter_rows(values_only=True))
        if not values:
            return []
        headers=[_norm_header(x) for x in values[0]]
        rows=[]
        for vals in values[1:]:
            row={headers[i]: ("" if i>=len(vals) or vals[i] is None else str(vals[i]).strip())
                 for i in range(len(headers)) if headers[i]}
            # Ignore completely blank rows (common in Absent/other worksheets).
            if any(row.values()):
                rows.append(row)
        return rows
    raise RuntimeError("Unsupported file type. Please upload CSV or XLSX.")


def _infer_lga_from_filename(filename):
    """Infer the LGA for the standard NYSC download filenames.

    A/C/unsuffixed filenames represent batches, not different LGAs:
    e.g. rimiC.xlsx, rimiA.xlsx and rimi.xlsx are all Rimi.
    Katsina is intentionally not inferred because the zone contains
    both Katsina A and Katsina B; the importer must be told which one.
    """
    base=os.path.splitext(os.path.basename(filename or ""))[0].strip().lower()
    base=re.sub(r"[_\-\s]*(?:a|b|c)$","",base)
    mapping={
        "batagarawa":"Batagarawa",
        "rimi":"Rimi",
        "kaita":"Kaita",
        "jibia":"Jibia",
        "charanchi":"Charanchi",
    }
    return mapping.get(base,"")


def _normalize_inspection_lga(value, component=""):
    """Normalize workbook LGA/component values to the seven zone LGAs."""
    v=str(value or "").strip().upper()
    comp=str(component or "").strip().upper()
    # The master zonal workbook stores both Katsina A and Katsina B rows as
    # LGA=KATSINA, while Component identifies the actual zonal LGA.
    if v in ("KATSINA", "KATSINA MAIN", "KATSINA METROPOLIS"):
        if comp in ("KATSINA A", "KATSINA B"):
            return comp.title()
        return ""
    mapping={
        "BATAGARAWA":"Batagarawa", "RIMI":"Rimi", "KAITA":"Kaita",
        "JIBIA":"Jibia", "CHARANCHI":"Charanchi",
        "KATSINA A":"Katsina A", "KATSINA B":"Katsina B"
    }
    return mapping.get(v, str(value or "").strip())


def _legacy_corps_fields(row, filename="", selected_lga=""):
    """Map both the Zonal master workbook and raw NYSC downloads."""
    state=_pick(row,"state_code","statecode","state code","state-code","code")

    name=_pick(row,"full_name","corps_member_name","corps member name","name","corps name")
    if not name:
        surname=_pick(row,"surname","last name","lastname")
        othernames=_pick(row,"othernames","other names","first name","firstname")
        name=" ".join(x for x in (surname,othernames) if x).strip()

    ppa=_pick(row,"ppa_establishment","ppa establishment","ppa / establishment",
              "ppa","ppa_employer","place_of_posting","place of posting",
              "employer","company","company name","establishment",
              "place of primary assignment")

    component=_pick(row,"component","zone component")
    raw_lga=_pick(row,"lga","local government","local government area","posted_lga","posted lga")
    lga=_normalize_inspection_lga(raw_lga,component)
    if not lga:
        fallback=(selected_lga or _infer_lga_from_filename(filename)).strip()
        lga=_normalize_inspection_lga(fallback,component) or fallback

    batch=_pick(row,"batch","batch year")
    if not batch and state:
        m=re.search(r"/(\d{2}[ABC])/?",state.upper())
        if m:
            batch=m.group(1)
    if batch:
        b=batch.strip().replace("_"," ")
        if re.fullmatch(r"[ABC]",b.upper()):
            batch=f"Batch_{b.upper()}"
        elif re.fullmatch(r"BATCH\s*[ABC]",b.upper()):
            batch="Batch_"+b[-1].upper()
        else:
            batch=batch.strip()

    return {
        "state":state,
        "name":name,
        "ppa":ppa,
        "lga":lga,
        "gender":_pick(row,"gender","sex"),
        "discipline":_pick(row,"discipline","course","qualification"),
        "batch":batch,
        "stream":_pick(row,"stream"),
        "phone":_pick(row,"phone","phone number","mobile","gsmno","gsm no","gsm no.","gsm"),
        "status":_pick(row,"status") or "Active",
    }


def _pick(row,*names):
    for name in names:
        key=_norm_header(name)
        if row.get(key): return str(row[key]).strip()
    return ""


def next_new_inspection_id():
    c=db(); n=c.execute("SELECT COUNT(*) FROM inspection_records").fetchone()["count"]; c.close()
    return f"KZO-INSP-{datetime.now().year}-{n+1:04d}"


@app.route("/inspections")
@login_required
def inspections():
    u=current_user()
    if u["role"] in ("Administrator","Zonal Inspector"):
        c=db()
        ppas=c.execute("""SELECT p.*, COUNT(cm.id) AS corps_count,
                    (SELECT COUNT(*) FROM inspection_assignments ia WHERE ia.ppa_id=p.id AND ia.status='Active') AS assigned
                    FROM ppa_establishments p LEFT JOIN corps_members cm ON cm.ppa_id=p.id
                    WHERE p.active=1 GROUP BY p.id ORDER BY p.lga,p.name""").fetchall()
        assignments=c.execute("""SELECT ia.*,p.name AS ppa_name,p.lga,u.full_name AS staff_name
                    FROM inspection_assignments ia JOIN ppa_establishments p ON p.id=ia.ppa_id
                    JOIN users u ON u.id=ia.supporting_staff_id
                    WHERE ia.status='Active' ORDER BY p.lga,p.name""").fetchall()
        staff=c.execute("SELECT id,full_name,username FROM users WHERE role='Supporting Staff' AND active=1 ORDER BY full_name").fetchall()
        recent=c.execute("""SELECT ir.*,cm.state_code,cm.full_name,p.name AS ppa_name,p.lga,u.full_name AS inspector_name
                    FROM inspection_records ir JOIN corps_members cm ON cm.id=ir.corps_member_id
                    JOIN ppa_establishments p ON p.id=ir.ppa_id JOIN users u ON u.id=ir.inspected_by
                    ORDER BY ir.id DESC LIMIT 30""").fetchall()
        c.close()
        return render_template("inspections.html",mode="management",ppas=ppas,assignments=assignments,staff=staff,recent=recent)
    if u["role"] == "Supporting Staff":
        c=db()
        assigned=c.execute("""SELECT p.id,p.name,p.lga,COUNT(cm.id)::int AS corps_count,
                    COUNT(cm.id) FILTER (WHERE lr.attendance_status='Present')::int AS present_count,
                    COUNT(cm.id) FILTER (WHERE lr.attendance_status='Absent')::int AS absent_count,
                    COUNT(cm.id) FILTER (WHERE lr.id IS NULL)::int AS pending_count
                    FROM inspection_assignments ia JOIN ppa_establishments p ON p.id=ia.ppa_id
                    LEFT JOIN corps_members cm ON cm.ppa_id=p.id AND cm.status='Active'
                    LEFT JOIN LATERAL (
                        SELECT ir.id,ir.attendance_status
                        FROM inspection_records ir
                        WHERE ir.corps_member_id=cm.id AND ir.ppa_id=p.id
                        ORDER BY ir.id DESC LIMIT 1
                    ) lr ON TRUE
                    WHERE ia.supporting_staff_id=%s AND ia.status='Active' AND p.active=1
                    GROUP BY p.id ORDER BY p.lga,p.name""",(u["id"],)).fetchall()
        mine=c.execute("""SELECT ir.*,cm.state_code,cm.full_name,p.name AS ppa_name,p.lga
                    FROM inspection_records ir JOIN corps_members cm ON cm.id=ir.corps_member_id
                    JOIN ppa_establishments p ON p.id=ir.ppa_id
                    WHERE ir.inspected_by=%s ORDER BY ir.id DESC LIMIT 50""",(u["id"],)).fetchall()
        c.close()
        return render_template("inspections.html",mode="staff",assigned=assigned,mine=mine)
    flash("Inspection access is not available to this role.","error")
    return redirect(url_for("dashboard"))


@app.route("/inspection/import",methods=["GET","POST"])
@inspection_management_required
def inspection_import():
    """Fast, PostgreSQL-safe Corps Member importer.

    The previous implementation performed several database round-trips for every
    row.  With a 2,000+ row zonal workbook that could exceed Gunicorn's request
    timeout.  This version validates rows in memory, bulk-creates missing PPAs,
    then performs batched PostgreSQL upserts for Corps Members.
    """
    if request.method == "POST":
        uploads=[u for u in request.files.getlist("corps_file") if u and u.filename]
        selected_lga=(request.form.get("lga") or "").strip()
        if not uploads:
            flash("Please select at least one CSV or XLSX file.","error")
            return redirect(url_for("inspection_import"))
        if selected_lga and selected_lga not in LGAS:
            flash("Please select a valid LGA.","error")
            return redirect(url_for("inspection_import"))

        try:
            # -------------------------------------------------------------
            # 1. Read and validate everything before opening the DB write path.
            # -------------------------------------------------------------
            valid=[]
            errors=0
            processed=0
            error_rows=[]

            for upload in uploads:
                filename=upload.filename
                try:
                    rows=_read_corps_upload(upload)
                except Exception as exc:
                    errors += 1
                    error_rows.append(f"{filename}: {exc}")
                    continue

                for idx,row in enumerate(rows,start=2):
                    fields=_legacy_corps_fields(row,filename,selected_lga)
                    processed += 1
                    state,name,ppa,lga=(fields["state"],fields["name"],fields["ppa"],fields["lga"])
                    missing=[]
                    if not state: missing.append("State Code")
                    if not name: missing.append("Name")
                    if not ppa: missing.append("PPA/Establishment")
                    if not lga: missing.append("LGA")
                    if missing:
                        errors += 1
                        error_rows.append(f"{filename} row {idx}: {', '.join(missing)} required")
                        continue
                    if lga not in LGAS:
                        errors += 1
                        error_rows.append(f"{filename} row {idx}: Invalid LGA '{lga}'")
                        continue
                    valid.append(fields)

            if not valid:
                flash(f"Import completed: {processed} rows processed, 0 new, 0 updated, {errors} errors.","error")
                if error_rows:
                    flash(" | ".join(error_rows[:8]),"error")
                return redirect(url_for("inspection_import"))

            # A user may upload overlapping batch files. PostgreSQL cannot
            # update the same ON CONFLICT key twice within one INSERT statement,
            # so collapse duplicate State Codes before the bulk upsert. The last
            # valid occurrence wins, while `processed` still reports every row.
            deduped={}
            for f in valid:
                deduped[f["state"].strip()]=f
            valid=list(deduped.values())

            c=db()
            t=now()
            user_id=current_user()["id"]

            # -------------------------------------------------------------
            # 2. Bulk-create PPAs. UNIQUE(name,lga) prevents duplicates.
            # -------------------------------------------------------------
            ppa_keys=[]
            seen_ppas=set()
            for f in valid:
                key=(f["ppa"].strip(),f["lga"].strip())
                if key not in seen_ppas:
                    seen_ppas.add(key)
                    ppa_keys.append(key)

            if ppa_keys:
                placeholders=",".join(["(%s,%s,1,%s,%s)"]*len(ppa_keys))
                params=[]
                for name,lga in ppa_keys:
                    params.extend([name,lga,user_id,t])
                c.execute(f"""
                    INSERT INTO ppa_establishments(name,lga,active,created_by,created_at)
                    VALUES {placeholders}
                    ON CONFLICT (name,lga) DO NOTHING
                """,params)

            # Fetch all relevant PPA ids in one query.
            ppa_where=",".join(["(%s,%s)"]*len(ppa_keys))
            ppa_params=[]
            for name,lga in ppa_keys:
                ppa_params.extend([name,lga])
            ppa_rows=c.execute(f"""
                SELECT id,name,lga FROM ppa_establishments
                WHERE (name,lga) IN ({ppa_where})
            """,ppa_params).fetchall()
            ppa_map={(r["name"].lower(),r["lga"].lower()):r["id"] for r in ppa_rows}

            # -------------------------------------------------------------
            # 3. Determine new vs existing State Codes with one query.
            # -------------------------------------------------------------
            states=[]
            seen_states=set()
            for f in valid:
                st=f["state"].strip()
                if st not in seen_states:
                    seen_states.add(st)
                    states.append(st)

            existing_states=set()
            # PostgreSQL has a practical parameter limit; 2,458 is well below
            # it, but chunking keeps this safe for larger future imports.
            for i in range(0,len(states),500):
                part=states[i:i+500]
                ph=",".join(["%s"]*len(part))
                found=c.execute(f"SELECT state_code FROM corps_members WHERE state_code IN ({ph})",part).fetchall()
                existing_states.update(r["state_code"] for r in found)

            # -------------------------------------------------------------
            # 4. Bulk upsert Corps Members in chunks. Each chunk is one SQL
            # statement, instead of 4+ network round-trips per row.
            # -------------------------------------------------------------
            new_count=sum(1 for f in valid if f["state"] not in existing_states)
            updated_count=sum(1 for f in valid if f["state"] in existing_states)

            columns=("state_code,full_name,gender,discipline,ppa_id,batch,stream,phone,status,created_at,updated_at")
            for offset in range(0,len(valid),500):
                chunk=valid[offset:offset+500]
                values=[]
                params=[]
                for f in chunk:
                    ppa_id=ppa_map.get((f["ppa"].strip().lower(),f["lga"].strip().lower()))
                    if not ppa_id:
                        raise RuntimeError(f"PPA could not be resolved: {f['ppa']} ({f['lga']})")
                    values.append("(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
                    params.extend([
                        f["state"],f["name"],f["gender"],f["discipline"],ppa_id,
                        f["batch"],f["stream"],f["phone"],f["status"],t,t
                    ])
                c.execute(f"""
                    INSERT INTO corps_members({columns})
                    VALUES {','.join(values)}
                    ON CONFLICT (state_code) DO UPDATE SET
                        full_name=EXCLUDED.full_name,
                        gender=EXCLUDED.gender,
                        discipline=EXCLUDED.discipline,
                        ppa_id=EXCLUDED.ppa_id,
                        batch=EXCLUDED.batch,
                        stream=EXCLUDED.stream,
                        phone=EXCLUDED.phone,
                        status=EXCLUDED.status,
                        updated_at=EXCLUDED.updated_at
                """,params)

            c.commit()
            c.close()

            msg=f"Import completed: {processed} rows processed, {new_count} new, {updated_count} updated, {errors} errors."
            flash(msg,"success" if errors==0 else "error")
            if error_rows:
                flash(" | ".join(error_rows[:8]),"error")

        except Exception as exc:
            try:
                c.rollback()
                c.close()
            except Exception:
                pass
            flash(f"Import failed: {exc}","error")
        return redirect(url_for("inspection_import"))
    return render_template("inspection_import.html", lgas=LGAS)


@app.route("/inspection/assign",methods=["POST"])
@inspection_management_required
def inspection_assign():
    ppa_id=request.form.get("ppa_id",type=int); staff_id=request.form.get("staff_id",type=int)
    if not ppa_id or not staff_id:
        flash("PPA/Establishment and Supporting Staff are required.","error"); return redirect(url_for("inspections"))
    c=db(); p=c.execute("SELECT * FROM ppa_establishments WHERE id=%s AND active=1",(ppa_id,)).fetchone(); staff=c.execute("SELECT * FROM users WHERE id=%s AND role='Supporting Staff' AND active=1",(staff_id,)).fetchone()
    if not p or not staff:
        c.close(); flash("Invalid PPA or Supporting Staff selected.","error"); return redirect(url_for("inspections"))
    c.execute("UPDATE inspection_assignments SET status='Reassigned' WHERE ppa_id=%s AND status='Active'",(ppa_id,))
    c.execute("""INSERT INTO inspection_assignments(ppa_id,supporting_staff_id,assigned_by,assigned_at,status)
                 VALUES(%s,%s,%s,%s,'Active')""",(ppa_id,staff_id,current_user()["id"],now()))
    c.commit(); c.close(); flash(f"{p['name']} assigned to {staff['full_name']}.","success"); return redirect(url_for("inspections"))


@app.route("/inspection/assignment/<int:assignment_id>/remove",methods=["POST"])
@inspection_management_required
def inspection_remove_assignment(assignment_id):
    c=db(); c.execute("UPDATE inspection_assignments SET status='Removed' WHERE id=%s",(assignment_id,)); c.commit(); c.close(); flash("Inspection assignment removed.","success"); return redirect(url_for("inspections"))



@app.route("/inspection/submit/<int:ppa_id>", methods=["POST"])
@login_required
def inspection_submit_to_zi(ppa_id):
    """Create a timestamped, reviewable snapshot of the current PPA inspection."""
    u=current_user()
    if u["role"] != "Supporting Staff":
        flash("Only Supporting Staff can submit an inspection report to the Zonal Inspector.","error")
        return redirect(url_for("inspection_ppa", ppa_id=ppa_id))
    c=db()
    allowed=c.execute("""SELECT 1 FROM inspection_assignments
                       WHERE ppa_id=%s AND supporting_staff_id=%s AND status='Active'""",(ppa_id,u["id"])).fetchone()
    ppa=c.execute("SELECT * FROM ppa_establishments WHERE id=%s AND active=1",(ppa_id,)).fetchone()
    if not allowed or not ppa:
        c.close(); flash("This PPA is not assigned to you.","error")
        return redirect(url_for("inspections"))
    rows=c.execute("""SELECT cm.id,cm.state_code,cm.full_name,cm.gender,cm.discipline,cm.batch,cm.stream,
                            lr.attendance_status,lr.inspected_at,lr.remarks,lr.other_reason
                     FROM corps_members cm
                     LEFT JOIN LATERAL (
                       SELECT ir.attendance_status,ir.inspected_at,ir.remarks,ir.other_reason
                       FROM inspection_records ir
                       WHERE ir.corps_member_id=cm.id AND ir.ppa_id=%s
                       ORDER BY ir.id DESC LIMIT 1
                     ) lr ON TRUE
                     WHERE cm.ppa_id=%s AND cm.status='Active'
                     ORDER BY cm.full_name""",(ppa_id,ppa_id)).fetchall()
    snapshot=[]
    for r in rows:
        snapshot.append({k:r[k] for k in ("id","state_code","full_name","gender","discipline","batch","stream","attendance_status","inspected_at","remarks","other_reason")})
    present=sum(1 for r in rows if r["attendance_status"]=="Present")
    absent=sum(1 for r in rows if r["attendance_status"]=="Absent")
    pending=sum(1 for r in rows if r["attendance_status"] is None)
    other=len(rows)-present-absent-pending
    t=now()
    c.execute("""INSERT INTO inspection_submissions
      (ppa_id,supporting_staff_id,submitted_at,status,total_count,present_count,absent_count,pending_count,other_count,snapshot)
      VALUES(%s,%s,%s,'Submitted',%s,%s,%s,%s,%s,%s::jsonb)""",
      (ppa_id,u["id"],t,len(rows),present,absent,pending,other,json.dumps(snapshot,default=str)))
    c.commit(); c.close()
    flash(f"Inspection report for {ppa['name']} submitted to the Zonal Inspector for review.","success")
    return redirect(url_for("inspection_ppa",ppa_id=ppa_id))

@app.route("/inspection/review-inbox")
@login_required
def inspection_review_inbox():
    u=current_user()
    if u["role"] not in ("Administrator","Zonal Inspector"):
        flash("Only the Administrator or Zonal Inspector may review inspection submissions.","error")
        return redirect(url_for("inspections"))
    c=db()
    rows=c.execute("""SELECT s.*,p.name AS ppa_name,p.lga,u.full_name AS staff_name,
                            rv.full_name AS reviewer_name
                     FROM inspection_submissions s
                     JOIN ppa_establishments p ON p.id=s.ppa_id
                     JOIN users u ON u.id=s.supporting_staff_id
                     LEFT JOIN users rv ON rv.id=s.reviewed_by
                     ORDER BY CASE WHEN s.status='Submitted' THEN 0 WHEN s.status='Returned' THEN 1 ELSE 2 END,
                              s.id DESC""").fetchall()
    c.close()
    return render_template("inspection_review_inbox.html",rows=rows)

@app.route("/inspection/review/<int:submission_id>")
@login_required
def inspection_review_detail(submission_id):
    u=current_user()
    if u["role"] not in ("Administrator","Zonal Inspector"):
        flash("Only the Administrator or Zonal Inspector may review inspection submissions.","error")
        return redirect(url_for("inspections"))
    c=db()
    row=c.execute("""SELECT s.*,p.name AS ppa_name,p.lga,u.full_name AS staff_name,
                           rv.full_name AS reviewer_name
                    FROM inspection_submissions s
                    JOIN ppa_establishments p ON p.id=s.ppa_id
                    JOIN users u ON u.id=s.supporting_staff_id
                    LEFT JOIN users rv ON rv.id=s.reviewed_by
                    WHERE s.id=%s""",(submission_id,)).fetchone()
    c.close()
    if not row: return "Inspection submission not found",404
    data=dict(row)
    data["snapshot"]=data["snapshot"] if isinstance(data["snapshot"],list) else json.loads(data["snapshot"])
    present=[x for x in data["snapshot"] if x.get("attendance_status")=="Present"]
    absent=[x for x in data["snapshot"] if x.get("attendance_status")=="Absent"]
    pending=[x for x in data["snapshot"] if not x.get("attendance_status")]
    other=[x for x in data["snapshot"] if x.get("attendance_status") not in (None,"Present","Absent")]
    return render_template("inspection_review_detail.html",submission=data,present=present,absent=absent,pending=pending,other=other)

@app.route("/inspection/review/<int:submission_id>/decision", methods=["POST"])
@login_required
def inspection_review_decision(submission_id):
    u=current_user()
    if u["role"] not in ("Administrator","Zonal Inspector"):
        flash("Only the Administrator or Zonal Inspector may review inspection submissions.","error")
        return redirect(url_for("inspections"))
    decision=request.form.get("decision","").strip()
    comment=request.form.get("review_comment","").strip()
    if decision not in ("Reviewed","Returned"):
        flash("Select Reviewed or Returned.","error")
        return redirect(url_for("inspection_review_detail",submission_id=submission_id))
    if decision=="Returned" and not comment:
        flash("Please provide a reason when returning a report to Supporting Staff.","error")
        return redirect(url_for("inspection_review_detail",submission_id=submission_id))
    c=db()
    exists=c.execute("SELECT id FROM inspection_submissions WHERE id=%s",(submission_id,)).fetchone()
    if not exists:
        c.close(); return "Inspection submission not found",404
    c.execute("""UPDATE inspection_submissions
                 SET status=%s,reviewed_by=%s,reviewed_at=%s,review_comment=%s
                 WHERE id=%s""",(decision,u["id"],now(),comment,submission_id))
    c.commit(); c.close()
    flash("Inspection report marked as reviewed." if decision=="Reviewed" else "Inspection report returned to Supporting Staff for attention.","success")
    return redirect(url_for("inspection_review_detail",submission_id=submission_id))

@app.route("/inspection/reports")
@login_required
def inspection_reports():
    """Hierarchical inspection reports for the Zonal Inspector/Admin.

    Structure: Supporting Staff -> Assigned PPA -> Present / Absent / Pending.
    The report uses the latest inspection record for each active Corps Member.
    """
    u=current_user()
    if u["role"] not in ("Administrator","Zonal Inspector"):
        flash("Inspection reports are available to the Administrator and Zonal Inspector.","error")
        return redirect(url_for("inspections"))
    c=db()
    staff_rows=c.execute("""
        SELECT u.id, u.full_name,
               COUNT(DISTINCT ia.ppa_id)::int AS ppa_count,
               COUNT(DISTINCT cm.id)::int AS corps_count,
               COUNT(DISTINCT cm.id) FILTER (WHERE lr.attendance_status='Present')::int AS present_count,
               COUNT(DISTINCT cm.id) FILTER (WHERE lr.attendance_status='Absent')::int AS absent_count,
               COUNT(DISTINCT cm.id) FILTER (WHERE lr.id IS NULL)::int AS pending_count
        FROM inspection_assignments ia
        JOIN users u ON u.id=ia.supporting_staff_id
        JOIN ppa_establishments p ON p.id=ia.ppa_id AND p.active=1
        LEFT JOIN corps_members cm ON cm.ppa_id=p.id AND cm.status='Active'
        LEFT JOIN LATERAL (
            SELECT ir.id, ir.attendance_status
            FROM inspection_records ir
            WHERE ir.corps_member_id=cm.id AND ir.ppa_id=p.id
            ORDER BY ir.id DESC LIMIT 1
        ) lr ON TRUE
        WHERE ia.status='Active' AND u.active=1
        GROUP BY u.id,u.full_name
        ORDER BY u.full_name
    """).fetchall()
    c.close()
    return render_template("inspection_reports.html",staff_rows=staff_rows)


@app.route("/inspection/reports/staff/<int:staff_id>")
@login_required
def inspection_report_staff(staff_id):
    u=current_user()
    if u["role"] not in ("Administrator","Zonal Inspector"):
        flash("Inspection reports are available to the Administrator and Zonal Inspector.","error")
        return redirect(url_for("inspections"))
    c=db()
    staff=c.execute("SELECT id,full_name,username FROM users WHERE id=%s AND role='Supporting Staff'",(staff_id,)).fetchone()
    if not staff:
        c.close(); return "Supporting Staff not found",404
    ppas=c.execute("""
        SELECT p.id,p.name,p.lga,
               COUNT(cm.id)::int AS total,
               COUNT(cm.id) FILTER (WHERE lr.attendance_status='Present')::int AS present_count,
               COUNT(cm.id) FILTER (WHERE lr.attendance_status='Absent')::int AS absent_count,
               COUNT(cm.id) FILTER (WHERE lr.id IS NULL)::int AS pending_count
        FROM inspection_assignments ia
        JOIN ppa_establishments p ON p.id=ia.ppa_id AND p.active=1
        LEFT JOIN corps_members cm ON cm.ppa_id=p.id AND cm.status='Active'
        LEFT JOIN LATERAL (
            SELECT ir.id,ir.attendance_status
            FROM inspection_records ir
            WHERE ir.corps_member_id=cm.id AND ir.ppa_id=p.id
            ORDER BY ir.id DESC LIMIT 1
        ) lr ON TRUE
        WHERE ia.supporting_staff_id=%s AND ia.status='Active'
        GROUP BY p.id,p.name,p.lga
        ORDER BY p.lga,p.name
    """,(staff_id,)).fetchall()
    c.close()
    return render_template("inspection_report_staff.html",staff=staff,ppas=ppas)


@app.route("/inspection/reports/ppa/<int:ppa_id>")
@login_required
def inspection_report_ppa(ppa_id):
    u=current_user()
    if u["role"] not in ("Administrator","Zonal Inspector"):
        flash("Inspection reports are available to the Administrator and Zonal Inspector.","error")
        return redirect(url_for("inspections"))
    c=db()
    ppa=c.execute("""
        SELECT p.*,u.id AS staff_id,u.full_name AS staff_name
        FROM ppa_establishments p
        JOIN inspection_assignments ia ON ia.ppa_id=p.id AND ia.status='Active'
        JOIN users u ON u.id=ia.supporting_staff_id
        WHERE p.id=%s AND p.active=1
    """,(ppa_id,)).fetchone()
    if not ppa:
        c.close(); return "PPA not found or not actively assigned",404
    rows=c.execute("""
        SELECT cm.id,cm.state_code,cm.full_name,cm.gender,cm.discipline,
               cm.batch,cm.stream,lr.attendance_status,lr.inspected_at,lr.remarks,
               lr.other_reason
        FROM corps_members cm
        LEFT JOIN LATERAL (
            SELECT ir.attendance_status,ir.inspected_at,ir.remarks,ir.other_reason
            FROM inspection_records ir
            WHERE ir.corps_member_id=cm.id AND ir.ppa_id=%s
            ORDER BY ir.id DESC LIMIT 1
        ) lr ON TRUE
        WHERE cm.ppa_id=%s AND cm.status='Active'
        ORDER BY CASE WHEN lr.attendance_status='Present' THEN 1 WHEN lr.attendance_status='Absent' THEN 2 ELSE 3 END, cm.full_name
    """,(ppa_id,ppa_id)).fetchall()
    c.close()
    present=[r for r in rows if r["attendance_status"]=="Present"]
    absent=[r for r in rows if r["attendance_status"]=="Absent"]
    pending=[r for r in rows if r["attendance_status"] is None]
    other=[r for r in rows if r["attendance_status"] not in (None,"Present","Absent")]
    return render_template("inspection_report_ppa.html",ppa=ppa,present=present,absent=absent,pending=pending,other=other)

@app.route("/inspection/live-dashboard")
@login_required
def inspection_live_dashboard():
    """Return current PPA inspection/clearance progress for ZI/Admin dashboard.

    Cleared = latest inspection status is Present.
    Not Cleared = active Corps Member has no latest Present inspection.
    The endpoint is read-only and is polled by the dashboard every 10 seconds.
    """
    u=current_user()
    if u["role"] not in ("Administrator","Zonal Inspector"):
        return {"error":"Only the Administrator or Zonal Inspector may view the live inspection dashboard."},403
    c=db()
    rows=c.execute("""
        WITH latest AS (
            SELECT DISTINCT ON (ir.corps_member_id)
                   ir.corps_member_id, ir.attendance_status, ir.inspected_at,
                   u.full_name AS inspector_name
            FROM inspection_records ir
            JOIN users u ON u.id=ir.inspected_by
            ORDER BY ir.corps_member_id, ir.id DESC
        )
        SELECT p.id, p.name AS ppa_name, p.lga,
               COALESCE(st.full_name,'Not assigned') AS staff_name,
               COUNT(cm.id)::int AS total,
               COUNT(*) FILTER (WHERE l.attendance_status='Present')::int AS cleared,
               COUNT(*) FILTER (WHERE l.attendance_status IS NULL OR l.attendance_status<>'Present')::int AS not_cleared,
               COUNT(*) FILTER (WHERE l.attendance_status='Absent')::int AS absent,
               COUNT(*) FILTER (WHERE l.attendance_status='Leave')::int AS leave_count,
               COUNT(*) FILTER (WHERE l.attendance_status='Sick Leave')::int AS sick_leave,
               COUNT(*) FILTER (WHERE l.attendance_status='Maternity Leave')::int AS maternity_leave,
               MAX(l.inspected_at) AS last_update
        FROM ppa_establishments p
        JOIN inspection_assignments ia ON ia.ppa_id=p.id AND ia.status='Active'
        LEFT JOIN users st ON st.id=ia.supporting_staff_id
        LEFT JOIN corps_members cm ON cm.ppa_id=p.id AND cm.status='Active'
        LEFT JOIN latest l ON l.corps_member_id=cm.id
        WHERE p.active=1
        GROUP BY p.id,p.name,p.lga,st.full_name
        ORDER BY p.lga,p.name
    """).fetchall()
    c.close()
    return {"updated_at":now(),"ppas":[dict(r) for r in rows]}


@app.route("/inspection/ppa/<int:ppa_id>")
@login_required
def inspection_ppa(ppa_id):
    u=current_user(); c=db(); p=c.execute("SELECT * FROM ppa_establishments WHERE id=%s AND active=1",(ppa_id,)).fetchone()
    if not p:
        c.close(); return "PPA not found",404
    if u["role"]=="Supporting Staff":
        allowed=c.execute("SELECT 1 FROM inspection_assignments WHERE ppa_id=%s AND supporting_staff_id=%s AND status='Active'",(ppa_id,u["id"])).fetchone()
        if not allowed:
            c.close(); flash("This PPA is not assigned to you.","error"); return redirect(url_for("inspections"))
    elif u["role"] not in ("Administrator","Zonal Inspector"):
        c.close(); flash("Inspection access is not available to this role.","error"); return redirect(url_for("dashboard"))
    members=c.execute("""SELECT cm.*,lr.attendance_status,lr.inspected_at,lr.remarks,lr.other_reason
                    FROM corps_members cm
                    LEFT JOIN LATERAL (
                        SELECT ir.attendance_status,ir.inspected_at,ir.remarks,ir.other_reason
                        FROM inspection_records ir
                        WHERE ir.corps_member_id=cm.id AND ir.ppa_id=%s
                        ORDER BY ir.id DESC LIMIT 1
                    ) lr ON TRUE
                    WHERE cm.ppa_id=%s AND cm.status='Active' ORDER BY cm.full_name""",(ppa_id,ppa_id)).fetchall()
    present=[m for m in members if m["attendance_status"]=="Present"]
    absent=[m for m in members if m["attendance_status"]=="Absent"]
    pending=[m for m in members if m["attendance_status"] is None]
    other=[m for m in members if m["attendance_status"] not in (None,"Present","Absent")]
    latest_submission=c.execute("""SELECT s.*,rv.full_name AS reviewer_name
                                  FROM inspection_submissions s
                                  LEFT JOIN users rv ON rv.id=s.reviewed_by
                                  WHERE s.ppa_id=%s ORDER BY s.id DESC LIMIT 1""",(ppa_id,)).fetchone()
    c.close()
    return render_template("inspection_ppa.html",ppa=p,members=members,present=present,absent=absent,pending=pending,other=other,latest_submission=latest_submission)


@app.route("/inspection/ppa/<int:ppa_id>/search")
@login_required
def inspection_search(ppa_id):
    u=current_user(); state=request.args.get("state_code","").strip()
    if u["role"]!="Supporting Staff": return {"error":"Only Supporting Staff may use this search."},403
    c=db(); allowed=c.execute("SELECT 1 FROM inspection_assignments WHERE ppa_id=%s AND supporting_staff_id=%s AND status='Active'",(ppa_id,u["id"])).fetchone()
    if not allowed: c.close(); return {"error":"PPA is not assigned to you."},403
    # State Codes are case-insensitive and surrounding spaces are ignored.
    # This lets staff enter kt/26a/0173, KT/26A/0173, or values copied with spaces.
    row=c.execute("""SELECT cm.*,p.name AS ppa_name,p.lga FROM corps_members cm JOIN ppa_establishments p ON p.id=cm.ppa_id
                     WHERE cm.ppa_id=%s
                       AND UPPER(TRIM(cm.state_code))=UPPER(TRIM(%s))
                       AND cm.status='Active'""",(ppa_id,state)).fetchone(); c.close()
    if not row: return {"found":False,"message":"No active corps member was found under this PPA for that State Code."}
    return {"found":True,"member":dict(row)}


@app.route("/inspection/record",methods=["POST"])
@login_required
def inspection_record():
    u=current_user()
    if u["role"]!="Supporting Staff":
        flash("Only Supporting Staff may submit inspection attendance.","error"); return redirect(url_for("inspections"))
    ppa_id=request.form.get("ppa_id",type=int); member_id=request.form.get("corps_member_id",type=int); status=request.form.get("attendance_status","").strip(); other=request.form.get("other_reason","").strip(); remarks=request.form.get("remarks","").strip()
    allowed_status={"Present","Absent","Leave","Sick Leave","Maternity Leave","Others"}
    if status not in allowed_status:
        flash("Please select a valid inspection status.","error"); return redirect(url_for("inspection_ppa",ppa_id=ppa_id))
    if status=="Others" and not other:
        flash("Please specify the reason for Other status.","error"); return redirect(url_for("inspection_ppa",ppa_id=ppa_id))
    c=db(); allowed=c.execute("SELECT 1 FROM inspection_assignments WHERE ppa_id=%s AND supporting_staff_id=%s AND status='Active'",(ppa_id,u["id"])).fetchone(); member=c.execute("SELECT * FROM corps_members WHERE id=%s AND ppa_id=%s AND status='Active'",(member_id,ppa_id)).fetchone()
    if not allowed or not member:
        c.close(); flash("The selected corps member or PPA is not assigned to you.","error"); return redirect(url_for("inspections"))
    iid=next_new_inspection_id(); t=now(); query=1 if status=="Absent" else 0
    c.execute("""INSERT INTO inspection_records(inspection_id,corps_member_id,ppa_id,inspected_by,attendance_status,query_issued,other_reason,remarks,inspected_at)
                 VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(iid,member_id,ppa_id,u["id"],status,query,other,remarks,t))
    # Keep the legacy inspections table populated for compatibility with existing reporting screens.
    findings=f"Attendance status: {status}. Query issued: {'Yes' if query else 'No'}." + (f" Reason: {other}." if other else "")
    c.execute("""INSERT INTO inspections(inspection_id,lga,ppa_employer,corps_member,subject,findings,recommendations,inspected_by,inspected_at,status)
                 VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(iid,member["ppa_id"] and c.execute("SELECT lga FROM ppa_establishments WHERE id=%s",(ppa_id,)).fetchone()["lga"],member["ppa_id"] and c.execute("SELECT name FROM ppa_establishments WHERE id=%s",(ppa_id,)).fetchone()["name"],member["full_name"],"PPA Attendance Inspection",findings,remarks,u["full_name"],t,"Completed"))
    c.commit(); c.close(); flash(f"{iid} recorded successfully. Query issued: {'YES' if query else 'NO'}.","success"); return redirect(url_for("inspection_ppa",ppa_id=ppa_id))

@app.route("/reports")
@login_required
def reports():
    u=current_user(); c=db()
    if u["role"] == "LGI Officer": rows=c.execute("SELECT * FROM reports WHERE lga=%s ORDER BY id DESC",(u["lga"],)).fetchall()
    elif u["role"] in ("Administrator", "Zonal Inspector"): rows=c.execute("SELECT * FROM reports ORDER BY id DESC").fetchall()
    else: c.close(); flash("Reports are not available to this role.","error"); return redirect(url_for("dashboard"))
    c.close(); return render_template("reports.html",rows=rows,report_only=(u["role"]=="LGI Officer"))

@app.route("/report/new",methods=["GET","POST"])
@report_management_required
def new_report():
    if request.method=="POST":
        subject=request.form.get("subject","").strip(); body=request.form.get("report_body","").strip(); lga=request.form.get("lga","").strip()
        if not subject or not body or lga not in LGAS: flash("LGA, report subject and report content are required.","error"); return redirect(url_for("new_report"))
        t=now(); rid=next_report_id(); u=current_user(); c=db(); c.execute("INSERT INTO reports (report_id,lga,report_type,ppa_employer,corps_member,subject,report_body,issued_by,issued_at,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(rid,lga,request.form.get("report_type","General LGA Report"),request.form.get("ppa_employer"),request.form.get("corps_member"),subject,body,u["full_name"],t,"Issued")); c.commit(); c.close(); flash(f"{rid} issued to {lga} LGI.","success"); return redirect(url_for("reports"))
    return render_template("report_form.html",lgas=LGAS)

@app.route("/download/<name>")
@login_required
@lgi_report_only
def download(name):
    return send_from_directory(UPLOADS,name,as_attachment=True)

@app.route("/admin/db-inspection")
@admin_required
def db_inspection():
    """Read-only PostgreSQL inspection page for the Administrator."""
    with db() as c:
        tables = c.execute("""
            SELECT tablename
            FROM pg_catalog.pg_tables
            WHERE schemaname='public'
            ORDER BY tablename
        """).fetchall()

        counts = {}
        for row in tables:
            table = row["tablename"]
            counts[table] = c.execute(
                f'SELECT COUNT(*) AS count FROM "{table}"'
            ).fetchone()["count"]

        database = c.execute(
            "SELECT current_database() AS database"
        ).fetchone()["database"]
        version = c.execute(
            "SELECT version() AS version"
        ).fetchone()["version"]

    rows = "".join(
        f"<tr><td>{name}</td><td>{count}</td></tr>"
        for name, count in counts.items()
    )
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Database Inspection</title>
<style>body{{font-family:Arial,sans-serif;margin:40px}}table{{border-collapse:collapse}}
th,td{{border:1px solid #ccc;padding:8px 12px}}th{{background:#f3f3f3}}</style></head>
<body><h1>PostgreSQL Database Inspection</h1>
<p><b>Database:</b> {database}</p><p><b>Server:</b> {version}</p>
<table><tr><th>Table</th><th>Rows</th></tr>{rows}</table>
</body></html>"""
    return html

init_db()

if __name__=="__main__":
    app.run(debug=True)
