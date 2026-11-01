"""
Smart Healthcare Project Management & Monitoring System
CSE-494 Software Project Management - Mid-term (CLO-6)

Run the application :  python spms.py
Run the test cases   :  python spms.py --test
Requirements         :  Python 3.8+  (Tkinter + SQLite are built in, nothing to install)

The first run creates spms.db next to this file and loads realistic sample data
based on the case study (5 hospitals, 16 weeks, PKR 5,000,000, 2 pending change requests).
"""
import os
import re
import sys
import math
import sqlite3
from datetime import date, datetime, timedelta

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
except ImportError:          # lets the engine / tests run on machines without Tk
    tk = None

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spms.db")
FMT = "%Y-%m-%d"
ONE = timedelta(days=1)

PRIORITY = ["Critical", "High", "Medium", "Low"]
REQ_STATUS = ["Proposed", "Approved", "Rejected"]
DEFECT_STATUS = ["Open", "In Progress", "Resolved", "Closed"]
CHECK_RESULT = ["Pending", "Pass", "Fail"]
RISK_STATUS = ["Open", "Mitigated", "Occurred", "Closed"]
MS_STATUS = ["Not Started", "In Progress", "Achieved", "Missed"]
WBS_TYPES = ["Project", "Deliverable", "Work Package"]
PROJECT_STATUS = ["Initiating", "Planning", "Executing", "Monitoring & Controlling", "On Hold", "Closed"]


# ============================================================ helpers
def pdate(s):
    return datetime.strptime(str(s), FMT).date()


def today():
    return date.today().strftime(FMT)


def money(x):
    return f"PKR {x:,.0f}"


def fmt_num(v):
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return "" if v is None else str(v)


def risk_level(score):
    return "High" if score >= 15 else "Medium" if score >= 9 else "Low"


def parse_value(f, text):
    """Validate one input value according to its field specification."""
    label = f["label"]
    t = (text or "").strip()
    if t == "":
        if f.get("req", True):
            raise ValueError(f"{label} is required.")
        return None
    k = f["kind"]
    v = t
    if k == "int":
        try:
            v = int(t)
        except ValueError:
            raise ValueError(f"{label} must be a whole number.")
    elif k == "float":
        try:
            v = float(t.replace(",", ""))
        except ValueError:
            raise ValueError(f"{label} must be a number.")
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError(f"{label} must be a valid number.")
    elif k == "date":
        try:
            v = pdate(t).strftime(FMT)
        except ValueError:
            raise ValueError(f"{label} must be a valid date in YYYY-MM-DD format (e.g. 2026-10-26).")
    elif k == "fk":
        try:
            v = int(t.split(" - ")[0])
        except ValueError:
            raise ValueError(f"Please select a valid {label}.")
    elif k == "choice":
        ch = f.get("choices")
        ch = ch() if callable(ch) else ch
        if ch and t not in ch:
            raise ValueError(f"{label} must be one of: {', '.join(ch)}.")
    if k in ("int", "float"):
        if "min" in f and v < f["min"]:
            raise ValueError(f"{label} must be at least {f['min']}.")
        if "max" in f and v > f["max"]:
            raise ValueError(f"{label} must be at most {f['max']}.")
    return v


# ============================================================ database
SCHEMA = """
CREATE TABLE IF NOT EXISTS project(
  id INTEGER PRIMARY KEY CHECK(id=1),
  name TEXT NOT NULL, objectives TEXT, stakeholders TEXT, scope_boundaries TEXT,
  start_date TEXT NOT NULL, original_budget REAL NOT NULL, original_deadline TEXT NOT NULL,
  plan_scope TEXT, plan_schedule TEXT, plan_cost TEXT, plan_quality TEXT,
  status TEXT DEFAULT 'Planning', status_date TEXT,
  cpi_threshold REAL DEFAULT 0.9, spi_threshold REAL DEFAULT 0.9,
  closure_notes TEXT, closed_on TEXT);
CREATE TABLE IF NOT EXISTS team(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, role TEXT NOT NULL, responsibility TEXT);
CREATE TABLE IF NOT EXISTS milestones(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, due_date TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'Not Started', responsible TEXT REFERENCES team(name));
CREATE TABLE IF NOT EXISTS requirements(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT,
  priority TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Proposed');
CREATE TABLE IF NOT EXISTS wbs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  parent_id INTEGER REFERENCES wbs(id), node_type TEXT NOT NULL,
  requirement_id INTEGER REFERENCES requirements(id));
CREATE TABLE IF NOT EXISTS change_requests(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, justification TEXT NOT NULL,
  requirement_id INTEGER REFERENCES requirements(id),
  cost_impact REAL NOT NULL DEFAULT 0 CHECK(cost_impact>=0),
  schedule_impact INTEGER NOT NULL DEFAULT 0 CHECK(schedule_impact>=0),
  status TEXT NOT NULL DEFAULT 'Pending', raised_on TEXT, decided_on TEXT);
CREATE TABLE IF NOT EXISTS activities(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, assignee TEXT REFERENCES team(name),
  duration INTEGER NOT NULL CHECK(duration>0), start_date TEXT NOT NULL, depends_on TEXT,
  planned_cost REAL NOT NULL CHECK(planned_cost>=0),
  percent_complete REAL NOT NULL DEFAULT 0 CHECK(percent_complete BETWEEN 0 AND 100),
  actual_end TEXT, requirement_id INTEGER REFERENCES requirements(id));
CREATE TABLE IF NOT EXISTS expenses(
  id INTEGER PRIMARY KEY AUTOINCREMENT, activity_id INTEGER NOT NULL REFERENCES activities(id),
  amount REAL NOT NULL CHECK(amount>0), spent_on TEXT NOT NULL, description TEXT);
CREATE TABLE IF NOT EXISTS defects(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, activity_id INTEGER REFERENCES activities(id),
  severity TEXT NOT NULL, assigned_to TEXT REFERENCES team(name), status TEXT NOT NULL DEFAULT 'Open',
  reported_on TEXT, resolved_on TEXT);
CREATE TABLE IF NOT EXISTS quality_checks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, deliverable TEXT NOT NULL, check_item TEXT NOT NULL,
  result TEXT NOT NULL DEFAULT 'Pending', tested_by TEXT REFERENCES team(name), test_date TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS risks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, description TEXT NOT NULL,
  likelihood INTEGER NOT NULL CHECK(likelihood BETWEEN 1 AND 5),
  impact INTEGER NOT NULL CHECK(impact BETWEEN 1 AND 5),
  preventive TEXT NOT NULL, corrective TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Open');
"""
TABLES_DROP_ORDER = ["expenses", "defects", "quality_checks", "risks", "change_requests", "wbs",
                     "milestones", "activities", "requirements", "team", "project"]


class DB:
    def __init__(self, path=DB_FILE):
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")

    def run(self, sql, args=()):
        cur = self.con.execute(sql, args)
        self.con.commit()
        return cur

    def all(self, sql, args=()):
        return self.con.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        return self.con.execute(sql, args).fetchone()

    def insert(self, table, values):
        cols = ",".join(values)
        ph = ",".join("?" * len(values))
        return self.run(f"INSERT INTO {table}({cols}) VALUES({ph})", list(values.values())).lastrowid

    def update(self, table, rec_id, values):
        sets = ",".join(f"{k}=?" for k in values)
        self.run(f"UPDATE {table} SET {sets} WHERE id=?", list(values.values()) + [rec_id])

    def delete(self, table, rec_id):
        self.run(f"DELETE FROM {table} WHERE id=?", (rec_id,))

    def many(self, table, cols, rows):
        for r in rows:
            self.insert(table, dict(zip(cols, r)))


def init_schema(db):
    db.con.executescript(SCHEMA)


def project(db):
    return db.one("SELECT * FROM project WHERE id=1")


def baseline(db):
    """Approved budget & deadline = original values + all APPROVED change requests."""
    p = project(db)
    r = db.one("SELECT COALESCE(SUM(cost_impact),0) c, COALESCE(SUM(schedule_impact),0) d "
               "FROM change_requests WHERE status='Approved'")
    return p["original_budget"] + r["c"], pdate(p["original_deadline"]) + timedelta(days=r["d"])


# ============================================================ schedule engine
def dep_list(a):
    txt = (a["depends_on"] or "").replace(" ", "")
    return sorted({int(x) for x in txt.split(",") if x})


def topo_order(acts):
    for a in acts.values():
        for d in dep_list(a):
            if d not in acts:
                raise ValueError(f"Activity {a['id']} depends on unknown activity {d}.")
            if d == a["id"]:
                raise ValueError("An activity cannot depend on itself.")
    indeg = {i: len(dep_list(a)) for i, a in acts.items()}
    ready = sorted(i for i, n in indeg.items() if n == 0)
    order = []
    while ready:
        i = ready.pop(0)
        order.append(i)
        for j, a in acts.items():
            if i in dep_list(a):
                indeg[j] -= 1
                if indeg[j] == 0:
                    ready.append(j)
        ready.sort()
    if len(order) != len(acts):
        raise ValueError("Circular dependency detected between activities.")
    return order


def compute_schedule(db):
    """Baseline (planned) dates by forward pass + forecast dates using progress at the status date."""
    p = project(db)
    sd = pdate(p["status_date"])
    acts = {r["id"]: dict(r) for r in db.all("SELECT * FROM activities")}
    order = topo_order(acts)
    for i in order:                                    # planned (baseline) schedule
        a = acts[i]
        s = pdate(a["start_date"])
        preds = dep_list(a)
        if preds:
            s = max(s, max(acts[d]["end"] for d in preds) + ONE)
        a["start"], a["end"] = s, s + timedelta(days=a["duration"] - 1)
    for i in order:                                    # forecast schedule
        a = acts[i]
        preds = dep_list(a)
        s = pdate(a["start_date"])
        if preds:
            s = max(s, max(acts[d]["f_end"] for d in preds) + ONE)
        e = s + timedelta(days=a["duration"] - 1)
        pct = a["percent_complete"]
        if pct >= 100:
            s = a["start"]
            e = pdate(a["actual_end"]) if a["actual_end"] else a["end"]
        elif s <= sd:                                  # should already be running
            rem = math.ceil(round(a["duration"] * (1 - pct / 100), 6))
            e = max(e, sd + timedelta(days=rem - 1))
        a["f_start"], a["f_end"] = s, e
        a["delay"] = (e - a["end"]).days
        a["inherited"] = (s - a["start"]).days if pct < 100 else 0
        own = a["delay"] - a["inherited"]
        if pct >= 100:
            a["state"] = "Completed Late" if a["delay"] > 0 else "Complete"
        elif own > 0:
            a["state"] = "Delayed"
        elif a["delay"] > 0:
            a["state"] = "Impacted"
        else:
            a["state"] = "On Track"
    rows = [acts[i] for i in sorted(acts)]
    succ = {i: [j for j in acts if i in dep_list(acts[j])] for i in acts}

    def downstream(i):
        seen, stack = [], list(succ[i])
        while stack:
            j = stack.pop()
            if j not in seen:
                seen.append(j)
                stack.extend(succ[j])
        return sorted(seen)

    delayed = [a for a in rows if a["state"] in ("Delayed", "Completed Late")]
    for a in delayed:
        a["affected"] = [acts[j] for j in downstream(a["id"]) if acts[j]["delay"] > 0]
    _, deadline = baseline(db)
    planned_end = max((a["end"] for a in rows), default=None)
    forecast_end = max((a["f_end"] for a in rows), default=None)
    overrun = (forecast_end - deadline).days if forecast_end else 0
    return dict(rows=rows, status_date=sd, planned_end=planned_end, forecast_end=forecast_end,
                deadline=deadline, overrun=overrun, delayed=delayed)


