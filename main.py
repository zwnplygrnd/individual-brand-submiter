# app.py
from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
import json, os, pathlib, requests
from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleRequest
import google.auth.transport.requests
import google.auth
from google.cloud import firestore
import base64, hashlib

db = firestore.Client(database="brand-submitter", project="regulator-wr")
COLL = os.environ["COLLECTION_NAME"]    
print(COLL)                     # collection name

def _doc_id(name: str) -> str:
    """
    Return a URL-safe, slash-free doc ID derived from |name|.
    Uses SHA-1 → 20 bytes → base64url (27 chars).
    """
    digest = hashlib.sha1(name.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")

def save_operation(name: str, url: str, payload: dict):
    """Add or update a Firestore document whose ID is the operation name."""
    doc_ref = db.collection(COLL).document(_doc_id(name))
    doc_ref.set({
        "name":    name,
        "url":     url,
        "payload": payload,          # Firestore accepts nested maps
        "created": firestore.SERVER_TIMESTAMP,
    }, merge=True)

def list_operations() -> list[str]:
    """Return operation names currently stored (oldest first)."""
    docs = (
        db.collection(COLL)
        .order_by("created", direction=firestore.Query.DESCENDING)
        .stream()
    )
    names = []
    for d in docs:
        data = d.to_dict() or {}
        names.append(data.get("name") or d.id)   # fall-back = old hash
    return names

app = Flask(__name__)                                  # ← no secret key

KEY_PATH = os.getenv("WEBRISK_KEY_PATH", "/var/secrets/key.json")
SCOPES   = ["https://www.googleapis.com/auth/cloud-platform"]

# ──────────────────────────────────────────────────────────────────────────────
def get_access_token() -> str:
    creds = service_account.Credentials.from_service_account_file(
        KEY_PATH, scopes=SCOPES
    )
    creds.refresh(GoogleRequest())
    return creds.token

# ────────────────────────────  shared CSS  ───────────────────────────────────
CSS = """
<style>
/* Copy button hover + active feedback */
.copy-btn{
  transition:transform .05s, background .15s;
}
.copy-btn:hover{
  background:#6a95ff;                    /* slightly lighter blue */
}
.copy-btn.clicked{
  transform:scale(0.93);                 /* quick “press” effect */
}
/* fixed footer help message */
.issue-msg{
  position:fixed;
  left:18px;
  bottom:18px;
  font-size:14px;
  color: white;
}
.issue-msg a{color:inherit;text-decoration:none}
.issue-msg a:hover{color:var(--accent)}

.op-card{
  cursor:pointer;
  background:var(--panel);
  border-radius:6px;
  padding:12px;
  transition:background .15s;
}
.op-card:hover{
  background:#3a3a49;          /* slightly lighter */
}
.caret{margin-right:6px}        /* keep arrow neutral */
:root{
  --bg:#0f0f13; --panel:#2a2a39; --text:#e8e8e8;
  --placeholder:#7c7c8c; --accent:#5981ff; --error:#ff4d4f; --success:#17c964;
}
html,body{height:100%;margin:0;font-family:-apple-system,BlinkMacSystemFont,Inter,
          Roboto,"Helvetica Neue",Arial,sans-serif;background:var(--bg);color:var(--text);}
.wrap{display:flex;flex-direction:column;align-items:center;max-width:800px;margin:40px auto;padding:0 12px}
h1{font-weight:600;margin:0 0 30px 0}
a.top-nav{position:fixed;top:18px;left:18px;padding:8px 20px;border-radius:6px;text-decoration:none;
          font-size:14px;background:var(--panel);color:var(--text);border:1px solid var(--panel)}
a.top-nav:hover{background:var(--accent);color:#fff}
label{display:block;margin:18px 0 6px 0}.required{color:var(--error)}
input,select,textarea{width:100%;box-sizing:border-box;background:var(--panel);color:var(--text);
      border:1px solid var(--panel);border-radius:6px;padding:12px 14px;font-size:15px;}
input::placeholder,textarea::placeholder{color:var(--placeholder)}
textarea{resize:vertical;min-height:90px}
button{padding:12px 32px;font-size:16px;font-weight:600;background:var(--accent);
       color:white;border:none;border-radius:6px;cursor:pointer}
button:hover{opacity:.9}
#submitBtn{margin-top:28px}
.flash{margin:12px 0;color:var(--error)}
pre.json{background:var(--panel);padding:18px;border-radius:6px;overflow:auto}

/* pills for states */
.pill{display:inline-block;padding:4px 14px;font-size:12px;font-weight:600;border-radius:4px;
      color:#fff;text-transform:uppercase}
.pill-success{background:var(--success)}
.pill-running{background:#e6c74c}
.pill-closed{ background:var(--error)}

/* op-list layout */
.op-item{margin-bottom:22px}
.time{color:var(--placeholder);margin-right:8px}
.op-header{display:flex;align-items:center;gap:6px;cursor:pointer}
.op-header:hover .caret{color:var(--accent)}

/* modal */
#overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);
         backdrop-filter:blur(2px);z-index:1000;justify-content:center;align-items:center}
.modal{background:var(--panel);padding:32px 28px;border-radius:8px;max-width:480px;width:90%;
       box-shadow:0 8px 32px rgba(0,0,0,.6);position:relative}
.modal h2{margin:0 0 18px;font-size:20px}
.close-btn{position:absolute;top:12px;right:12px;font-size:22px;background:none;border:none;
           color:var(--text);cursor:pointer}
.key-row{display:flex;gap:10px;margin-top:14px}
.key-row input{flex:1;background:var(--bg);border:1px solid var(--bg);border-radius:6px;
               padding:12px 14px;font-family:monospace;color:var(--text)}
.copy-btn{padding:10px 22px;font-size:14px}
/* table layout */
.ops-table{width:100%;border-collapse:collapse;margin-top:16px}
.ops-table th,.ops-table td{padding:12px 16px;text-align:left}

/* header row uses same base colour as rows */
.ops-table thead th{
  background:var(--panel);color:var(--text);font-size:20px;font-weight:600;
}

/* zebra-striped body rows */
.ops-table tbody tr:nth-child(odd){background:#2a2a39;}
.ops-table tbody tr:nth-child(even){background:#363646;}

/* hover highlight so users see it’s clickable */
.ops-table tbody tr:hover{background:#444455;cursor:pointer}

/* cell with the coloured pill */
.status-cell{min-width:120px}
.ops-table thead tr:first-child th{
  font-size:32px;          /* adjust as you like */
  line-height:1.3;
}
/* legend table (top-right) */
.legend-wrap{display:flex;justify-content:space-between;width:100%}
.legend-table{border-collapse:collapse;margin-left:auto}
.legend-table th,.legend-table td{padding:8px 12px;text-align:left;vertical-align:top}
.legend-table thead th{
  background:var(--panel);color:var(--text);font-size:20px;font-weight:600;
}
.legend-table .pill{margin-right:6px}
/* ------ shared row look & feel ------------------------------------ */
.ops-table tbody tr,
.legend-table tbody tr{
  border-bottom:1px solid #444;          /* clearer separation */
}

/* zebra stripes for BOTH tables */
.ops-table tbody tr:nth-child(odd),
.legend-table tbody tr:nth-child(odd){background:#2a2a39;}
.ops-table tbody tr:nth-child(even),
.legend-table tbody tr:nth-child(even){background:#363646;}

/* same header colour on both tables */
.legend-table thead th{background:var(--panel);color:var(--text)}

/* layout tweaks */
.legend-wrap{display:flex;gap:40px;width:100%}   /* fixed gap between tables */
.legend-table{border-collapse:collapse;margin-left:auto;min-width:380px}
/* hover highlight only for ops-table body rows */
.ops-table tbody tr:hover{background:#444455;cursor:pointer}
/* remove hover from legend rows */
.legend-table tbody tr:hover{background:inherit;cursor:default}

/* arrow / expand button */
.expand-btn{cursor:pointer;font-weight:700}
.legend-table tbody tr{
  background:#2a2a39 !important;   /* fixed background for all legend rows */
}
/* FINAL override — keep every legend row a single colour */
.legend-table tbody tr:nth-child(odd),
.legend-table tbody tr:nth-child(even){
  background:#2a2a39 !important;   /* same solid colour for all */
}

</style>
"""

# ─────────────────────────  MAIN PAGE  ───────────────────────────────────────
MAIN_TEMPLATE = """
<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Web Risk Submission Application</title>{{ css|safe }}</head><body>
<a class="top-nav" href="/operations">Operations</a>
<div class="wrap">
  <h1>Web Risk Submission Application</h1>
  <div class="flash" id="flash"></div>

  <form id="submitForm">
    <label>Web Risk service-account key (JSON) <span class="required">*</span></label>
    <textarea name="sa_key" required rows="6" placeholder='Paste the JSON key here'></textarea>


    <label>Project number <span class="required">*</span></label>
    <input name="parent" placeholder="123456789" required>

    <label>Suspicious URI <span class="required">*</span></label>
    <input name="uri" placeholder="https://evil.example" required>

    <label>Abuse type</label>
    <select name="abuseType">
      <option value="">(not specified)</option>
      <option>MALWARE</option>
      <option>SOCIAL_ENGINEERING</option>
      <option>UNWANTED_SOFTWARE</option>
    </select>

    <label>Confidence score (0-1)</label>
    <input name="score" type="number" step="0.01" min="0" max="1">

    <label>Confidence level</label>
    <select name="level">
      <option value="">(not specified)</option>
      <option>LOW</option>
      <option>MEDIUM</option>
      <option>HIGH</option>
    </select>

    <label>Justification labels (Ctrl/Cmd-click to multi-select)</label>
    <select name="labels" multiple size="4">
      <option>MANUAL_VERIFICATION</option>
      <option>USER_REPORT</option>
      <option>AUTOMATED_REPORT</option>
    </select>

    <label>Justification comments</label>
    <textarea name="comments" placeholder="Free-form text…"></textarea>

    <label>Platform</label>
    <select name="platform">
      <option value="">(not specified)</option>
      <option>ANDROID</option>
      <option>IOS</option>
      <option>MACOS</option>
      <option>WINDOWS</option>
    </select>

    <label>Region codes (comma-separated ISO-3166-2)</label>
    <input name="regions" placeholder="US,FR">

    <button id="submitBtn" type="submit">Submit to API</button>
  </form>
</div>

<!-- modal -->
<div id="overlay">
  <div class="modal">
    <button class="close-btn" id="closeModal">&times;</button>
    <h2>Please copy the operation name now.</h2>
    <label>Operation name</label>
    <div class="key-row">
      <input id="nameField" readonly>
      <button class="copy-btn" id="copyBtn">Copy</button>
    </div>
  </div>
</div>

<script>
const form     = document.getElementById('submitForm');
const flash    = document.getElementById('flash');
const overlay  = document.getElementById('overlay');
const nameFld  = document.getElementById('nameField');
const copyBtn  = document.getElementById('copyBtn');
const closeBtn = document.getElementById('closeModal');

form.addEventListener('submit', async e => {
  e.preventDefault();
  flash.textContent = '';
  try {
    const resp = await fetch('/submit', {method:'POST', body:new FormData(form)});
    if(!resp.ok) throw new Error(await resp.text() || resp.statusText);
    const data = await resp.json();
    nameFld.value = data.name || '(none)';
    overlay.style.display = 'flex';
    form.reset();
  } catch(err){
    flash.textContent = err.message || 'Request failed';
  }
});

copyBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(nameFld.value);
  copyBtn.classList.add('clicked');
  const oldText = copyBtn.textContent;
  copyBtn.textContent = 'Copied!';
  setTimeout(() => {
    copyBtn.classList.remove('clicked');
    copyBtn.textContent = oldText;
  }, 1200);
});
const hideModal = () => overlay.style.display = 'none';
closeBtn.addEventListener('click', hideModal);
overlay.addEventListener('click', e => { if(e.target === overlay) hideModal(); });
</script>
<div class="issue-msg">
  If you face any issues, please email
  <a href="mailto:mickaelchau@google.com">mickaelchau@google.com</a>
</div>
</body></html>
"""

# ───────────────────────  OPERATIONS PAGE  ───────────────────────────────────
OPS_TEMPLATE = """
<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Web Risk Operations</title>
{{ css|safe }}

<!-- styles used only on the Operations page -->
<style>
:root{
  --bg:#121218; --panel:#2a2a39; --row1:#2e2e3d; --row2:#3a3a49;
  --text:#e8e8e8; --accent:#5981ff; --success:#17c964;
  --warning:#e6c74c; --error:#ff4d4f;
}

/* layout: legend left, ops right */
.ops-wrapper{display:flex;gap:48px;width:100%;align-items:flex-start}

/* ── legend table ── */
.legend-tbl{min-width:420px;border-collapse:collapse}
.legend-tbl thead th{background:var(--panel);color:var(--text);
                     font-size:20px;font-weight:600;padding:14px 18px;text-align:left}
.legend-tbl tbody tr{background:var(--panel)}
.legend-tbl td{padding:14px 18px;vertical-align:top}
.legend-tbl .pill{margin-right:6px}

/* ── operations table ── */
.ops-tbl{width:100%;border-collapse:collapse}
.ops-tbl thead th{background:var(--panel);color:var(--text);
                  padding:14px 18px;text-align:left;font-size:20px;font-weight:600}
.ops-tbl thead tr:first-child th{font-size:32px}
.ops-tbl tbody tr:nth-child(odd){background:var(--row1)}
.ops-tbl tbody tr:nth-child(even){background:var(--row2)}
.ops-tbl td{padding:14px 18px;vertical-align:top}
.status-cell{width:120px}
.expand{cursor:pointer;font-weight:700;user-select:none}
.expand:hover{color:var(--accent)}
pre.json{margin:0;background:var(--panel);padding:20px;border-radius:6px;overflow:auto}
/* make the escalation e-mail appear white */
.legend-tbl a{color:#ffffff;text-decoration:none;font-weight:bold;}
.legend-tbl a:hover{color:var(--accent)}


/* state pills */
.pill{display:inline-block;padding:4px 14px;font-size:12px;font-weight:600;
      border-radius:4px;color:#fff;text-transform:uppercase}
.pill-success{background:var(--success)}
.pill-running{background:var(--warning)}
.pill-closed{ background:var(--error)}
</style>
</head><body>
<a class="top-nav" href="/">← Back</a>

<div class="wrap ops-wrapper">

  <!-- ███  STATE EXPLANATION  (left)  ███ -->
  <table class="legend-tbl">
    <thead><tr><th colspan="2">STATE EXPLANATION</th></tr></thead>
    <tbody>
      <tr>
        <td><span class="pill pill-running">RUNNING</span></td>
        <td>Your URL is currently reviewed by AI or a Human Analyst. It can take up to 24&nbsp;hours to get the final verdict</td>
      </tr>
      <tr>
        <td><span class="pill pill-success">SUCCEEDED</span></td>
        <td>Your URL has been successfully added to the Safe&nbsp;Browsing List</td>
      </tr>
      <tr>
        <td><span class="pill pill-closed">CLOSED</span></td>
        <td>Your URL has been refused. If unexpected, email&nbsp;<a  color: white href="mailto:web-risk-escalations@google.com">web-risk-escalations@google.com</a></td>
      </tr>
    </tbody>
  </table>

  <!-- ███  OPERATIONS TABLE  (right)  ███ -->
  <table class="ops-tbl">
    <thead>
      <tr><th colspan="4">Operations status</th></tr>
      <tr>
        <th style="width:230px">Date&nbsp;&amp;&nbsp;Time</th>
        <th>URI</th>
        <th class="status-cell">State</th>
        <th style="width:110px">Payload</th>
      </tr>
    </thead>
    <tbody>
    {% for op in ops %}
      <tr>
        <td>[{{ op.time }}]</td>
        <td>{{ op.url }}</td>
        <td class="status-cell">
          <span class="pill pill-{{ op.state_class }}">{{ op.state }}</span>
        </td>
        <td class="expand" id="btn-op{{ loop.index }}"
            onclick="toggle({{ loop.index }})">▶</td>
      </tr>
      <tr id="p-op{{ loop.index }}" style="display:none">
        <td colspan="4"><pre class="json">{{ op.payload }}</pre></td>
      </tr>
    {% endfor %}
    </tbody>
  </table>

</div>  <!-- /ops-wrapper -->

<script>
function toggle(idx){
  const row = document.getElementById('p-op'+idx);
  const btn = document.getElementById('btn-op'+idx);
  const open = row.style.display==='table-row';
  row.style.display = open ? 'none' : 'table-row';
  btn.textContent   = open ? '▶' : '▼';
}
</script>
<div class="issue-msg">
  If you face any issues, please email
  <a href="mailto:mickaelchau@google.com">mickaelchau@google.com</a>
</div>

</body></html>
"""




# ─────────────────────────  ROUTES  ──────────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    return render_template_string(MAIN_TEMPLATE, css=CSS)

@app.route("/submit", methods=["POST"])
def submit():
    try:
        proj_num = request.form["parent"].strip()
        uri      = request.form["uri"].strip()
        if not proj_num or not uri:
            return "project number and uri are required", 400

        parent  = f"projects/{proj_num}"
        payload = {"submission": {"uri": uri}}

        # optional helpers
        if request.form.get("abuseType"):
            payload.setdefault("threatInfo", {})["abuseType"] = request.form["abuseType"]

        score = request.form.get("score")
        level = request.form.get("level")
        if score:
            payload.setdefault("threatInfo", {}).setdefault("threatConfidence", {})["score"] = float(score)
        elif level:
            payload.setdefault("threatInfo", {}).setdefault("threatConfidence", {})["level"] = level

        labels   = request.form.getlist("labels")
        comments = request.form.get("comments")
        if labels or comments:
            tj = {}
            if labels:   tj["labels"]   = labels
            if comments: tj["comments"] = [comments]
            payload.setdefault("threatInfo", {})["threatJustification"] = tj

        platform = request.form.get("platform")
        regions  = request.form.get("regions")
        if platform or regions:
            td = {}
            if platform: td["platform"] = platform
            if regions:
                td["regionCodes"] = [r.strip().upper() for r in regions.split(",") if r.strip()]
            payload["threatDiscovery"] = td

        # print payload
        print("\nPayload sent to Web Risk API:")
        print(json.dumps(payload, indent=2), "\n")


        # NEW — build creds from the posted service-account key
        sa_key_raw = request.form["sa_key"].strip()
        try:
            key_info = json.loads(sa_key_raw)
        except json.JSONDecodeError:
            return "Service-account key is not valid JSON", 400

        try:
            creds = service_account.Credentials.from_service_account_info(
                key_info, scopes=SCOPES
            )
            creds.refresh(GoogleRequest())
        except Exception as e:
            return f"Could not use service-account key: {e}", 400

        token = creds.token

        resp = requests.post(
            f"https://webrisk.googleapis.com/v1/{parent}/uris:submit",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=20,
        )

        resp.raise_for_status()
        result = resp.json()

        # append operation name
        op_name = result.get("name")
        if op_name:
            with open("operations", "a", encoding="utf-8") as f:
                f.write(op_name + "\n")
                save_operation(op_name, uri, payload)

        return jsonify(result)
    except Exception as exc:
        return str(exc), 400

@app.route("/operations", methods=["GET"])
def operations_page():
    path = pathlib.Path("operations")
    if not path.exists():
        return "'operations' file not found", 404

    token   = get_access_token()
    # creds, _ = google.auth.default(scopes=SCOPES)
    # creds.refresh(google.auth.transport.requests.Request())
    # token = creds.token
    headers = {"Authorization": f"Bearer {token}"}
    ops_out = []

    for name in list_operations():          # names from Firestore helper
        if not name:
            continue
        try:
            # status from Web Risk
            r = requests.get(f"https://webrisk.googleapis.com/v1/{name}",
                             headers=headers, timeout=20)
            r.raise_for_status()
            data = r.json()

            # additional info from Firestore document
            doc = db.collection(COLL).document(_doc_id(name)).get()
            doc_data = doc.to_dict() or {}
            url      = doc_data.get("url", "(unknown)")
            payload  = json.dumps(doc_data.get("payload", {}), indent=2)

            meta   = data.get("metadata", {})
            iso_ts = meta.get("createTime")
            time_str = "-"
            if iso_ts:
              dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
              # Example: 09 Jul 2025 16:10:21
              time_str = dt.strftime("%d %b %Y %H:%M:%S")


            state = meta.get("state", "UNKNOWN")
            state_class = ("success" if state == "SUCCEEDED"
                           else "running" if state == "RUNNING"
                           else "closed")

            ops_out.append({
                "time": time_str,
                "url": url,
                "payload": payload,
                "state": state,
                "state_class": state_class
            })

        except Exception as exc:
            ops_out.append({
                "time": "-",
                "url": name,
                "payload": f"ERROR: {exc}",
                "state": "ERROR",
                "state_class": "closed"
            })

    return render_template_string(OPS_TEMPLATE, css=CSS, ops=ops_out)


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=8080)