# ============================================================ cost / EVM engine
def compute_evm(db):
    s = compute_schedule(db)
    p = project(db)
    sd = s["status_date"]
    bac = pv = ev = 0.0
    for a in s["rows"]:
        c = a["planned_cost"]
        bac += c
        ev += c * a["percent_complete"] / 100
        if sd >= a["end"]:
            frac = 1
        elif sd < a["start"]:
            frac = 0
        else:
            frac = ((sd - a["start"]).days + 1) / a["duration"]
        pv += c * frac
    ac = db.one("SELECT COALESCE(SUM(amount),0) t FROM expenses")["t"]
    cpi = ev / ac if ac > 0 else None
    spi = ev / pv if pv > 0 else None
    eac = bac / cpi if cpi else bac
    budget, deadline = baseline(db)
    warns = []
    if cpi is not None and cpi < p["cpi_threshold"]:
        warns.append(f"COST OVERRUN: CPI {cpi:.2f} is below the threshold {p['cpi_threshold']:.2f} "
                     f"(spent {money(ac)} for work worth {money(ev)}).")
    if spi is not None and spi < p["spi_threshold"]:
        warns.append(f"SCHEDULE DEVIATION: SPI {spi:.2f} is below the threshold {p['spi_threshold']:.2f} "
                     f"(only {money(ev)} earned against {money(pv)} planned).")
    if bac > budget:
        warns.append(f"BUDGET: planned cost {money(bac)} exceeds approved budget {money(budget)}.")
    if ac > budget:
        warns.append(f"BUDGET: actual cost {money(ac)} exceeds approved budget {money(budget)}.")
    if eac > budget:
        warns.append(f"FORECAST: estimate at completion {money(eac)} exceeds approved budget {money(budget)} "
                     f"by {money(eac - budget)}.")
    if s["overrun"] > 0:
        warns.append(f"DEADLINE: forecast finish {s['forecast_end']} is {s['overrun']} day(s) after the "
                     f"deadline {deadline}.")
    return dict(bac=bac, pv=pv, ev=ev, ac=ac, cpi=cpi, spi=spi, cv=ev - ac, sv=ev - pv,
                eac=eac, etc=eac - ac, vac=bac - eac, budget=budget, warnings=warns)


# ============================================================ change control / scope
def decide_cr(db, cr_id, decision):
    cr = db.one("SELECT * FROM change_requests WHERE id=?", (cr_id,))
    if not cr:
        raise ValueError("Change request not found.")
    if cr["status"] != "Pending":
        raise ValueError("This change request has already been decided.")
    b0, d0 = baseline(db)
    db.update("change_requests", cr_id, {"status": decision, "decided_on": today()})
    lines = []
    req = db.one("SELECT * FROM requirements WHERE id=?", (cr["requirement_id"],)) if cr["requirement_id"] else None
    if decision == "Approved":
        if req:
            db.update("requirements", req["id"], {"status": "Approved"})
            lines.append(f"SCOPE: requirement {req['id']} '{req['title']}' is now APPROVED and part of the project scope.")
        b1, d1 = baseline(db)
        sch = compute_schedule(db)
        lines.append(f"BUDGET: {money(b0)} -> {money(b1)}  (+{money(b1 - b0)})")
        lines.append(f"DEADLINE: {d0} -> {d1}  (+{(d1 - d0).days} days)")
        if sch["overrun"] > 0:
            lines.append(f"Forecast finish {sch['forecast_end']} is still {sch['overrun']} day(s) after the new deadline.")
        else:
            lines.append(f"Forecast finish {sch['forecast_end']} is within the new deadline.")
        lines.append("Tip: use 'Auto-generate WBS' to add the newly approved scope to the WBS.")
    else:
        if req and req["status"] == "Proposed":
            db.update("requirements", req["id"], {"status": "Rejected"})
            lines.append(f"SCOPE: requirement {req['id']} '{req['title']}' is REJECTED and stays out of scope.")
        lines.append("Budget and deadline are unchanged.")
    return f"Change request {cr_id} {decision.upper()}.\n\n" + "\n".join(lines)


def generate_wbs(db):
    p = project(db)
    root = db.one("SELECT * FROM wbs WHERE parent_id IS NULL ORDER BY id")
    if not root:
        db.insert("wbs", dict(code="1", name=p["name"], parent_id=None, node_type="Project", requirement_id=None))
        root = db.one("SELECT * FROM wbs WHERE parent_id IS NULL ORDER BY id")
    created = 0
    for r in db.all("SELECT * FROM requirements WHERE status='Approved' ORDER BY id"):
        if db.one("SELECT 1 FROM wbs WHERE requirement_id=? AND node_type='Deliverable'", (r["id"],)):
            continue
        n = db.one("SELECT COUNT(*) c FROM wbs WHERE parent_id=?", (root["id"],))["c"] + 1
        while db.one("SELECT 1 FROM wbs WHERE code=?", (f"{root['code']}.{n}",)):
            n += 1
        code = f"{root['code']}.{n}"
        did = db.insert("wbs", dict(code=code, name=r["title"], parent_id=root["id"],
                                    node_type="Deliverable", requirement_id=r["id"]))
        for k, nm in enumerate(["Design & Develop", "Test & Verify"], 1):
            db.insert("wbs", dict(code=f"{code}.{k}", name=f"{nm}: {r['title']}", parent_id=did,
                                  node_type="Work Package", requirement_id=r["id"]))
        created += 1
    return created


def close_project(db, notes):
    if not (notes or "").strip():
        raise ValueError("Closure notes are required to close the project.")
    problems = []
    n = db.one("SELECT COUNT(*) n FROM activities WHERE percent_complete<100")["n"]
    if n:
        problems.append(f"{n} activit{'y is' if n == 1 else 'ies are'} not 100% complete")
    n = db.one("SELECT COUNT(*) n FROM defects WHERE severity='Critical' AND status NOT IN ('Resolved','Closed')")["n"]
    if n:
        problems.append(f"{n} critical defect(s) are unresolved")
    n = db.one("SELECT COUNT(*) n FROM change_requests WHERE status='Pending'")["n"]
    if n:
        problems.append(f"{n} change request(s) are still pending")
    if problems:
        raise ValueError("Project cannot be closed:\n - " + "\n - ".join(problems))
    db.update("project", 1, {"status": "Closed", "closed_on": today(), "closure_notes": notes.strip()})


# ============================================================ validators (consistency rules)
def _exists(db, table, rid, what):
    if rid is not None and not db.one(f"SELECT 1 FROM {table} WHERE id=?", (rid,)):
        raise ValueError(f"{what} {rid} does not exist.")


def _approved_req(db, rid, what="A task"):
    if rid is None:
        return
    r = db.one("SELECT * FROM requirements WHERE id=?", (rid,))
    if not r:
        raise ValueError(f"Requirement {rid} does not exist.")
    if r["status"] != "Approved":
        raise ValueError(f"Requirement {rid} '{r['title']}' is {r['status']}, not Approved. {what} cannot use "
                         f"unapproved scope - submit and approve a Change Request first.")


def _team(db, name):
    if name and not db.one("SELECT 1 FROM team WHERE name=?", (name,)):
        raise ValueError(f"'{name}' is not a member of the project team.")


def v_requirement(db, v, rid, op):
    if op == "add":
        return
    used = db.one("SELECT (SELECT COUNT(*) FROM wbs WHERE requirement_id=:i)+"
                  "(SELECT COUNT(*) FROM activities WHERE requirement_id=:i) n", {"i": rid})["n"]
    if op == "delete":
        if used or db.one("SELECT 1 FROM change_requests WHERE requirement_id=?", (rid,)):
            raise ValueError("This requirement is used by WBS items, activities or change requests and cannot be deleted.")
    elif v["status"] != "Approved" and used:
        raise ValueError("This requirement is already used by WBS items/activities, so it must stay Approved.")


def v_cr(db, v, rid, op):
    if op != "add":
        if db.one("SELECT status FROM change_requests WHERE id=?", (rid,))["status"] != "Pending":
            raise ValueError("Only Pending change requests can be edited or deleted (decided ones form the audit trail).")
    if op != "delete":
        _exists(db, "requirements", v["requirement_id"], "Requirement")


def v_wbs(db, v, rid, op):
    if op == "delete":
        if db.one("SELECT 1 FROM wbs WHERE parent_id=?", (rid,)):
            raise ValueError("Delete the child WBS items first.")
        return
    if not re.fullmatch(r"\d+(\.\d+)*", v["code"]):
        raise ValueError("WBS code must look like 1, 1.2 or 1.2.3")
    if v["parent_id"] is not None:
        par = db.one("SELECT * FROM wbs WHERE id=?", (v["parent_id"],))
        if not par:
            raise ValueError("Parent WBS item does not exist.")
        cur = par
        while rid is not None and cur:
            if cur["id"] == rid:
                raise ValueError("A WBS item cannot be its own parent or descendant.")
            cur = db.one("SELECT * FROM wbs WHERE id=?", (cur["parent_id"],)) if cur["parent_id"] else None
        if not v["code"].startswith(par["code"] + "."):
            raise ValueError(f"Code must start with the parent's code ({par['code']}.)")
    elif db.one("SELECT 1 FROM wbs WHERE parent_id IS NULL AND id IS NOT ?", (rid,)):
        raise ValueError("Only one root WBS item is allowed; choose a parent.")
    _approved_req(db, v["requirement_id"], "A WBS item")


def v_activity(db, v, rid, op):
    if op == "delete":
        for a in db.all("SELECT id, depends_on FROM activities"):
            if rid in dep_list(a):
                raise ValueError(f"Activity {a['id']} depends on this activity. Remove that dependency first.")
        if db.one("SELECT 1 FROM expenses WHERE activity_id=?", (rid,)) or \
                db.one("SELECT 1 FROM defects WHERE activity_id=?", (rid,)):
            raise ValueError("Expenses or defects are recorded against this activity, so it cannot be deleted.")
        return
    if pdate(v["start_date"]) < pdate(project(db)["start_date"]):
        raise ValueError("Activity start date cannot be before the project start date.")
    dep = v["depends_on"]
    if dep and not re.fullmatch(r"\s*\d+(\s*,\s*\d+)*\s*", dep):
        raise ValueError("Dependencies must be activity IDs separated by commas, e.g. 2,3")
    _team(db, v["assignee"])
    _approved_req(db, v["requirement_id"])
    if v["actual_end"] and v["percent_complete"] < 100:
        raise ValueError("Actual end date can only be entered when the activity is 100% complete.")
    if v["actual_end"] and pdate(v["actual_end"]) < pdate(v["start_date"]):
        raise ValueError("Actual end date cannot be before the start date.")
    acts = {r["id"]: dict(r) for r in db.all("SELECT * FROM activities")}
    key = rid if rid is not None else -1
    acts[key] = dict(v, id=key)
    topo_order(acts)                                   # unknown ids / self / circular dependencies
    budget, _ = baseline(db)
    total = sum(a["planned_cost"] for a in acts.values())
    if total > budget + 1e-6:
        raise ValueError(f"Total planned cost {money(total)} would exceed the approved budget {money(budget)}. "
                         f"Raise and approve a Change Request to increase the budget first.")


def v_expense(db, v, rid, op):
    if op == "delete":
        return
    _exists(db, "activities", v["activity_id"], "Activity")
    if pdate(v["spent_on"]) < pdate(project(db)["start_date"]):
        raise ValueError("Expense date cannot be before the project start date.")


def v_defect(db, v, rid, op):
    if op == "delete":
        return
    _team(db, v["assigned_to"])
    _exists(db, "activities", v["activity_id"], "Activity")
    if v["severity"] in ("Critical", "High") and not v["assigned_to"]:
        raise ValueError("Critical and High severity defects must be assigned to a team member.")
    old = db.one("SELECT resolved_on FROM defects WHERE id=?", (rid,)) if rid else None
    if v["status"] in ("Resolved", "Closed"):
        v["resolved_on"] = (old["resolved_on"] if old and old["resolved_on"] else today())
    else:
        v["resolved_on"] = None


def v_check(db, v, rid, op):
    if op == "delete":
        return
    _team(db, v["tested_by"])
    if v["result"] in ("Pass", "Fail") and (not v["tested_by"] or not v["test_date"]):
        raise ValueError("A Pass/Fail inspection result needs the inspector (Tested by) and the test date.")


def v_milestone(db, v, rid, op):
    if op == "delete":
        return
    _team(db, v["responsible"])
    _, dl = baseline(db)
    d = pdate(v["due_date"])
    if d < pdate(project(db)["start_date"]) or d > dl:
        raise ValueError(f"Milestone date must be between the project start and the approved deadline ({dl}).")


# ============================================================ report
def build_report(db):
    p = project(db)
    sch = compute_schedule(db)
    evm = compute_evm(db)
    budget, deadline = baseline(db)
    rows = sch["rows"]
    tot = sum(a["duration"] for a in rows)
    progress = sum(a["duration"] * a["percent_complete"] for a in rows) / tot if tot else 0
    pending = db.all("SELECT * FROM change_requests WHERE status='Pending'")
    crit = db.all("SELECT * FROM defects WHERE severity='Critical' AND status NOT IN ('Resolved','Closed')")
    open_def = db.one("SELECT COUNT(*) n FROM defects WHERE status NOT IN ('Resolved','Closed')")["n"]
    qc = db.one("SELECT SUM(result='Pass') p, SUM(result='Fail') f, COUNT(*) n FROM quality_checks")
    ms = db.all("SELECT * FROM milestones ORDER BY due_date")
    missed = [m for m in ms if m["status"] != "Achieved" and pdate(m["due_date"]) < sch["status_date"]]
    risks = db.all("SELECT * FROM risks WHERE status IN ('Open','Occurred') ORDER BY likelihood*impact DESC, id")
    reqs = {r["status"]: r["n"] for r in db.all("SELECT status, COUNT(*) n FROM requirements GROUP BY status")}
    return dict(p=p, sch=sch, evm=evm, budget=budget, deadline=deadline, progress=progress, pending=pending,
                crit=crit, open_def=open_def, qc=qc, ms=ms, missed=missed, risks=risks, reqs=reqs)


def report_text(db):
    r = build_report(db)
    p, s, e = r["p"], r["sch"], r["evm"]
    L = []
    add = L.append
    add("== PROJECT STATUS REPORT ==")
    add(f"Project : {p['name']}")
    add(f"Status  : {p['status']}      Status date: {s['status_date']}")
    add(f"Overall progress: {r['progress']:.1f}%")
    add("")
    add("== SCHEDULE ==")
    add(f"Start {p['start_date']} | Approved deadline {r['deadline']} (original {p['original_deadline']})")
    add(f"Planned finish {s['planned_end']} | Forecast finish {s['forecast_end']}")
    if s["overrun"] > 0:
        add(f"[!] Forecast finish is {s['overrun']} day(s) AFTER the deadline.")
    else:
        add("Forecast finish is within the deadline.")
    add(f"Delayed activities: {len(s['delayed'])}")
    for a in s["delayed"]:
        aff = ", ".join(f"#{x['id']}" for x in a["affected"]) or "none"
        add(f"[!] #{a['id']} {a['name']} - late by {a['delay']} day(s); delays dependants: {aff}")
    add("")
    add("== BUDGET & EARNED VALUE ==")
    add(f"Approved budget {money(r['budget'])} (original {money(p['original_budget'])}) | Planned cost (BAC) {money(e['bac'])}")
    add(f"PV {money(e['pv'])} | EV {money(e['ev'])} | AC {money(e['ac'])}")
    add(f"CPI {e['cpi']:.2f} | SPI {e['spi']:.2f} | CV {money(e['cv'])} | SV {money(e['sv'])}"
        if e["cpi"] is not None and e["spi"] is not None else "CPI / SPI not available yet.")
    add(f"EAC {money(e['eac'])} | ETC {money(e['etc'])} | VAC {money(e['vac'])}")
    for w in e["warnings"]:
        add(f"[!] {w}")
    add("")
    add("== SCOPE & CHANGE REQUESTS ==")
    add("Requirements: " + ", ".join(f"{k} {v}" for k, v in sorted(r["reqs"].items())))
    add(f"Pending change requests: {len(r['pending'])}")
    for c in r["pending"]:
        add(f"[!] CR{c['id']} {c['title']} - +{money(c['cost_impact'])}, +{c['schedule_impact']} days (awaiting decision)")
    add("")
    add("== QUALITY ==")
    add(f"Open defects: {r['open_def']} | Unresolved CRITICAL defects: {len(r['crit'])}")
    for d in r["crit"]:
        add(f"[!] D{d['id']} {d['title']} (assigned to {d['assigned_to']}, {d['status']})")
    q = r["qc"]
    add(f"Quality checklist: {q['p'] or 0} passed, {q['f'] or 0} failed, of {q['n']} items")
    add("")
    add("== MILESTONES ==")
    for m in r["ms"]:
        flag = "[!] " if m in r["missed"] else ""
        add(f"{flag}{m['due_date']}  {m['name']}  [{m['status']}]")
    add("")
    add("== TOP RISKS ==")
    for k in r["risks"][:3]:
        sc = k["likelihood"] * k["impact"]
        add(f"R{k['id']} [{risk_level(sc)}, score {sc}] {k['description']}")
    return "\n".join(L)


# ============================================================ sample data
def reset_db(db):
    db.con.execute("PRAGMA foreign_keys = OFF")
    for t in TABLES_DROP_ORDER:
        db.con.execute(f"DROP TABLE IF EXISTS {t}")
    db.con.commit()
    db.con.execute("PRAGMA foreign_keys = ON")
    init_schema(db)


def seed(db):
    reset_db(db)
    db.insert("project", dict(
        id=1, name="Smart Healthcare Project Management and Monitoring System",
        objectives="Deliver an integrated system for a network of five hospitals covering patient appointments, "
                   "laboratory reports, doctor schedules, online consultations and hospital billing within 16 weeks "
                   "and PKR 5,000,000.",
        stakeholders="Hospital Management (Sponsor); Doctors; Patients; Laboratory staff; Billing department; "
                     "Project Manager; Development Team; QA Engineer",
        scope_boundaries="IN: appointments, lab reports, doctor schedules, online consultation, billing, patient records, "
                         "web portals. OUT: pharmacy, payroll/HR, medical device integration. New items only via approved "
                         "Change Requests.",
        start_date="2026-08-31", original_budget=5000000, original_deadline="2026-12-20",
        plan_scope="Approved requirements R1-R10 decomposed into the WBS (deliverables and work packages).",
        plan_schedule="16 weeks, finish-to-start dependencies, weekly progress review, milestones M1-M5.",
        plan_cost="Budget PKR 5,000,000; activity-level cost estimates; EVM tracked weekly (CPI/SPI threshold 0.90).",
        plan_quality="Code review, unit and system testing, quality checklist per deliverable, zero critical defects at release.",
        status="Executing", status_date="2026-10-26", cpi_threshold=0.9, spi_threshold=0.9))
    db.many("team", ["name", "role", "responsibility"], [
        ("Ahmed Raza", "Project Manager", "Planning, monitoring, stakeholder communication"),
        ("Usman Ali", "Backend Developer", "Appointment and billing services"),
        ("Sara Malik", "Backend Developer", "Lab reports, doctor schedule, consultation services"),
        ("Hina Tariq", "Frontend Developer", "Web portals"),
        ("Zain Abbas", "Frontend Developer", "Integration and UI"),
        ("Imran Sheikh", "Database Developer", "Schema design and database implementation"),
        ("Fatima Noor", "QA Engineer", "Test planning, defect tracking, inspections")])
    db.many("requirements", ["title", "description", "priority", "status"], [
        ("Patient appointment management", "Book, reschedule, cancel appointments", "Critical", "Approved"),
        ("Laboratory report management", "Upload, view and share lab reports", "High", "Approved"),
        ("Doctor schedule management", "Doctor availability and rosters", "High", "Approved"),
        ("Online consultation", "Video/chat consultation sessions", "High", "Approved"),
        ("Hospital billing and invoicing", "Invoices, payments, receipts", "High", "Approved"),
        ("Patient record management", "Central patient history and records", "Critical", "Approved"),
        ("Role-based security and login", "Access control and audit log", "High", "Approved"),
        ("Multi-hospital network support", "One system for five hospitals", "Medium", "Approved"),
        ("Web portals for patients and staff", "Responsive web user interface", "High", "Approved"),
        ("Management reports", "Operational reports for hospital management", "Medium", "Approved"),
        ("Mobile application", "Patient mobile app (new request)", "Medium", "Proposed"),
        ("AI-based preliminary diagnosis module", "Symptom-based preliminary diagnosis (new request)", "Medium", "Proposed")])
    cols = ["name", "assignee", "duration", "start_date", "depends_on", "planned_cost", "percent_complete",
            "actual_end", "requirement_id"]
    s0 = "2026-08-31"
    db.many("activities", cols, [
        ("Requirements Analysis & Project Planning", "Ahmed Raza", 10, s0, None, 300000, 100, "2026-09-09", 8),
        ("System Architecture & Database Design", "Imran Sheikh", 10, s0, "1", 400000, 100, "2026-09-19", 6),
        ("Database Implementation", "Imran Sheikh", 12, s0, "2", 450000, 100, "2026-10-01", 6),
        ("Appointment Scheduling Module", "Usman Ali", 18, s0, "2", 600000, 80, None, 1),
        ("Laboratory Reports Module", "Sara Malik", 15, s0, "3", 500000, 100, "2026-10-16", 2),
        ("Doctor Schedule & Online Consultation", "Sara Malik", 15, s0, "5", 550000, 40, None, 3),
        ("Hospital Billing Module", "Usman Ali", 20, s0, "4", 450000, 0, None, 5),
        ("Web Frontend (Patient & Staff Portals)", "Hina Tariq", 25, s0, "2", 700000, 50, None, 9),
        ("System Integration", "Zain Abbas", 10, s0, "6,7,8", 400000, 0, None, 8),
        ("System Testing & QA", "Fatima Noor", 18, s0, "9", 400000, 0, None, 7),
        ("Deployment & Staff Training", "Ahmed Raza", 8, s0, "10", 150000, 0, None, None)])
    db.many("expenses", ["activity_id", "amount", "spent_on", "description"], [
        (1, 310000, "2026-09-09", "Analysis and planning effort"),
        (2, 410000, "2026-09-19", "Architecture and DB design"),
        (3, 470000, "2026-10-01", "Database implementation"),
        (4, 560000, "2026-10-20", "Appointment module development"),
        (5, 520000, "2026-10-16", "Laboratory module development"),
        (6, 260000, "2026-10-24", "Doctor schedule development (in progress)"),
        (8, 520000, "2026-10-24", "Frontend development (in progress)")])
    db.many("defects", ["title", "activity_id", "severity", "assigned_to", "status", "reported_on", "resolved_on"], [
        ("Double booking of appointment slots", 4, "Critical", "Usman Ali", "Open", "2026-10-22", None),
        ("Patient record not saved after update", 3, "Critical", "Imran Sheikh", "In Progress", "2026-10-23", None),
        ("Doctor schedule overlap not detected", 6, "High", "Sara Malik", "Open", "2026-10-24", None),
        ("Lab report PDF export is truncated", 5, "Medium", "Sara Malik", "Resolved", "2026-10-15", "2026-10-20"),
        ("Date picker shows wrong format", 8, "Low", "Hina Tariq", "Closed", "2026-10-10", "2026-10-12")])
    db.many("quality_checks", ["deliverable", "check_item", "result", "tested_by", "test_date", "notes"], [
        ("Appointment Module", "Overlapping appointments are blocked", "Fail", "Fatima Noor", "2026-10-22", "Double booking found"),
        ("Appointment Module", "Reschedule and cancel work correctly", "Pass", "Fatima Noor", "2026-10-22", None),
        ("Patient Record Management", "Create/update persists data", "Fail", "Fatima Noor", "2026-10-23", "Update lost"),
        ("Patient Record Management", "Mandatory field validation", "Pass", "Fatima Noor", "2026-10-23", None),
        ("Laboratory Reports Module", "Report linked to correct patient", "Pass", "Fatima Noor", "2026-10-18", None),
        ("Laboratory Reports Module", "Upload format validation", "Pass", "Fatima Noor", "2026-10-18", None),
        ("Web Frontend", "Responsive on three browsers", "Pending", None, None, None)])
    db.many("risks", ["description", "likelihood", "impact", "preventive", "corrective", "status"], [
        ("Scope creep from new hospital requirements", 4, 4, "Strict change control; baseline approved scope",
         "Re-baseline budget and schedule after approved change request", "Open"),
        ("Critical defects in appointment scheduling", 4, 5, "Code reviews, unit tests, early QA involvement",
         "Hot-fix sprint and regression testing before release", "Occurred"),
        ("Patient data privacy breach", 2, 5, "Encryption, role-based access, security audit",
         "Incident response plan, patch and notify hospital management", "Open"),
        ("AI diagnosis accuracy not accepted by doctors", 3, 4, "Prototype with clinicians; validated datasets",
         "Limit to decision-support only and defer advanced features", "Open"),
        ("Budget overrun caused by new requirements", 4, 3, "Weekly EVM tracking; contingency reserve",
         "Request additional funding or de-scope low-priority items", "Open"),
        ("Key developer unavailable", 2, 3, "Cross-training and documentation",
         "Re-allocate tasks or hire a short-term contractor", "Open"),
        ("Delay integrating with hospital networks", 3, 3, "Set up integration environment early",
         "Escalate to hospital IT; use mock services meanwhile", "Open")])
    db.many("change_requests", ["title", "justification", "requirement_id", "cost_impact", "schedule_impact",
                                "status", "raised_on", "decided_on"], [
        ("Add mobile application", "Hospital management wants patients to book appointments from phones.",
         11, 300000, 7, "Pending", "2026-10-05", None),
        ("Add AI-based preliminary diagnosis module", "Hospital management wants symptom-based preliminary diagnosis.",
         12, 500000, 14, "Pending", "2026-10-12", None)])
    db.many("milestones", ["name", "due_date", "status", "responsible"], [
        ("M1 Requirements baseline approved", "2026-09-09", "Achieved", "Ahmed Raza"),
        ("M2 Design complete", "2026-09-19", "Achieved", "Imran Sheikh"),
        ("M3 Backend modules complete", "2026-10-31", "In Progress", "Usman Ali"),
        ("M4 System integration complete", "2026-11-10", "Not Started", "Zain Abbas"),
        ("M5 Go-live and handover", "2026-12-20", "Not Started", "Ahmed Raza")])
    generate_wbs(db)


def ensure_db(path=DB_FILE):
    db = DB(path)
    init_schema(db)
    if not project(db):
        seed(db)
    return db


# ============================================================ test cases
def run_test_cases():
    db = DB(":memory:")
    init_schema(db)
    seed(db)
    out = []

    def case(desc, expected, fn):
        try:
            actual = fn()
        except Exception as ex:
            actual = f"Error: {ex}"
        out.append((f"TC{len(out) + 1:02d}", desc, str(expected), str(actual),
                    "PASS" if str(expected) == str(actual) else "FAIL"))

    def rejected(fn):
        try:
            fn()
            return "Accepted"
        except ValueError:
            return "Rejected"

    def act(i):
        return next(a for a in compute_schedule(db)["rows"] if a["id"] == i)

    def avals(aid=None, **chg):
        base = dict(name="Extra Task", assignee="Ahmed Raza", duration=5, start_date="2026-09-01", depends_on=None,
                    planned_cost=100000, percent_complete=0, actual_end=None, requirement_id=1)
        if aid:
            r = db.one("SELECT * FROM activities WHERE id=?", (aid,))
            base = {k: r[k] for k in base}
        base.update(chg)
        return base

    case("Initial approved budget and deadline", "5,000,000 | 2026-12-20",
         lambda: f"{baseline(db)[0]:,.0f} | {baseline(db)[1]}")
    case("Activity 1 planned finish (10 days from 2026-08-31)", "2026-09-09", lambda: act(1)["end"])
    case("Dependency scheduling: activity 9 starts after 6, 7, 8 finish", "2026-11-01", lambda: act(9)["start"])
    case("Planned project finish date", "2026-12-06", lambda: compute_schedule(db)["planned_end"])
    case("Delayed activities at status date 2026-10-26", "[4, 6, 8]",
         lambda: [a["id"] for a in compute_schedule(db)["delayed"]])
    case("Dependent activities identified as impacted", "[7, 9, 10, 11]",
         lambda: [a["id"] for a in compute_schedule(db)["rows"] if a["state"] == "Impacted"])
    case("Delay of activity 4 (days)", 22, lambda: act(4)["delay"])
    case("Activities impacted by delay of activity 4", "[7, 9, 10, 11]",
         lambda: [x["id"] for x in next(a for a in compute_schedule(db)["delayed"] if a["id"] == 4)["affected"]])
    case("Forecast project finish", "2026-12-24", lambda: compute_schedule(db)["forecast_end"])
    case("Forecast overrun against deadline (days)", 4, lambda: compute_schedule(db)["overrun"])
    case("Total planned budget (BAC)", "4,900,000", lambda: f"{compute_evm(db)['bac']:,.0f}")
    case("Planned Value (PV)", "3,744,167", lambda: f"{compute_evm(db)['pv']:,.0f}")
    case("Earned Value (EV)", "2,700,000", lambda: f"{compute_evm(db)['ev']:,.0f}")
    case("Actual Cost (AC)", "3,050,000", lambda: f"{compute_evm(db)['ac']:,.0f}")
    case("CPI = EV / AC", "0.885", lambda: f"{compute_evm(db)['cpi']:.3f}")
    case("SPI = EV / PV", "0.721", lambda: f"{compute_evm(db)['spi']:.3f}")
    case("Cost overrun warning raised (CPI below threshold)", "Yes",
         lambda: "Yes" if any(w.startswith("COST OVERRUN") for w in compute_evm(db)["warnings"]) else "No")
    case("Schedule deviation warning raised (SPI below threshold)", "Yes",
         lambda: "Yes" if any(w.startswith("SCHEDULE DEVIATION") for w in compute_evm(db)["warnings"]) else "No")
    case("Circular dependency rejected (1 depends on 11)", "Rejected",
         lambda: rejected(lambda: v_activity(db, avals(1, depends_on="11"), 1, "update")))
    case("Unknown dependency rejected (depends on 99)", "Rejected",
         lambda: rejected(lambda: v_activity(db, avals(depends_on="99"), None, "add")))
    case("Activity using unapproved requirement (R11) rejected", "Rejected",
         lambda: rejected(lambda: v_activity(db, avals(requirement_id=11), None, "add")))
    case("WBS item using unapproved requirement (R12) rejected", "Rejected",
         lambda: rejected(lambda: v_wbs(db, dict(code="1.20", name="AI", parent_id=1, node_type="Deliverable",
                                                requirement_id=12), None, "add")))
    case("Activity exceeding approved budget (5,100,000 > 5,000,000) rejected", "Rejected",
         lambda: rejected(lambda: v_activity(db, avals(planned_cost=200000), None, "add")))
    case("Invalid date '2026-13-45' rejected", "Rejected",
         lambda: rejected(lambda: parse_value(dict(label="Date", kind="date"), "2026-13-45")))
    case("Negative cost rejected", "Rejected",
         lambda: rejected(lambda: parse_value(dict(label="Cost", kind="float", min=0), "-5")))
    case("Deleting an activity that others depend on is rejected", "Rejected",
         lambda: rejected(lambda: v_activity(db, {}, 2, "delete")))
    case("Defect assigned to a non-team member rejected", "Rejected",
         lambda: rejected(lambda: v_defect(db, dict(title="x", activity_id=4, severity="Low", assigned_to="Nobody",
                                                   status="Open"), None, "add")))
    case("Pass result without inspector/date rejected", "Rejected",
         lambda: rejected(lambda: v_check(db, dict(deliverable="x", check_item="y", result="Pass", tested_by=None,
                                                  test_date=None, notes=None), None, "add")))
    case("Dashboard: pending change requests", 2, lambda: len(build_report(db)["pending"]))
    case("Dashboard: unresolved critical defects", 2, lambda: len(build_report(db)["crit"]))
    case("Risk prioritisation: highest score first", "R2 (20)",
         lambda: (lambda r: f"R{r['id']} ({r['likelihood'] * r['impact']})")(build_report(db)["risks"][0]))
    case("Closing project blocked by open critical defects", "Rejected",
         lambda: rejected(lambda: close_project(db, "Closing")))
    case("Approve CR1 (mobile app): new budget | new deadline", "5,300,000 | 2026-12-27",
         lambda: (decide_cr(db, 1, "Approved"), f"{baseline(db)[0]:,.0f} | {baseline(db)[1]}")[1])
    case("Approved CR moves requirement 11 into scope", "Approved",
         lambda: db.one("SELECT status FROM requirements WHERE id=11")["status"])
    case("Approve CR2 (AI module): total +PKR 800,000 and +21 days", "5,800,000 | 2027-01-10",
         lambda: (decide_cr(db, 2, "Approved"), f"{baseline(db)[0]:,.0f} | {baseline(db)[1]}")[1])
    case("Deadline overrun cleared after approved schedule impact", 0,
         lambda: max(0, compute_schedule(db)["overrun"]))
    case("Same change request cannot be decided twice", "Rejected",
         lambda: rejected(lambda: decide_cr(db, 1, "Approved")))
    case("Decided change request is locked from editing", "Rejected",
         lambda: rejected(lambda: v_cr(db, dict(requirement_id=11), 1, "update")))
    case("Task using newly approved requirement and larger budget accepted", "Accepted",
         lambda: rejected(lambda: v_activity(db, avals(requirement_id=11, planned_cost=200000), None, "add")))
    case("Auto WBS adds deliverables for newly approved scope", 2, lambda: generate_wbs(db))
    return out


# ============================================================ GUI
if tk is not None:
    TAGS = {"red": "#fde0dc", "orange": "#ffe9cc", "green": "#e0f2e1", "grey": "#eeeeee"}

    def friendly(e):
        m = str(e)
        if "FOREIGN KEY" in m:
            return "This record is linked to other records (tasks, defects, WBS, ...). Remove or change those links first."
        if "UNIQUE" in m:
            return "A record with this value already exists."
        return m

    class CrudTab(ttk.Frame):
        """Generic form + table with Add / Update / Delete, validation and database persistence."""

        def __init__(self, parent, app, table, fields, validator=None, order="id", actions=(), per_row=2,
                     hier=False, tag_fn=None, height=9, footer=None):
            super().__init__(parent)
            self.app, self.db, self.table = app, app.db, table
            self.fields, self.validator, self.order = fields, validator, order
            self.hier, self.tag_fn, self.footer = hier, tag_fn, footer
            app.tabs.append(self)
            self.vars, self.combos = {}, {}
            form = ttk.Frame(self)
            form.pack(fill="x", padx=8, pady=(8, 2))
            for n, f in enumerate([f for f in fields if f.get("form", True)]):
                r, c = divmod(n, per_row)
                ttk.Label(form, text=f["label"] + ("" if f.get("req", True) else " (optional)")).grid(
                    row=r, column=2 * c, sticky="e", padx=(10, 4), pady=2)
                var = tk.StringVar()
                self.vars[f["name"]] = var
                if f["kind"] in ("choice", "fk"):
                    w = ttk.Combobox(form, textvariable=var, state="readonly", width=36)
                    self.combos[f["name"]] = w
                else:
                    w = ttk.Entry(form, textvariable=var, width=39)
                w.grid(row=r, column=2 * c + 1, sticky="w", pady=2)
            bar = ttk.Frame(self)
            bar.pack(fill="x", padx=8, pady=6)
            for text, cmd in (("Add", lambda: self.do("add")), ("Update", lambda: self.do("update")),
                              ("Delete", lambda: self.do("delete")), ("Clear", self.clear)):
                ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=3)
            for text, fn, needs_sel in actions:
                ttk.Button(bar, text=text, command=lambda fn=fn, ns=needs_sel: self.act(fn, ns)).pack(
                    side="left", padx=(14, 3))
            if footer:
                self.foot = ttk.Label(self, font=("Segoe UI", 9, "bold"), justify="left")
                self.foot.pack(fill="x", padx=10)
            box = ttk.Frame(self)
            box.pack(fill="both", expand=True, padx=8, pady=(4, 8))
            cols = ["id"] + [f["name"] for f in fields]
            self.tree = ttk.Treeview(box, columns=cols, show="tree headings" if hier else "headings", height=height)
            vsb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
            hsb = ttk.Scrollbar(box, orient="horizontal", command=self.tree.xview)
            self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
            self.tree.grid(row=0, column=0, sticky="nsew")
            vsb.grid(row=0, column=1, sticky="ns")
            hsb.grid(row=1, column=0, sticky="ew")
            box.rowconfigure(0, weight=1)
            box.columnconfigure(0, weight=1)
            self.tree.heading("id", text="ID")
            self.tree.column("id", width=45, stretch=False)
            if hier:
                self.tree.heading("#0", text="WBS")
                self.tree.column("#0", width=110, stretch=False)
            for f in fields:
                self.tree.heading(f["name"], text=f["label"])
                self.tree.column(f["name"], width=f.get("w", 190 if f["kind"] == "text" else 110), stretch=False)
            for t, c in TAGS.items():
                self.tree.tag_configure(t, background=c)
            self.tree.bind("<<TreeviewSelect>>", self.on_select)

        def choices(self, f):
            ch = f.get("choices", [])
            return list(ch() if callable(ch) else ch)

        def selected_id(self):
            sel = self.tree.selection()
            return int(sel[0]) if sel else None

        def row_values(self, r):
            return [r["id"]] + [fmt_num(r[f["name"]]) for f in self.fields]

        def refresh(self):
            for f in self.fields:
                if f.get("form", True) and f["kind"] in ("choice", "fk"):
                    self.combos[f["name"]]["values"] = ([""] if not f.get("req", True) else []) + self.choices(f)
            sel = self.selected_id()
            rows = self.db.all(f"SELECT * FROM {self.table} ORDER BY {self.order}")
            self.tree.delete(*self.tree.get_children())
            if self.hier:
                kids = {}
                for r in rows:
                    kids.setdefault(r["parent_id"], []).append(r)

                def add(pid, piid):
                    for r in sorted(kids.get(pid, []), key=lambda x: [int(n) for n in x["code"].split(".")]):
                        self.tree.insert(piid, "end", iid=str(r["id"]), text=r["code"],
                                         values=self.row_values(r), open=True)
                        add(r["id"], str(r["id"]))
                add(None, "")
            else:
                for r in rows:
                    tag = self.tag_fn(r) if self.tag_fn else None
                    self.tree.insert("", "end", iid=str(r["id"]), values=self.row_values(r), tags=(tag,) if tag else ())
            if sel and self.tree.exists(str(sel)):
                self.tree.selection_set(str(sel))
            if self.footer:
                self.foot.config(text=self.footer(self.db))

        def on_select(self, _=None):
            rid = self.selected_id()
            if rid is None:
                return
            row = self.db.one(f"SELECT * FROM {self.table} WHERE id=?", (rid,))
            for f in self.fields:
                if not f.get("form", True):
                    continue
                v = row[f["name"]]
                if v is None:
                    s = ""
                elif f["kind"] == "fk":
                    s = next((c for c in self.choices(f) if c.split(" - ")[0] == str(v)), str(v))
                else:
                    s = fmt_num(v).replace(",", "") if f["kind"] == "float" else str(v)
                self.vars[f["name"]].set(s)

        def clear(self):
            self.tree.selection_remove(*self.tree.selection())
            for f in self.fields:
                if f.get("form", True):
                    self.vars[f["name"]].set(f.get("init", ""))

        def collect(self, op):
            vals = {}
            for f in self.fields:
                if f.get("form", True):
                    g = dict(f)
                    if callable(g.get("choices")):
                        g["choices"] = g["choices"]()
                    vals[f["name"]] = parse_value(g, self.vars[f["name"]].get())
                elif op == "add":
                    d = f.get("default")
                    vals[f["name"]] = d() if callable(d) else d
            return vals

        def do(self, op):
            try:
                rid = self.selected_id()
                if op in ("update", "delete") and rid is None:
                    raise ValueError("Select a record from the table first.")
                vals = {} if op == "delete" else self.collect(op)
                if self.validator:
                    self.validator(self.db, vals, rid, op)
                if op == "add":
                    self.db.insert(self.table, vals)
                elif op == "update":
                    self.db.update(self.table, rid, vals)
                else:
                    if not messagebox.askyesno("Confirm", "Delete the selected record?"):
                        return
                    self.db.delete(self.table, rid)
                if op != "update":
                    self.clear()
                self.app.refresh_all()
            except ValueError as e:
                messagebox.showwarning("Validation", str(e))
            except sqlite3.IntegrityError as e:
                self.db.con.rollback()
                messagebox.showerror("Database rule violated", friendly(e))
            except Exception as e:
                messagebox.showerror("Error", f"Unexpected error: {e}")

        def act(self, fn, needs_sel):
            try:
                rid = self.selected_id()
                if needs_sel and rid is None:
                    raise ValueError("Select a record from the table first.")
                msg = fn(self.db, rid)
                self.app.refresh_all()
                if msg:
                    messagebox.showinfo("Result", msg)
            except ValueError as e:
                messagebox.showwarning("Validation", str(e))
            except Exception as e:
                messagebox.showerror("Error", f"Unexpected error: {e}")

    # ---------------------------------------------------------------- project charter & plan
    class ProjectForm(ttk.Frame):
        SPECS = {
            "name": dict(label="Project name", kind="text"),
            "objectives": dict(label="Objectives", kind="text"),
            "stakeholders": dict(label="Stakeholders", kind="text"),
            "scope_boundaries": dict(label="Scope boundaries", kind="text"),
            "start_date": dict(label="Start date", kind="date"),
            "original_budget": dict(label="Approved budget", kind="float", min=1),
            "original_deadline": dict(label="Deadline", kind="date"),
            "plan_scope": dict(label="Plan: scope", kind="text"),
            "plan_schedule": dict(label="Plan: schedule", kind="text"),
            "plan_cost": dict(label="Plan: cost", kind="text"),
            "plan_quality": dict(label="Plan: quality", kind="text"),
            "status": dict(label="Project status", kind="choice", choices=PROJECT_STATUS),
            "closure_notes": dict(label="Closure notes", kind="text", req=False),
        }
        LONG = ["objectives", "stakeholders", "scope_boundaries", "plan_scope", "plan_schedule", "plan_cost",
                "plan_quality", "closure_notes"]

        def __init__(self, parent, app):
            super().__init__(parent)
            self.app, self.db = app, app.db
            app.tabs.append(self)
            self.w = {}
            left = ttk.LabelFrame(self, text="Project Charter")
            right = ttk.LabelFrame(self, text="Project Management Plan")
            bottom = ttk.LabelFrame(self, text="Status, Milestone Control & Closure")
            left.grid(row=0, column=0, sticky="nsew", padx=8, pady=6)
            right.grid(row=0, column=1, sticky="nsew", padx=8, pady=6)
            bottom.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=6)
            self.columnconfigure(0, weight=1)
            self.columnconfigure(1, weight=1)
            self.add(left, "name", "Project name", 0, "entry")
            self.add(left, "objectives", "Objectives", 1, "text")
            self.add(left, "stakeholders", "Stakeholders", 2, "text")
            self.add(left, "scope_boundaries", "Scope boundaries", 3, "text")
            self.add(left, "start_date", "Start date", 4, "entry")
            self.add(left, "original_budget", "Approved budget (PKR)", 5, "entry")
            self.add(left, "original_deadline", "Deadline", 6, "entry")
            self.cur = ttk.Label(left, font=("Segoe UI", 9, "bold"), foreground="#1565c0")
            self.cur.grid(row=7, column=0, columnspan=2, sticky="w", padx=6, pady=4)
            for i, (k, t) in enumerate([("plan_scope", "Scope"), ("plan_schedule", "Schedule"),
                                        ("plan_cost", "Cost"), ("plan_quality", "Quality")]):
                self.add(right, k, t, i, "text", h=5)
            self.add(bottom, "status", "Project status", 0, "combo")
            self.add(bottom, "closure_notes", "Closure notes", 1, "text")
            bt = ttk.Frame(bottom)
            bt.grid(row=2, column=0, columnspan=2, pady=6)
            ttk.Button(bt, text="Save Charter & Plan", command=self.save).pack(side="left", padx=6)
            ttk.Button(bt, text="Close Project", command=self.close).pack(side="left", padx=6)

        def add(self, parent, key, label, row, kind, h=3):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="ne", padx=6, pady=3)
            if kind == "text":
                w = tk.Text(parent, height=h, width=58, wrap="word", font=("Segoe UI", 9))
            elif kind == "combo":
                w = ttk.Combobox(parent, values=PROJECT_STATUS, state="readonly", width=30)
            else:
                w = ttk.Entry(parent, width=40)
            w.grid(row=row, column=1, sticky="w", padx=6, pady=3)
            self.w[key] = w

        def get(self, key):
            w = self.w[key]
            return w.get("1.0", "end").strip() if isinstance(w, tk.Text) else w.get()

        def put(self, key, val):
            w = self.w[key]
            val = "" if val is None else str(val)
            if isinstance(w, tk.Text):
                w.delete("1.0", "end")
                w.insert("1.0", val)
            elif isinstance(w, ttk.Combobox):
                w.set(val)
            else:
                w.delete(0, "end")
                w.insert(0, val)

        def refresh(self):
            p = project(self.db)
            for k in self.SPECS:
                v = p[k]
                self.put(k, f"{v:.0f}" if k == "original_budget" else v)
            b, d = baseline(self.db)
            self.cur.config(text=f"Current approved baseline (after approved change requests):  "
                                 f"{money(b)}  |  deadline {d}")

        def save(self):
            try:
                v = {k: parse_value(spec, self.get(k)) for k, spec in self.SPECS.items()}
                if pdate(v["original_deadline"]) <= pdate(v["start_date"]):
                    raise ValueError("Deadline must be after the start date.")
                if v["status"] == "Closed" and project(self.db)["status"] != "Closed":
                    raise ValueError("Use the 'Close Project' button to close the project.")
                self.db.update("project", 1, v)
                self.app.refresh_all()
                messagebox.showinfo("Saved", "Project charter and plan saved.")
            except ValueError as e:
                messagebox.showwarning("Validation", str(e))

        def close(self):
            try:
                close_project(self.db, self.get("closure_notes"))
                self.app.refresh_all()
                messagebox.showinfo("Closed", "Project closed and closure record stored.")
            except ValueError as e:
                messagebox.showwarning("Cannot close project", str(e))

    # ---------------------------------------------------------------- approved scope view
    class ScopeView(ttk.Frame):
        def __init__(self, parent, app):
            super().__init__(parent)
            self.db = app.db
            app.tabs.append(self)
            ttk.Label(self, text="Only APPROVED requirements are part of the project scope. "
                                 "Proposed/Rejected requirements cannot be used by the WBS or by activities.",
                      font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=8)
            cols = ("id", "title", "priority", "status", "scope", "wbs", "acts")
            self.tree = ttk.Treeview(self, columns=cols, show="headings", height=16)
            for c, t, w in zip(cols, ["ID", "Requirement", "Priority", "Status", "In approved scope?",
                                      "WBS items", "Activities"], [45, 330, 90, 90, 130, 90, 90]):
                self.tree.heading(c, text=t)
                self.tree.column(c, width=w, stretch=False)
            for t, c in TAGS.items():
                self.tree.tag_configure(t, background=c)
            self.tree.pack(fill="both", expand=True, padx=8, pady=4)
            self.sum = ttk.Label(self, font=("Segoe UI", 10, "bold"))
            self.sum.pack(anchor="w", padx=10, pady=6)

        def refresh(self):
            self.tree.delete(*self.tree.get_children())
            n_in = 0
            for r in self.db.all("SELECT * FROM requirements ORDER BY id"):
                w = self.db.one("SELECT COUNT(*) n FROM wbs WHERE requirement_id=?", (r["id"],))["n"]
                a = self.db.one("SELECT COUNT(*) n FROM activities WHERE requirement_id=?", (r["id"],))["n"]
                ins = r["status"] == "Approved"
                n_in += ins
                self.tree.insert("", "end", values=(r["id"], r["title"], r["priority"], r["status"],
                                                    "YES" if ins else "NO", w, a),
                                 tags=("green" if ins else "orange" if r["status"] == "Proposed" else "grey",))
            total = self.db.one("SELECT COUNT(*) n FROM requirements")["n"]
            self.sum.config(text=f"{n_in} of {total} requirements are in the approved scope baseline.")

    # ---------------------------------------------------------------- schedule analysis
    class ScheduleTab(ttk.Frame):
        def __init__(self, parent, app):
            super().__init__(parent)
            self.app, self.db = app, app.db
            app.tabs.append(self)
            top = ttk.Frame(self)
            top.pack(fill="x", padx=8, pady=6)
            ttk.Label(top, text="Status date (YYYY-MM-DD):").pack(side="left")
            self.sd = tk.StringVar()
            ttk.Entry(top, textvariable=self.sd, width=14).pack(side="left", padx=6)
            ttk.Button(top, text="Apply", command=self.apply).pack(side="left", padx=3)
            ttk.Button(top, text="Use today's date", command=lambda: (self.sd.set(today()), self.apply())).pack(side="left")
            ttk.Label(top, text="   (progress is measured as of this date)").pack(side="left")
            cols = ("id", "name", "who", "ps", "pe", "fs", "fe", "pct", "delay", "state")
            self.tree = ttk.Treeview(self, columns=cols, show="headings", height=11)
            for c, t, w in zip(cols, ["ID", "Activity", "Assigned to", "Planned start", "Planned end", "Forecast start",
                                      "Forecast end", "% done", "Delay (days)", "Status"],
                               [40, 270, 110, 95, 95, 95, 95, 60, 85, 110]):
                self.tree.heading(c, text=t)
                self.tree.column(c, width=w, stretch=False)
            for t, c in TAGS.items():
                self.tree.tag_configure(t, background=c)
            self.tree.pack(fill="x", padx=8)
            self.txt = tk.Text(self, height=12, font=("Consolas", 10), wrap="word")
            self.txt.pack(fill="both", expand=True, padx=8, pady=8)
            self.txt.tag_configure("warn", foreground="#c62828", font=("Consolas", 10, "bold"))

        def apply(self):
            try:
                v = parse_value(dict(label="Status date", kind="date"), self.sd.get())
                self.db.update("project", 1, {"status_date": v})
                self.app.refresh_all()
            except ValueError as e:
                messagebox.showwarning("Validation", str(e))

        def refresh(self):
            self.sd.set(project(self.db)["status_date"])
            self.tree.delete(*self.tree.get_children())
            self.txt.delete("1.0", "end")
            try:
                s = compute_schedule(self.db)
            except ValueError as e:
                self.txt.insert("end", f"Schedule error: {e}", "warn")
                return
            tagmap = {"Delayed": "red", "Completed Late": "red", "Impacted": "orange", "Complete": "green"}
            for a in s["rows"]:
                self.tree.insert("", "end", tags=(tagmap.get(a["state"], ""),), values=(
                    a["id"], a["name"], a["assignee"], a["start"], a["end"], a["f_start"], a["f_end"],
                    f"{a['percent_complete']:.0f}%", a["delay"], a["state"]))
            w = lambda t, tag=None: self.txt.insert("end", t + "\n", tag)
            w(f"Status date {s['status_date']}  |  Planned finish {s['planned_end']}  |  "
              f"Forecast finish {s['forecast_end']}  |  Deadline {s['deadline']}")
            if s["overrun"] > 0:
                w(f"[!] FINAL DEADLINE AT RISK: forecast finish is {s['overrun']} day(s) after the deadline.", "warn")
            else:
                w(f"Forecast finish is within the deadline ({-s['overrun']} day(s) of float).")
            w("")
            w("Delayed activities and their impact on dependent activities:")
            if not s["delayed"]:
                w("  none")
            for a in s["delayed"]:
                w(f"[!] #{a['id']} {a['name']}: late by {a['delay']} day(s)", "warn")
                if a["affected"]:
                    w("      pushes: " + "; ".join(f"#{x['id']} {x['name']} (+{x['delay']}d)" for x in a["affected"]))
                else:
                    w("      no dependent activities affected")

    # ---------------------------------------------------------------- Gantt chart
    class GanttTab(ttk.Frame):
        def __init__(self, parent, app):
            super().__init__(parent)
            self.db = app.db
            app.tabs.append(self)
            ttk.Label(self, text="Grey = planned baseline | Blue/Green/Orange/Red = forecast (filled part = progress) | "
                                 "Blue dashed = status date | Red line = deadline | Diamonds = milestones",
                      font=("Segoe UI", 9)).pack(anchor="w", padx=8, pady=4)
            box = ttk.Frame(self)
            box.pack(fill="both", expand=True)
            self.c = tk.Canvas(box, bg="white")
            vsb = ttk.Scrollbar(box, orient="vertical", command=self.c.yview)
            hsb = ttk.Scrollbar(box, orient="horizontal", command=self.c.xview)
            self.c.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
            self.c.grid(row=0, column=0, sticky="nsew")
            vsb.grid(row=0, column=1, sticky="ns")
            hsb.grid(row=1, column=0, sticky="ew")
            box.rowconfigure(0, weight=1)
            box.columnconfigure(0, weight=1)

        def refresh(self):
            c = self.c
            c.delete("all")
            try:
                s = compute_schedule(self.db)
            except ValueError as e:
                c.create_text(10, 10, text=str(e), anchor="nw", fill="red")
                return
            rows = s["rows"]
            if not rows:
                c.create_text(10, 10, text="No activities yet.", anchor="nw")
                return
            ms = self.db.all("SELECT * FROM milestones ORDER BY due_date")
            start = min(min(a["start"] for a in rows), pdate(project(self.db)["start_date"]))
            end = max(s["forecast_end"], s["deadline"]) + timedelta(days=5)
            total = (end - start).days + 1
            ppd = max(5, min(16, 900 // total))
            left, top, rh = 250, 45, 30
            width = left + total * ppd + 60
            height = top + rh * (len(rows) + len(ms) + 2) + 20
            c.configure(scrollregion=(0, 0, width, height))
            X = lambda d: left + (d - start).days * ppd
            d = 0
            while d < total:
                x = left + d * ppd
                c.create_line(x, top - 8, x, height, fill="#e6e6e6")
                c.create_text(x + 2, top - 22, text=(start + timedelta(days=d)).strftime("%d %b"),
                              anchor="w", font=("Segoe UI", 8))
                d += 7
            col = {"Complete": "#2e7d32", "Delayed": "#e53935", "Completed Late": "#e53935",
                   "Impacted": "#fb8c00", "On Track": "#1e88e5"}
            pos = {}
            for n, a in enumerate(rows):
                y = top + n * rh
                pos[a["id"]] = y
                c.create_text(8, y + rh / 2, text=f"{a['id']}. {a['name']}"[:36], anchor="w", font=("Segoe UI", 9))
                c.create_rectangle(X(a["start"]), y + 3, X(a["end"]) + ppd, y + 11, fill="#cfd8dc", outline="#90a4ae")
                fx1, fx2 = X(a["f_start"]), X(a["f_end"]) + ppd
                k = col[a["state"]]
                c.create_rectangle(fx1, y + 14, fx2, y + 26, fill="white", outline=k)
                c.create_rectangle(fx1, y + 14, fx1 + (fx2 - fx1) * a["percent_complete"] / 100, y + 26, fill=k, outline=k)
                c.create_text(fx2 + 4, y + 20, text=f"{a['percent_complete']:.0f}%", anchor="w", font=("Segoe UI", 8))
            from_ids = {a["id"]: a for a in rows}
            for a in rows:                                 # dependency arrows
                for dpd in dep_list(a):
                    p = from_ids[dpd]
                    c.create_line(X(p["f_end"]) + ppd, pos[dpd] + 20, X(a["f_start"]), pos[a["id"]] + 20,
                                  fill="#9e9e9e", arrow=tk.LAST)
            y0 = top + len(rows) * rh + 10
            for n, m in enumerate(ms):
                y = y0 + n * rh
                x = X(pdate(m["due_date"])) + ppd // 2
                late = m["status"] != "Achieved" and pdate(m["due_date"]) < s["status_date"]
                k = "#2e7d32" if m["status"] == "Achieved" else "#c62828" if late else "#6a1b9a"
                c.create_polygon(x, y + 4, x + 9, y + 14, x, y + 24, x - 9, y + 14, fill=k, outline=k)
                c.create_text(8, y + 14, text=m["name"][:36], anchor="w", font=("Segoe UI", 9, "italic"))
                c.create_text(x + 14, y + 14, text=f"{m['due_date']} [{m['status']}]", anchor="w", font=("Segoe UI", 8))
            xs = X(s["status_date"]) + ppd // 2
            c.create_line(xs, top - 8, xs, height, fill="#1565c0", dash=(4, 3), width=2)
            c.create_text(xs, top - 34, text="Status", fill="#1565c0", font=("Segoe UI", 8, "bold"))
            xd = X(s["deadline"]) + ppd
            c.create_line(xd, top - 8, xd, height, fill="#c62828", width=2)
            c.create_text(xd, top - 34, text="Deadline", fill="#c62828", font=("Segoe UI", 8, "bold"))

    # ---------------------------------------------------------------- cost estimates
    class CostTab(ttk.Frame):
        def __init__(self, parent, app):
            super().__init__(parent)
            self.db = app.db
            app.tabs.append(self)
            cols = ("id", "name", "bac", "pct", "ev", "ac", "cv")
            self.tree = ttk.Treeview(self, columns=cols, show="headings", height=16)
            for c, t, w in zip(cols, ["ID", "Activity", "Planned cost (PKR)", "% done", "Budgeted cost of work done (EV)",
                                      "Actual cost (PKR)", "Cost variance (EV-AC)"], [40, 300, 130, 70, 210, 130, 160]):
                self.tree.heading(c, text=t)
                self.tree.column(c, width=w, stretch=False, anchor="w" if c == "name" else "e")
            for t, c in TAGS.items():
                self.tree.tag_configure(t, background=c)
            self.tree.pack(fill="both", expand=True, padx=8, pady=8)
            self.sum = ttk.Label(self, font=("Segoe UI", 10, "bold"), justify="left")
            self.sum.pack(anchor="w", padx=10, pady=6)

        def refresh(self):
            self.tree.delete(*self.tree.get_children())
            tb = te = ta = 0
            ac = {r["activity_id"]: r["t"] for r in self.db.all(
                "SELECT activity_id, SUM(amount) t FROM expenses GROUP BY activity_id")}
            for a in self.db.all("SELECT * FROM activities ORDER BY id"):
                ev = a["planned_cost"] * a["percent_complete"] / 100
                x = ac.get(a["id"], 0)
                tb, te, ta = tb + a["planned_cost"], te + ev, ta + x
                self.tree.insert("", "end", tags=("red" if ev - x < 0 else "",), values=(
                    a["id"], a["name"], f"{a['planned_cost']:,.0f}", f"{a['percent_complete']:.0f}%",
                    f"{ev:,.0f}", f"{x:,.0f}", f"{ev - x:,.0f}"))
            self.tree.insert("", "end", values=("", "TOTAL", f"{tb:,.0f}", "", f"{te:,.0f}", f"{ta:,.0f}", f"{te - ta:,.0f}"))
            budget, _ = baseline(self.db)
            self.sum.config(text=f"Total planned project budget: {money(tb)}   |   Approved budget: {money(budget)}   |   "
                                 f"Unallocated: {money(budget - tb)}")

    # ---------------------------------------------------------------- EVM
    class EVMTab(ttk.Frame):
        def __init__(self, parent, app):
            super().__init__(parent)
            self.app, self.db = app, app.db
            app.tabs.append(self)
            top = ttk.Frame(self)
            top.pack(fill="x", padx=8, pady=6)
            self.cpi_t, self.spi_t = tk.StringVar(), tk.StringVar()
            ttk.Label(top, text="Warning threshold - CPI below:").pack(side="left")
            ttk.Entry(top, textvariable=self.cpi_t, width=6).pack(side="left", padx=4)
            ttk.Label(top, text="SPI below:").pack(side="left", padx=(10, 0))
            ttk.Entry(top, textvariable=self.spi_t, width=6).pack(side="left", padx=4)
            ttk.Button(top, text="Save thresholds", command=self.save).pack(side="left", padx=8)
            self.grid_f = ttk.Frame(self)
            self.grid_f.pack(fill="x", padx=8, pady=4)
            self.cards = {}
            names = [("bac", "BAC (planned budget)"), ("pv", "PV Planned Value"), ("ev", "EV Earned Value"),
                     ("ac", "AC Actual Cost"), ("cpi", "CPI = EV/AC"), ("spi", "SPI = EV/PV"),
                     ("cv", "CV = EV - AC"), ("sv", "SV = EV - PV"), ("eac", "EAC = BAC/CPI"),
                     ("etc", "ETC = EAC - AC"), ("vac", "VAC = BAC - EAC"), ("budget", "Approved budget")]
            for n, (k, t) in enumerate(names):
                lf = tk.LabelFrame(self.grid_f, text=t)
                lf.grid(row=n // 6, column=n % 6, padx=4, pady=4, sticky="nsew")
                lb = tk.Label(lf, text="-", font=("Segoe UI", 12, "bold"), width=15)
                lb.pack(padx=4, pady=4)
                self.cards[k] = lb
            mid = ttk.Frame(self)
            mid.pack(fill="both", expand=True, padx=8, pady=4)
            self.cv = tk.Canvas(mid, width=420, height=230, bg="white", highlightthickness=1,
                                highlightbackground="#bbbbbb")
            self.cv.pack(side="left", padx=(0, 8))
            self.txt = tk.Text(mid, height=10, font=("Consolas", 10), wrap="word")
            self.txt.pack(side="left", fill="both", expand=True)
            self.txt.tag_configure("warn", foreground="#c62828", font=("Consolas", 10, "bold"))
            self.txt.tag_configure("ok", foreground="#2e7d32", font=("Consolas", 10, "bold"))

        def save(self):
            try:
                c = parse_value(dict(label="CPI threshold", kind="float", min=0.1, max=2), self.cpi_t.get())
                s = parse_value(dict(label="SPI threshold", kind="float", min=0.1, max=2), self.spi_t.get())
                self.db.update("project", 1, {"cpi_threshold": c, "spi_threshold": s})
                self.app.refresh_all()
            except ValueError as e:
                messagebox.showwarning("Validation", str(e))

        def refresh(self):
            p = project(self.db)
            self.cpi_t.set(str(p["cpi_threshold"]))
            self.spi_t.set(str(p["spi_threshold"]))
            try:
                e = compute_evm(self.db)
            except ValueError as ex:
                self.txt.delete("1.0", "end")
                self.txt.insert("end", f"Cannot calculate: {ex}", "warn")
                return
            for k in ("bac", "pv", "ev", "ac", "cv", "sv", "eac", "etc", "vac", "budget"):
                self.cards[k].config(text=f"{e[k]:,.0f}", fg="#c62828" if k in ("cv", "sv", "vac") and e[k] < 0 else "black")
            for k, th in (("cpi", p["cpi_threshold"]), ("spi", p["spi_threshold"])):
                v = e[k]
                self.cards[k].config(text="n/a" if v is None else f"{v:.2f}",
                                     fg="black" if v is None else "#c62828" if v < th else "#2e7d32")
            self.txt.delete("1.0", "end")
            if e["warnings"]:
                for w in e["warnings"]:
                    self.txt.insert("end", "[!] " + w + "\n\n", "warn")
            else:
                self.txt.insert("end", "Project performance is within thresholds.", "ok")
            c = self.cv
            c.delete("all")
            mx = max(e["pv"], e["ev"], e["ac"], 1)
            for i, (lab, v, colr) in enumerate([("PV", e["pv"], "#1e88e5"), ("EV", e["ev"], "#43a047"),
                                                ("AC", e["ac"], "#e53935")]):
                x = 40 + i * 125
                h = 170 * v / mx
                c.create_rectangle(x, 200 - h, x + 80, 200, fill=colr, outline=colr)
                c.create_text(x + 40, 212, text=lab, font=("Segoe UI", 10, "bold"))
                c.create_text(x + 40, 192 - h, text=f"{v:,.0f}", font=("Segoe UI", 8))
            c.create_text(210, 12, text="PV vs EV vs AC (as of status date)", font=("Segoe UI", 9, "bold"))

    # ---------------------------------------------------------------- risk matrix & PDPC
    class RiskMatrixTab(ttk.Frame):
        def __init__(self, parent, app):
            super().__init__(parent)
            self.db = app.db
            app.tabs.append(self)
            left = ttk.Frame(self)
            left.pack(side="left", padx=10, pady=10, anchor="n")
            ttk.Label(left, text="Prioritization Matrix (Likelihood x Impact)", font=("Segoe UI", 10, "bold")).grid(
                row=0, column=0, columnspan=7, pady=4)
            self.cells = {}
            for i, imp in enumerate(range(5, 0, -1)):
                ttk.Label(left, text=f"Impact {imp}").grid(row=i + 1, column=0, padx=4)
                for lik in range(1, 6):
                    lb = tk.Label(left, width=13, height=3, relief="ridge", wraplength=100, font=("Segoe UI", 9, "bold"))
                    lb.grid(row=i + 1, column=lik, padx=1, pady=1)
                    self.cells[(lik, imp)] = lb
            for lik in range(1, 6):
                ttk.Label(left, text=f"Likelihood {lik}").grid(row=6, column=lik)
            right = ttk.Frame(self)
            right.pack(side="left", fill="both", expand=True, padx=8, pady=10)
            ttk.Label(right, text="Risk ranking (highest score first)", font=("Segoe UI", 10, "bold")).pack(anchor="w")
            cols = ("rank", "id", "desc", "l", "i", "score", "level", "status")
            self.tree = ttk.Treeview(right, columns=cols, show="headings", height=15)
            for c, t, w in zip(cols, ["Rank", "ID", "Risk", "L", "I", "Score", "Level", "Status"],
                               [45, 40, 330, 30, 30, 50, 70, 80]):
                self.tree.heading(c, text=t)
                self.tree.column(c, width=w, stretch=False)
            for t, c in TAGS.items():
                self.tree.tag_configure(t, background=c)
            self.tree.pack(fill="both", expand=True)

        def refresh(self):
            risks = self.db.all("SELECT * FROM risks ORDER BY likelihood*impact DESC, id")
            for (lik, imp), lb in self.cells.items():
                sc = lik * imp
                lb.config(bg="#ef9a9a" if sc >= 15 else "#ffe082" if sc >= 9 else "#a5d6a7",
                          text=", ".join(f"R{r['id']}" for r in risks if r["likelihood"] == lik and r["impact"] == imp))
            self.tree.delete(*self.tree.get_children())
            for n, r in enumerate(risks, 1):
                sc = r["likelihood"] * r["impact"]
                lv = risk_level(sc)
                self.tree.insert("", "end", tags=("red" if lv == "High" else "orange" if lv == "Medium" else "green",),
                                 values=(n, r["id"], r["description"], r["likelihood"], r["impact"], sc, lv, r["status"]))

    class PDPCTab(ttk.Frame):
        def __init__(self, parent, app):
            super().__init__(parent)
            self.db = app.db
            app.tabs.append(self)
            ttk.Label(self, text="Process Decision Program Chart: goal -> potential problems -> preventive and corrective actions",
                      font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=6)
            self.tree = ttk.Treeview(self, show="tree", height=24)
            self.tree.pack(fill="both", expand=True, padx=8, pady=4)
            for t, c in TAGS.items():
                self.tree.tag_configure(t, background=c)

        def refresh(self):
            self.tree.delete(*self.tree.get_children())
            root = self.tree.insert("", "end", open=True,
                                    text="GOAL: Deliver the Smart Healthcare PM System on time, within budget and with quality")
            for r in self.db.all("SELECT * FROM risks ORDER BY likelihood*impact DESC, id"):
                sc = r["likelihood"] * r["impact"]
                lv = risk_level(sc)
                tag = "red" if lv == "High" else "orange" if lv == "Medium" else "green"
                n = self.tree.insert(root, "end", open=True, tags=(tag,),
                                     text=f"PROBLEM R{r['id']} [{lv}, score {sc}, {r['status']}]: {r['description']}")
                self.tree.insert(n, "end", text=f"PREVENTIVE ACTION: {r['preventive']}")
                self.tree.insert(n, "end", text=f"IF IT OCCURS - CORRECTIVE ACTION: {r['corrective']}")

    # ---------------------------------------------------------------- dashboard & tests
    class Dashboard(ttk.Frame):
        def __init__(self, parent, app):
            super().__init__(parent)
            self.app, self.db = app, app.db
            app.tabs.append(self)
            top = ttk.Frame(self)
            top.pack(fill="x", padx=8, pady=6)
            self.cards = {}
            names = [("progress", "Overall progress"), ("budget", "Approved budget (PKR)"), ("ac", "Actual cost (PKR)"),
                     ("cpi", "CPI"), ("spi", "SPI"), ("crs", "Pending change requests"),
                     ("delayed", "Delayed activities"), ("crit", "Unresolved critical defects")]
            for n, (k, t) in enumerate(names):
                lf = tk.LabelFrame(top, text=t)
                lf.grid(row=n // 4, column=n % 4, padx=5, pady=5, sticky="nsew")
                lb = tk.Label(lf, text="-", font=("Segoe UI", 17, "bold"), width=14)
                lb.pack(padx=6, pady=6)
                self.cards[k] = lb
                top.columnconfigure(n % 4, weight=1)
            self.bar = ttk.Progressbar(self, maximum=100)
            self.bar.pack(fill="x", padx=14, pady=2)
            btn = ttk.Frame(self)
            btn.pack(fill="x", padx=8, pady=4)
            ttk.Button(btn, text="Refresh", command=app.refresh_all).pack(side="left", padx=3)
            ttk.Button(btn, text="Export report (.txt)", command=self.export).pack(side="left", padx=3)
            ttk.Button(btn, text="Load sample data (reset)", command=self.reload).pack(side="left", padx=3)
            box = ttk.Frame(self)
            box.pack(fill="both", expand=True, padx=8, pady=4)
            self.txt = tk.Text(box, font=("Consolas", 10), wrap="word")
            sb = ttk.Scrollbar(box, command=self.txt.yview)
            self.txt.configure(yscrollcommand=sb.set)
            self.txt.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            self.txt.tag_configure("warn", foreground="#c62828")
            self.txt.tag_configure("h", font=("Consolas", 10, "bold"), foreground="#1565c0")

        def refresh(self):
            try:
                r = build_report(self.db)
            except ValueError as e:
                self.txt.delete("1.0", "end")
                self.txt.insert("end", f"Cannot build report: {e}")
                return
            e = r["evm"]
            p = r["p"]
            red, green = "#c62828", "#2e7d32"
            c = self.cards
            c["progress"].config(text=f"{r['progress']:.0f}%")
            c["budget"].config(text=f"{r['budget']:,.0f}", fg=red if e["ac"] > r["budget"] else "black")
            c["ac"].config(text=f"{e['ac']:,.0f}")
            c["cpi"].config(text="n/a" if e["cpi"] is None else f"{e['cpi']:.2f}",
                            fg="black" if e["cpi"] is None else red if e["cpi"] < p["cpi_threshold"] else green)
            c["spi"].config(text="n/a" if e["spi"] is None else f"{e['spi']:.2f}",
                            fg="black" if e["spi"] is None else red if e["spi"] < p["spi_threshold"] else green)
            c["crs"].config(text=str(len(r["pending"])), fg=red if r["pending"] else green)
            c["delayed"].config(text=str(len(r["sch"]["delayed"])), fg=red if r["sch"]["delayed"] else green)
            c["crit"].config(text=str(len(r["crit"])), fg=red if r["crit"] else green)
            self.bar["value"] = r["progress"]
            self.txt.delete("1.0", "end")
            for line in report_text(self.db).split("\n"):
                self.txt.insert("end", line + "\n", "warn" if line.startswith("[!]") else "h" if line.startswith("==") else "")

        def export(self):
            path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="project_report.txt",
                                                filetypes=[("Text", "*.txt")])
            if path:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(report_text(self.db))
                messagebox.showinfo("Exported", f"Report saved to {path}")

        def reload(self):
            if messagebox.askyesno("Load sample data", "This deletes ALL current data and reloads the case-study sample data. Continue?"):
                seed(self.db)
                self.app.refresh_all()

    class TestTab(ttk.Frame):
        def __init__(self, parent, app):
            super().__init__(parent)
            ttk.Label(self, text="Automated test cases run against a fresh in-memory copy of the sample data "
                                 "(your real database is not touched).", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=6)
            ttk.Button(self, text="Run all test cases", command=self.run).pack(anchor="w", padx=10)
            self.sum = ttk.Label(self, font=("Segoe UI", 11, "bold"))
            self.sum.pack(anchor="w", padx=10, pady=4)
            cols = ("id", "desc", "exp", "act", "res")
            self.tree = ttk.Treeview(self, columns=cols, show="headings", height=22)
            for c, t, w in zip(cols, ["Test", "Test case", "Expected result", "Actual result", "Result"],
                               [55, 430, 190, 190, 60]):
                self.tree.heading(c, text=t)
                self.tree.column(c, width=w, stretch=False)
            self.tree.tag_configure("PASS", background=TAGS["green"])
            self.tree.tag_configure("FAIL", background=TAGS["red"])
            self.tree.pack(fill="both", expand=True, padx=8, pady=6)

        def refresh(self):
            pass

        def run(self):
            self.tree.delete(*self.tree.get_children())
            res = run_test_cases()
            for r in res:
                self.tree.insert("", "end", values=r, tags=(r[4],))
            ok = sum(1 for r in res if r[4] == "PASS")
            self.sum.config(text=f"{ok} / {len(res)} test cases passed", foreground="#2e7d32" if ok == len(res) else "#c62828")

    # ---------------------------------------------------------------- main application
    class App(tk.Tk):
        def __init__(self, db):
            super().__init__()
            self.db = db
            self.tabs = []
            self.title("Smart Healthcare Project Management & Monitoring System  -  CSE-494")
            self.geometry("1340x800")
            try:
                ttk.Style().theme_use("clam")
            except tk.TclError:
                pass
            self.build()
            self.refresh_all()

        def refresh_all(self):
            for t in self.tabs:
                try:
                    t.refresh()
                except Exception as e:                  # never let one tab crash the app
                    print("Refresh error:", type(t).__name__, e)

        def sub(self, parent, title):
            n = ttk.Notebook(parent)
            parent.add(n, text=title)
            return n

        def build(self):
            db = self.db
            team = lambda d=db: [r["name"] for r in d.all("SELECT name FROM team ORDER BY id")]
            reqs = lambda ap=False: [f"{r['id']} - {r['title']}" for r in db.all(
                "SELECT id, title FROM requirements" + (" WHERE status='Approved'" if ap else "") + " ORDER BY id")]
            acts = lambda: [f"{r['id']} - {r['name']}" for r in db.all("SELECT id, name FROM activities ORDER BY id")]
            wbs = lambda: [f"{r['id']} - {r['code']} {r['name']}" for r in db.all("SELECT * FROM wbs ORDER BY id")]
            nb = ttk.Notebook(self)
            nb.pack(fill="both", expand=True)
            nb.add(Dashboard(nb, self), text="Dashboard / Report")

            # 1. initiation & integration
            n1 = self.sub(nb, "1. Initiation & Integration")
            n1.add(ProjectForm(n1, self), text="Charter, Plan & Closure")
            n1.add(CrudTab(n1, self, "milestones", [
                dict(name="name", label="Milestone", kind="text", w=260),
                dict(name="due_date", label="Due date", kind="date"),
                dict(name="status", label="Status", kind="choice", choices=MS_STATUS),
                dict(name="responsible", label="Responsible", kind="choice", choices=team, req=False)],
                v_milestone, order="due_date",
                tag_fn=lambda r: "green" if r["status"] == "Achieved" else None), text="Milestones")
            n1.add(CrudTab(n1, self, "team", [
                dict(name="name", label="Name", kind="text"),
                dict(name="role", label="Role", kind="text"),
                dict(name="responsibility", label="Responsibility", kind="text", req=False, w=320)]),
                text="Team & Responsibilities")

            # 2. scope & WBS
            n2 = self.sub(nb, "2. Scope & WBS")

            def set_req(status):
                def fn(d, rid):
                    if status != "Approved":
                        v_requirement(d, {"status": status}, rid, "update")
                    d.update("requirements", rid, {"status": status})
                    return f"Requirement {rid} is now {status}."
                return fn

            n2.add(CrudTab(n2, self, "requirements", [
                dict(name="title", label="Title", kind="text", w=260),
                dict(name="description", label="Description", kind="text", req=False, w=300),
                dict(name="priority", label="Priority", kind="choice", choices=PRIORITY, init="Medium"),
                dict(name="status", label="Status", kind="choice", choices=REQ_STATUS, init="Proposed")],
                v_requirement, order="CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END, id",
                actions=[("Approve", set_req("Approved"), True), ("Reject", set_req("Rejected"), True)],
                tag_fn=lambda r: {"Approved": "green", "Proposed": "orange", "Rejected": "grey"}[r["status"]]),
                text="Requirements")
            n2.add(CrudTab(n2, self, "change_requests", [
                dict(name="title", label="Change request", kind="text", w=240),
                dict(name="justification", label="Justification", kind="text", w=300),
                dict(name="requirement_id", label="Linked requirement", kind="fk", choices=reqs, req=False, w=220),
                dict(name="cost_impact", label="Cost impact (PKR)", kind="float", min=0, init="0"),
                dict(name="schedule_impact", label="Schedule impact (days)", kind="int", min=0, init="0"),
                dict(name="status", label="Approval status", kind="text", form=False, default="Pending", w=100),
                dict(name="raised_on", label="Raised on", kind="date", form=False, default=today),
                dict(name="decided_on", label="Decided on", kind="date", form=False, default=None)],
                v_cr, per_row=1,
                actions=[("Approve & Apply to project", lambda d, rid: decide_cr(d, rid, "Approved"), True),
                         ("Reject", lambda d, rid: decide_cr(d, rid, "Rejected"), True)],
                tag_fn=lambda r: {"Pending": "orange", "Approved": "green", "Rejected": "grey"}[r["status"]],
                footer=lambda d: (lambda b, dl, p: f"Original: {money(p['original_budget'])} / {p['original_deadline']}   ->   "
                                                   f"Current approved: {money(b)} / {dl}   "
                                                   f"(approved change requests change budget, deadline and scope)")(
                    *baseline(d), project(d)), height=6), text="Change Requests")
            n2.add(CrudTab(n2, self, "wbs", [
                dict(name="code", label="WBS code (e.g. 1.2)", kind="text", w=90),
                dict(name="name", label="Name", kind="text", w=300),
                dict(name="parent_id", label="Parent", kind="fk", choices=wbs, req=False, w=100),
                dict(name="node_type", label="Type", kind="choice", choices=WBS_TYPES, init="Work Package"),
                dict(name="requirement_id", label="Requirement (approved only)", kind="fk",
                     choices=lambda: reqs(True), req=False, w=100)],
                v_wbs, hier=True, height=13,
                actions=[("Auto-generate WBS from approved requirements",
                          lambda d, rid: f"{generate_wbs(d)} new deliverable(s) added to the WBS.", False)]),
                text="Work Breakdown Structure")
            n2.add(ScopeView(n2, self), text="Approved Scope Baseline")

            # 3. schedule & resources
            n3 = self.sub(nb, "3. Schedule & Resources")
            n3.add(CrudTab(n3, self, "activities", [
                dict(name="name", label="Activity", kind="text", w=280),
                dict(name="assignee", label="Assigned to", kind="choice", choices=team),
                dict(name="duration", label="Duration (days)", kind="int", min=1),
                dict(name="start_date", label="Earliest start", kind="date"),
                dict(name="depends_on", label="Depends on (IDs, e.g. 2,3)", kind="text", req=False, w=90),
                dict(name="planned_cost", label="Planned cost (PKR)", kind="float", min=0),
                dict(name="percent_complete", label="% complete", kind="float", min=0, max=100, init="0", w=80),
                dict(name="actual_end", label="Actual end (if 100%)", kind="date", req=False),
                dict(name="requirement_id", label="Requirement (approved)", kind="fk", choices=lambda: reqs(True),
                     req=False, w=80)], v_activity, height=11), text="Activities & Dependencies")
            n3.add(ScheduleTab(n3, self), text="Schedule, Delays & Impact")
            n3.add(GanttTab(n3, self), text="Gantt Chart")

            # 4. cost & EVM
            n4 = self.sub(nb, "4. Cost & EVM")
            n4.add(CostTab(n4, self), text="Cost Estimates")
            n4.add(CrudTab(n4, self, "expenses", [
                dict(name="activity_id", label="Activity", kind="fk", choices=acts, w=60),
                dict(name="amount", label="Amount (PKR)", kind="float", min=0.01),
                dict(name="spent_on", label="Date", kind="date", init=today()),
                dict(name="description", label="Description", kind="text", req=False, w=300)],
                v_expense, order="spent_on, id"), text="Actual Expenditure")
            n4.add(EVMTab(n4, self), text="Earned Value Analysis")

            # 5. quality & risk
            n5 = self.sub(nb, "5. Quality & Risk")
            n5.add(CrudTab(n5, self, "defects", [
                dict(name="title", label="Defect", kind="text", w=280),
                dict(name="activity_id", label="Activity", kind="fk", choices=acts, req=False, w=60),
                dict(name="severity", label="Severity", kind="choice", choices=PRIORITY, init="Medium"),
                dict(name="assigned_to", label="Assigned to", kind="choice", choices=team, req=False),
                dict(name="status", label="Status", kind="choice", choices=DEFECT_STATUS, init="Open"),
                dict(name="reported_on", label="Reported", kind="date", form=False, default=today),
                dict(name="resolved_on", label="Resolved", kind="date", form=False, default=None)],
                v_defect, tag_fn=lambda r: "red" if r["severity"] == "Critical" and r["status"] not in ("Resolved", "Closed")
                else "green" if r["status"] in ("Resolved", "Closed") else None), text="Defect Tracking")
            n5.add(CrudTab(n5, self, "quality_checks", [
                dict(name="deliverable", label="Deliverable", kind="text", w=200),
                dict(name="check_item", label="Checklist item", kind="text", w=260),
                dict(name="result", label="Inspection / test result", kind="choice", choices=CHECK_RESULT, init="Pending"),
                dict(name="tested_by", label="Tested by", kind="choice", choices=team, req=False),
                dict(name="test_date", label="Test date", kind="date", req=False),
                dict(name="notes", label="Notes", kind="text", req=False)],
                v_check, tag_fn=lambda r: {"Pass": "green", "Fail": "red"}.get(r["result"])), text="Quality Checklist")
            n5.add(CrudTab(n5, self, "risks", [
                dict(name="description", label="Risk / issue", kind="text", w=280),
                dict(name="likelihood", label="Likelihood (1-5)", kind="int", min=1, max=5, w=90),
                dict(name="impact", label="Impact (1-5)", kind="int", min=1, max=5, w=80),
                dict(name="preventive", label="Preventive action", kind="text", w=260),
                dict(name="corrective", label="Corrective action", kind="text", w=260),
                dict(name="status", label="Status", kind="choice", choices=RISK_STATUS, init="Open")],
                tag_fn=lambda r: "red" if r["likelihood"] * r["impact"] >= 15 else
                "orange" if r["likelihood"] * r["impact"] >= 9 else "green"), text="Risk Register")
            n5.add(RiskMatrixTab(n5, self), text="Prioritization Matrix")
            n5.add(PDPCTab(n5, self), text="PDPC Risk Response")

            nb.add(TestTab(nb, self), text="Test Cases")


def main():
    if "--test" in sys.argv:
        res = run_test_cases()
        for r in res:
            print(f"{r[0]} [{r[4]}] {r[1]}\n        expected: {r[2]}\n        actual  : {r[3]}")
        ok = sum(1 for r in res if r[4] == "PASS")
        print(f"\n{ok}/{len(res)} test cases passed")
        sys.exit(0 if ok == len(res) else 1)
    if tk is None:
        print("Tkinter is not available in this Python installation. Install the standard Python from python.org.")
        sys.exit(1)
    App(ensure_db()).mainloop()


if __name__ == "__main__":
    main()