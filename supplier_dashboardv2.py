
"""
Supplier Dashboard - Modern TKinter + SQLite (single-file, class-based, stdlib only)

Features:
- TOKYO dark theme
- Left panel: actions + stats
- Right panel: quick filter, pagination, sorting (click headers), table view
- Double-click row => edit dialog
- Column visibility toggles
- CSV export of current page/filter
- Background sync thread (Virtualstock APIs) - UI stays responsive
- SQLite persistence with requested supplier attributes

Configuration:
- Reads API auth from either:
    * environment variable: API_AUTH="Basic <token>"
    * or config.json in same directory: { "api_auth": "Basic <token>" }
- Endpoints:
    api_url_products = "https://api.virtualstock.com/api/v4/suppliers/?limit=1000"
    api_url_orders   = "https://api.virtualstock.com/restapi/v4/suppliers/?limit=1000"

Notes:
- Only standard libraries are used.
- For demonstration, if the DB is empty, the app seeds several sample suppliers.
- Sorting and pagination are executed via SQL for scalability.
"""

import csv
import datetime as dt
import json
import os
import queue
import sqlite3
import threading
import traceback
import urllib.request
import urllib.parse
from functools import lru_cache
from tkinter import (
    Tk, StringVar, IntVar, BooleanVar, Toplevel, N, S, E, W, BOTH, LEFT, RIGHT, X, Y, END
)
from tkinter import ttk, messagebox, filedialog

# ------------------------ DEV CONFIG ------------------------

API_AUTH = "Basic your-token-here"  # Replace with your actual token

API_URL_PRODUCTS = "https://api.virtualstock.com/api/v4/suppliers/?limit=1000"
API_URL_ORDERS   = "https://api.virtualstock.com/restapi/v4/suppliers/?limit=1000"
DB_FILE = "suppliers.db"
# ------------------------ LOAD CONFIG ------------------------
# def load_config():
#     global API_AUTH
#     # 1. From environment variable
#     env_auth = os.getenv("API_AUTH")
#     if env_auth:
#         API_AUTH = env_auth.strip()
#         return
#     # 2. From config.json
#     try:
#         with open("config.json", "r", encoding="utf-8") as f:
#             cfg = json.load(f)
#             if "api_auth" in cfg:
#                 API_AUTH = cfg["api_auth"].strip()
#     except Exception as ex:
#         print("No config.json found or invalid JSON:", ex)

class ApiClient:
    def __init__(self):
        self.headers = {
            "Authorization": API_AUTH,
            "Accept": "application/json"
        }

    def _http_get_json(self, url):
        resp = requests.get(url, headers=self.headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
# ------------------------ THEME ------------------------

TOKYO = {
    "bg": "#1a1b26",
    "bg_darker": "#16161e",
    "bg_lighter": "#24283b",
    "fg": "#c0caf5",
    "muted": "#a9b1d6",
    "accent": "#7aa2f7",
    "success": "#9ece6a",
    "warn": "#e0af68",
    "error": "#f7768e",
    "selection": "#283457",
    "border": "#3b4261",
}

# ------------------------ CONFIG / CONSTANTS ------------------------

DB_FILE = "suppliers.db"

API_URL_PRODUCTS = "https://api.virtualstock.com/api/v4/suppliers/?limit=1000"
API_URL_ORDERS = "https://api.virtualstock.com/restapi/v4/suppliers/?limit=1000"

DEFAULT_PAGE_SIZE = 25
PAGE_SIZE_OPTIONS = [10, 25, 50, 100, 250, 500]

ALL_COLUMNS = [
    # (db_field, label, width, visible_by_default, is_numeric_for_sort)
    ("id", "ID", 70, False, True),
    ("name", "Vendor", 220, True, False),
    ("sap_id", "Supplier SAP ID", 140, True, False),
    ("status", "Status", 100, True, False),
    ("vendor_category", "Vendor Category", 150, False, False),
    ("contact", "Contact", 180, False, False),
    ("address", "Address", 200, False, False),
    ("website", "Website", 180, False, False),
    ("vendor_manager", "Vendor Manager", 150, False, False),
    ("platform", "Platform", 120, False, False),
    ("api_integration", "API Integration", 120, False, True),
    ("payment_terms", "Payment Terms", 150, False, False),
    ("freight_matrix", "Freight Matrix", 150, False, False),
    ("abn", "ABN", 120, False, False),
    ("account_id", "Account ID", 120, True, False),
    ("external_id", "External ID", 120, False, True),
    ("country", "Country", 80, True, False),
    ("postcode", "Postcode", 90, False, False),
    ("updated_at", "Updated", 160, True, False),
]

DEFAULT_VISIBLE_COLUMNS = [c[0] for c in ALL_COLUMNS if c[3]]

# # ------------------------ DATA ACCESS ------------------------



class DataAccess:
    def __init__(self, db_path=DB_FILE):
        self.db_path = db_path
        # Connection for UI thread
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        cur = self.conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            sap_id TEXT,
            status TEXT,
            vendor_category TEXT,
            contact TEXT,
            address TEXT,
            website TEXT,
            vendor_manager TEXT,
            platform TEXT,
            api_integration INTEGER DEFAULT 0,
            payment_terms TEXT,
            freight_matrix TEXT,
            abn TEXT,
            account_id TEXT,
            external_id INTEGER,
            country TEXT,
            postcode TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_account ON suppliers(account_id)")
        self.conn.commit()

    def close(self):
        try:
            self.conn.close()
        except:
            pass

    def seed_demo_if_empty(self):
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM suppliers")
        count = cur.fetchone()[0]
        if count == 0:
            now = dt.datetime.utcnow().isoformat(timespec='seconds')
            demo = [
                ("360 International", "SAP-301382", "Active", "General", "contact@360intl.com", "Sydney NSW", "https://360intl.example", "Alex Wang", "VS", 1, "30 days", "Standard", "12 345 678 901", "301382", 8480, "AU", "2153", now, now),
                ("3D Printers Online", "SAP-301173", "Active", "Tech", "sales@3dpo.com", "Reading, UK", "https://3dpo.example", "Rita Moore", "VS", 1, "14 days", "Matrix A", "98 765 432 100", "301173", 5160, "GB", "RG1 1AR", now, now),
                ("ACME Tools", "SAP-400111", "Inactive", "Hardware", "support@acme.tools", "Melbourne VIC", "https://acme.tools", "John Smith", "Legacy", 0, "EOM+30", "Matrix B", "77 222 333 444", "400111", 9001, "AU", "3000", now, now),
                ("Global Home", "SAP-500222", "Active", "Home", "info@globalhome.io", "Auckland", "https://globalhome.io", "Hannah Lee", "VS", 1, "COD", "Custom", "55 111 222 333", "500222", 9011, "NZ", "1010", now, now),
            ]
            cur.executemany("""
                INSERT INTO suppliers (name, sap_id, status, vendor_category, contact, address, website,
                    vendor_manager, platform, api_integration, payment_terms, freight_matrix, abn, account_id,
                    external_id, country, postcode, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, demo)
            self.conn.commit()

    def _build_where_clause(self, q):
        # q: simple quick filter applied to name/vendor/sap/account_id
        where = ""
        params = []
        if q:
            where = "WHERE (name LIKE ? OR IFNULL(sap_id,'') LIKE ? OR IFNULL(account_id,'') LIKE ?)"
            like = f"%{q}%"
            params.extend([like, like, like])
        return where, params

    def _order_by_clause(self, sort_col, sort_dir):
        if not sort_col:
            return "ORDER BY name COLLATE NOCASE ASC"
        # numeric columns
        numeric_cols = {c[0] for c in ALL_COLUMNS if c[4]}
        if sort_col in numeric_cols:
            return f"ORDER BY CAST({sort_col} AS INTEGER) {sort_dir}"
        # updated_at sort should use datetime (stored ISO)
        if sort_col == "updated_at":
            return f"ORDER BY {sort_col} {sort_dir}"
        # default text sort case-insensitive
        return f"ORDER BY {sort_col} COLLATE NOCASE {sort_dir}"

    def query_page(self, q, sort_col, sort_dir, page_size, page_index):
        where, params = self._build_where_clause(q)
        order = self._order_by_clause(sort_col, sort_dir)
        limit = "LIMIT ? OFFSET ?"
        sql = f"SELECT * FROM suppliers {where} {order} {limit}"
        total_sql = f"SELECT COUNT(*) FROM suppliers {where}"
        cur = self.conn.cursor()
        cur.execute(total_sql, params)
        total = cur.fetchone()[0]
        offset = page_index * page_size
        cur.execute(sql, params + [page_size, offset])
        rows = [dict(r) for r in cur.fetchall()]
        return rows, total

    def get_stats(self):
        cur = self.conn.cursor()
        stats = {}
        cur.execute("SELECT COUNT(*) FROM suppliers")
        stats["total"] = cur.fetchone()[0]

        cur.execute("SELECT status, COUNT(*) c FROM suppliers GROUP BY status ORDER BY c DESC")
        stats["by_status"] = [(r[0] or "Unknown", r[1]) for r in cur.fetchall()]

        cur.execute("SELECT country, COUNT(*) c FROM suppliers GROUP BY country ORDER BY c DESC LIMIT 5")
        stats["top_countries"] = [(r[0] or "Unknown", r[1]) for r in cur.fetchall()]
        return stats

    def upsert_supplier(self, conn, s):
        """
        Upsert by account_id if present else by (name, external_id).
        'conn' is a separate sqlite3 connection passed by background thread.
        """
        # Ensure fields exist
        fields = {
            "name": s.get("name"),
            "sap_id": s.get("sap_id"),
            "status": s.get("status"),
            "vendor_category": s.get("vendor_category"),
            "contact": s.get("contact"),
            "address": s.get("address"),
            "website": s.get("website"),
            "vendor_manager": s.get("vendor_manager"),
            "platform": s.get("platform"),
            "api_integration": int(bool(s.get("api_integration"))),
            "payment_terms": s.get("payment_terms"),
            "freight_matrix": s.get("freight_matrix"),
            "abn": s.get("abn"),
            "account_id": s.get("account_id"),
            "external_id": s.get("external_id"),
            "country": s.get("country"),
            "postcode": s.get("postcode"),
            "updated_at": dt.datetime.utcnow().isoformat(timespec='seconds'),
        }
        cur = conn.cursor()
        # Strategy: try match by account_id first
        if fields["account_id"]:
            cur.execute("SELECT id FROM suppliers WHERE account_id = ?", (fields["account_id"],))
            existing = cur.fetchone()
            if existing:
                set_clause = ", ".join([f"{k} = ?" for k in fields.keys()])
                cur.execute(f"UPDATE suppliers SET {set_clause} WHERE id = ?", list(fields.values()) + [existing[0]])
            else:
                fields["created_at"] = dt.datetime.utcnow().isoformat(timespec='seconds')
                cols = ", ".join(fields.keys() | {"created_at"})
                qmarks = ", ".join(["?"] * (len(fields) + 1))
                cur.execute(f"INSERT INTO suppliers ({cols}) VALUES ({qmarks})",
                            list(fields.values()) + [fields["created_at"]])
        else:
            # Fallback match by (name, external_id)
            cur.execute("SELECT id FROM suppliers WHERE name = ? AND IFNULL(external_id, -1) = IFNULL(?, -1)",
                        (fields["name"], fields["external_id"]))
            existing = cur.fetchone()
            if existing:
                set_clause = ", ".join([f"{k} = ?" for k in fields.keys()])
                cur.execute(f"UPDATE suppliers SET {set_clause} WHERE id = ?", list(fields.values()) + [existing[0]])
            else:
                fields["created_at"] = dt.datetime.utcnow().isoformat(timespec='seconds')
                cols = ", ".join(fields.keys() | {"created_at"})
                qmarks = ", ".join(["?"] * (len(fields) + 1))
                cur.execute(f"INSERT INTO suppliers ({cols}) VALUES ({qmarks})",
                            list(fields.values()) + [fields["created_at"]])

    def get_supplier_by_id(self, rec_id):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM suppliers WHERE id = ?", (rec_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def update_supplier(self, rec_id, fields):
        # Ensure updated_at always refreshed
        fields = dict(fields)
        fields["updated_at"] = dt.datetime.utcnow().isoformat(timespec='seconds')
        set_clause = ", ".join([f"{k} = ?" for k in fields.keys()])
        params = list(fields.values()) + [rec_id]
        cur = self.conn.cursor()
        cur.execute(f"UPDATE suppliers SET {set_clause} WHERE id = ?", params)
        self.conn.commit()




# from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, func
# from sqlalchemy.orm import declarative_base, sessionmaker
# import datetime

# DB_FILE = "suppliers.db"
# engine = create_engine(f"sqlite:///{DB_FILE}", echo=False)
# Session = sessionmaker(bind=engine)
# Base = declarative_base()

# class Supplier(Base):
#     __tablename__ = 'suppliers'

#     id = Column(Integer, primary_key=True, autoincrement=True)
#     name = Column(String)
#     sap_id = Column(String)
#     status = Column(String)
#     vendor_category = Column(String)
#     contact = Column(String)
#     address = Column(String)
#     website = Column(String)
#     vendor_manager = Column(String)
#     platform = Column(String)
#     api_integration = Column(Boolean, default=False)
#     payment_terms = Column(String)
#     freight_matrix = Column(String)
#     abn = Column(String)
#     account_id = Column(String)
#     external_id = Column(Integer)
#     country = Column(String)
#     postcode = Column(String)
#     created_at = Column(DateTime, default=func.now())
#     updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

# Base.metadata.create_all(engine)

# class DataAccess:
#     def __init__(self):
#         self.session = Session()

#     def close(self):
#         self.session.close()

#     def seed_demo_if_empty(self):
#         if self.session.query(Supplier).count() == 0:
#             now = datetime.datetime.utcnow()
#             demo_suppliers = [
#                 Supplier(name="360 International", sap_id="SAP-301382", status="Active", vendor_category="General",
#                          contact="contact@360intl.com", address="Sydney NSW", website="https://360intl.example",
#                          vendor_manager="Alex Wang", platform="VS", api_integration=True, payment_terms="30 days",
#                          freight_matrix="Standard", abn="12 345 678 901", account_id="301382", external_id=8480,
#                          country="AU", postcode="2153", created_at=now, updated_at=now),
#                 Supplier(name="3D Printers Online", sap_id="SAP-301173", status="Active", vendor_category="Tech",
#                          contact="sales@3dpo.com", address="Reading, UK", website="https://3dpo.example",
#                          vendor_manager="Rita Moore", platform="VS", api_integration=True, payment_terms="14 days",
#                          freight_matrix="Matrix A", abn="98 765 432 100", account_id="301173", external_id=5160,
#                          country="GB", postcode="RG1 1AR", created_at=now, updated_at=now),
#                 Supplier(name="ACME Tools", sap_id="SAP-400111", status="Inactive", vendor_category="Hardware",
#                          contact="support@acme.tools", address="Melbourne VIC", website="https://acme.tools",
#                          vendor_manager="John Smith", platform="Legacy", api_integration=False, payment_terms="EOM+30",
#                          freight_matrix="Matrix B", abn="77 222 333 444", account_id="400111", external_id=9001,
#                          country="AU", postcode="3000", created_at=now, updated_at=now),
#                 Supplier(name="Global Home", sap_id="SAP-500222", status="Active", vendor_category="Home",
#                          contact="info@globalhome.io", address="Auckland", website="https://globalhome.io",
#                          vendor_manager="Hannah Lee", platform="VS", api_integration=True, payment_terms="COD",
#                          freight_matrix="Custom", abn="55 111 222 333", account_id="500222", external_id=9011,
#                          country="NZ", postcode="1010", created_at=now, updated_at=now),
#             ]
#             self.session.add_all(demo_suppliers)
#             self.session.commit()
# ------------------------ API CLIENT ------------------------

# class ApiClient:
#     def __init__(self, api_auth):
#         self.api_auth = api_auth

#     def _http_get_json(self, url):
#         req = urllib.request.Request(url)
#         if self.api_auth:
#             req.add_header("Authorization", self.api_auth)
#         req.add_header("Accept", "application/json")
#         with urllib.request.urlopen(req, timeout=30) as resp:
#             data = resp.read()
#             return json.loads(data.decode("utf-8"))

#     def _fetch_all_paginated(self, first_url):
#         """Follow RFC5988-style pagination via 'next' field (per API samples)."""
#         results = []
#         url = first_url
#         while url:
#             payload = self._http_get_json(url)
#             for r in payload.get("results", []):
#                 results.append(r)
#             url = payload.get("next")
#         return results

#     def fetch_suppliers_merged(self):
#         """Fetch products+orders suppliers and merge by account_id/name."""
#         products = self._fetch_all_paginated(API_URL_PRODUCTS)
#         orders = self._fetch_all_paginated(API_URL_ORDERS)

#         # Index orders by account_id & by name (fallback)
#         ord_by_acc = {}
#         ord_by_name = {}
#         for o in orders:
#             acc = o.get("account_id")
#             nm = o.get("name")
#             ord_by_acc[acc] = o
#             if nm:
#                 ord_by_name[nm.lower()] = o

#         merged = []
#         for p in products:
#             acc = p.get("account_id")
#             nm = p.get("name")
#             o = ord_by_acc.get(acc) or (ord_by_name.get(nm.lower()) if nm else None)
#             merged.append({
#                 "name": p.get("name") or (o.get("name") if o else None),
#                 "sap_id": None,              # Not provided by API - remains None for user to fill
#                 "status": "Active",          # Default guess - editable in app
#                 "vendor_category": None,
#                 "contact": None,
#                 "address": None,
#                 "website": None,
#                 "vendor_manager": None,
#                 "platform": "VS",
#                 "api_integration": True,
#                 "payment_terms": None,
#                 "freight_matrix": None,
#                 "abn": None,
#                 "account_id": p.get("account_id") or (o.get("account_id") if o else None),
#                 "external_id": (o.get("id") if o else None),
#                 "country": p.get("country"),
#                 "postcode": p.get("postcode"),
#             })

#         # Also add any orders that didn't appear in products
#         seen_acc = {m["account_id"] for m in merged if m.get("account_id")}
#         for o in orders:
#             acc = o.get("account_id")
#             if acc and acc not in seen_acc:
#                 merged.append({
#                     "name": o.get("name"),
#                     "sap_id": None,
#                     "status": "Active",
#                     "vendor_category": None,
#                     "contact": None,
#                     "address": None,
#                     "website": None,
#                     "vendor_manager": None,
#                     "platform": "VS",
#                     "api_integration": True,
#                     "payment_terms": None,
#                     "freight_matrix": None,
#                     "abn": None,
#                     "account_id": o.get("account_id"),
#                     "external_id": o.get("id"),
#                     "country": None,
#                     "postcode": None,
#                 })

#         return merged
import requests

class ApiClient:
    def __init__(self, api_auth):
        self.api_auth = api_auth
        self.headers = {
            "Accept": "application/json"
        }
        if self.api_auth:
            self.headers["Authorization"] = self.api_auth

    def _http_get_json(self, url):
        try:
            resp = requests.get(url, headers=self.headers, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            print(f"API request failed: {e}")
            return {}

    def _fetch_all_paginated(self, first_url):
        results = []
        url = first_url
        while url:
            payload = self._http_get_json(url)
            results.extend(payload.get("results", []))
            url = payload.get("next")
        return results

    def fetch_suppliers_merged(self):
        products = self._fetch_all_paginated(API_URL_PRODUCTS)
        orders = self._fetch_all_paginated(API_URL_ORDERS)

        ord_by_acc = {}
        ord_by_name = {}
        for o in orders:
            acc = o.get("account_id")
            nm = o.get("name")
            ord_by_acc[acc] = o
            if nm:
                ord_by_name[nm.lower()] = o

        merged = []
        for p in products:
            acc = p.get("account_id")
            nm = p.get("name")
            o = ord_by_acc.get(acc) or (ord_by_name.get(nm.lower()) if nm else None)
            merged.append({
                "name": p.get("name") or (o.get("name") if o else None),
                "sap_id": None,
                "status": "Active",
                "vendor_category": None,
                "contact": None,
                "address": None,
                "website": None,
                "vendor_manager": None,
                "platform": "VS",
                "api_integration": True,
                "payment_terms": None,
                "freight_matrix": None,
                "abn": None,
                "account_id": p.get("account_id") or (o.get("account_id") if o else None),
                "external_id": (o.get("id") if o else None),
                "country": p.get("country"),
                "postcode": p.get("postcode"),
            })

        seen_acc = {m["account_id"] for m in merged if m.get("account_id")}
        for o in orders:
            acc = o.get("account_id")
            if acc and acc not in seen_acc:
                merged.append({
                    "name": o.get("name"),
                    "sap_id": None,
                    "status": "Active",
                    "vendor_category": None,
                    "contact": None,
                    "address": None,
                    "website": None,
                    "vendor_manager": None,
                    "platform": "VS",
                    "api_integration": True,
                    "payment_terms": None,
                    "freight_matrix": None,
                    "abn": None,
                    "account_id": o.get("account_id"),
                    "external_id": o.get("id"),
                    "country": None,
                    "postcode": None,
                })

        return merged
# ------------------------ BACKGROUND SYNC ------------------------

class SyncWorker(threading.Thread):
    def __init__(self, db_path, api_auth, progress_queue):
        super().__init__(daemon=True)
        self.db_path = db_path
        self.api_auth = api_auth
        self.progress_queue = progress_queue

    def run(self):
        conn = None
        try:
            self._push(("status", "Sync started..."))
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            api = ApiClient(self.api_auth)
            merged = api.fetch_suppliers_merged()
            total = len(merged)
            self._push(("status", f"Fetched {total} records, writing to DB..."))
            da = DataAccess(self.db_path)  # to reuse upsert logic; but will open another conn; we won’t use its UI conn
            # Use local conn for upserts to ensure thread isolation:
            for i, item in enumerate(merged, start=1):
                da.upsert_supplier(conn, item)
                if i % 50 == 0 or i == total:
                    conn.commit()
                    self._push(("progress", i, total))
            conn.commit()
            self._push(("status", "Sync complete."))
            self._push(("done",))
        except Exception as ex:
            self._push(("error", f"Sync failed: {ex}\n{traceback.format_exc()}"))
        finally:
            try:
                if conn:
                    conn.close()
            except:
                pass

    def _push(self, msg):
        try:
            self.progress_queue.put_nowait(msg)
        except:
            pass

# ------------------------ EDIT DIALOG ------------------------

class EditDialog(Toplevel):
    def __init__(self, master, data_access: DataAccess, rec_id: int, on_saved):
        super().__init__(master)
        self.title("Edit Supplier")
        self.configure(bg=TOKYO["bg"])
        self.resizable(True, True)
        self.da = data_access
        self.rec_id = rec_id
        self.on_saved = on_saved

        self.fields = self.da.get_supplier_by_id(rec_id) or {}
        self.vars = {}
        # Container
        container = ttk.Frame(self)
        container.pack(fill=BOTH, expand=True, padx=16, pady=16)

        form_fields = [
            ("name", "Vendor"), ("sap_id", "Supplier SAP ID"), ("status", "Status"),
            ("vendor_category", "Vendor Category"), ("contact", "Contact"),
            ("address", "Address"), ("website", "Website"), ("vendor_manager", "Vendor Manager"),
            ("platform", "Platform"), ("api_integration", "API Integration (0/1)"),
            ("payment_terms", "Payment Terms"), ("freight_matrix", "Freight Matrix"),
            ("abn", "ABN"), ("account_id", "Account ID"), ("external_id", "External ID"),
            ("country", "Country"), ("postcode", "Postcode"),
        ]

        # Layout grid
        for i, (key, label) in enumerate(form_fields):
            ttk.Label(container, text=label).grid(row=i, column=0, sticky=E, padx=(0,8), pady=4)
            var = StringVar(value=str(self.fields.get(key, "") if self.fields.get(key) is not None else ""))
            self.vars[key] = var
            entry = ttk.Entry(container, textvariable=var)
            if key in ("address",):
                entry = ttk.Entry(container, textvariable=var, width=60)
            entry.grid(row=i, column=1, sticky=W, padx=(0,8), pady=4)

        # Buttons
        btns = ttk.Frame(container)
        btns.grid(row=len(form_fields), column=0, columnspan=2, sticky=E, pady=(12,0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side=RIGHT, padx=8)
        ttk.Button(btns, text="Save", command=self._save).pack(side=RIGHT)

        # Style adjustments
        self._apply_theme()

    def _apply_theme(self):
        self.option_add("*Toplevel*background", TOKYO["bg"])
        for child in self.winfo_children():
            pass  # Using ttk theme set globally

    def _save(self):
        # Sanitize & convert fields
        fields = {}
        for k, var in self.vars.items():
            v = var.get().strip()
            if k in ("external_id", "api_integration"):
                try:
                    v = int(v) if v != "" else None
                except:
                    v = None
            fields[k] = v if v != "" else None

        try:
            self.da.update_supplier(self.rec_id, fields)
            if self.on_saved:
                self.on_saved()
            self.destroy()
        except Exception as ex:
            messagebox.showerror("Error", f"Failed to save: {ex}")

# ------------------------ TABLE VIEW ------------------------
        sel = self.tree.selection()
        if not sel:
            return

        item_id = sel[0]
        try:
            rec_id = self.tree.item(item_id)["values"][0]  # Assuming first column is ID
            rec_id = int(rec_id)
        except Exception as e:
            print("Failed to get rec_id:", e)
            return

        def on_saved():
            self.refresh_table()

        EditDialog(self, self.da, rec_id, on_saved)

class TableView(ttk.Frame):
    def __init__(self, master, data_access: DataAccess):
        super().__init__(master)
        self.da = data_access
        self.q = StringVar(value="")
        self.page_size = IntVar(value=DEFAULT_PAGE_SIZE)
        self.page_index = IntVar(value=0)
        self.sort_col = StringVar(value="name")
        self.sort_dir = StringVar(value="ASC")
        self.visible_columns = set(DEFAULT_VISIBLE_COLUMNS)

        self._build_ui()
        self.refresh_table()

    def _build_ui(self):
        # Top bar: filter + pager + actions
        top = ttk.Frame(self)
        top.pack(fill=X, pady=(0,6))

        # Quick filter
        ttk.Label(top, text="Quick Filter:").pack(side=LEFT, padx=(0,8))
        entry = ttk.Entry(top, textvariable=self.q, width=30)
        entry.pack(side=LEFT, padx=(0,12))
        entry.bind("<Return>", lambda e: self._apply_filter())

        ttk.Button(top, text="Apply", command=self._apply_filter).pack(side=LEFT, padx=(0,8))
        ttk.Button(top, text="Clear", command=self._clear_filter).pack(side=LEFT)

        # Spacer
        ttk.Label(top, text=" ").pack(side=LEFT, padx=16)

        # Page size
        ttk.Label(top, text="Page Size:").pack(side=LEFT)
        ps = ttk.Combobox(top, values=PAGE_SIZE_OPTIONS, state="readonly", width=5, textvariable=self.page_size)
        ps.pack(side=LEFT, padx=(4,12))
        ps.bind("<<ComboboxSelected>>", lambda e: self._set_page_size())

        # Pager buttons
        ttk.Button(top, text="Prev", command=self._prev_page).pack(side=LEFT)
        ttk.Button(top, text="Next", command=self._next_page).pack(side=LEFT, padx=(6,12))

        self.page_info = ttk.Label(top, text="")
        self.page_info.pack(side=LEFT)

        # Right side actions
        right = ttk.Frame(top)
        right.pack(side=RIGHT)
        ttk.Button(right, text="Columns", command=self._open_columns_dialog).pack(side=LEFT, padx=(0,8))
        ttk.Button(right, text="Export CSV", command=self._export_csv).pack(side=LEFT)

        # Treeview
        self.tree = ttk.Treeview(self, columns=[c[0] for c in ALL_COLUMNS], show="headings", height=20)
        self.tree.pack(fill=BOTH, expand=True)
        self.tree.bind("<Double-1>", self._on_double_click)

        # Scrollbars
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscroll=vsb.set, xscroll=hsb.set)
        vsb.place(relx=1.0, rely=0, relheight=1.0, anchor="ne")
        hsb.pack(fill=X)

        # Configure headings and columns
        for (field, label, width, _, _) in ALL_COLUMNS:
            self.tree.heading(field, text=label, command=lambda f=field: self._toggle_sort(f))
            self.tree.column(field, minwidth=50, width=width, anchor="w")

        self._apply_visible_columns()
        self._apply_theme()

    def _apply_theme(self):
        # Styling done at app level; here we ensure tag colors for selection.
        style = ttk.Style()
        # Treeview row tags for striking colors if needed
        self.tree.tag_configure("muted", foreground=TOKYO["muted"])

    # --- Actions ---
    def _apply_filter(self):
        self.page_index.set(0)
        self.refresh_table()

    def _clear_filter(self):
        self.q.set("")
        self.page_index.set(0)
        self.refresh_table()

    def _set_page_size(self):
        self.page_index.set(0)
        self.refresh_table()

    def _prev_page(self):
        if self.page_index.get() > 0:
            self.page_index.set(self.page_index.get() - 1)
            self.refresh_table()

    def _next_page(self):
        # Only advance if not at end (checked after fetch)
        self.page_index.set(self.page_index.get() + 1)
        self.refresh_table()

    def _toggle_sort(self, field):
        if self.sort_col.get() == field:
            self.sort_dir.set("DESC" if self.sort_dir.get() == "ASC" else "ASC")
        else:
            self.sort_col.set(field)
            self.sort_dir.set("ASC")
        self.page_index.set(0)
        self.refresh_table()

    def _apply_visible_columns(self):
        all_cols = [c[0] for c in ALL_COLUMNS]
        display = [c for c in all_cols if c in self.visible_columns]
        if not display:
            display = ["name"]
            self.visible_columns = {"name"}
        self.tree["displaycolumns"] = display

    def _open_columns_dialog(self):
        win = Toplevel(self)
        win.title("Columns")
        win.configure(bg=TOKYO["bg"])
        frm = ttk.Frame(win)
        frm.pack(fill=BOTH, expand=True, padx=12, pady=12)

        checks = {}
        for i, (field, label, _, default, _) in enumerate(ALL_COLUMNS):
            var = BooleanVar(value=(field in self.visible_columns))
            chk = ttk.Checkbutton(frm, text=label, variable=var)
            chk.grid(row=i//2, column=i%2, sticky=W, padx=8, pady=4)
            checks[field] = var

        def apply_and_close():
            self.visible_columns = {f for f, v in checks.items() if v.get()}
            self._apply_visible_columns()
            win.destroy()
        btns = ttk.Frame(frm)
        btns.grid(row=(len(ALL_COLUMNS)//2)+2, column=0, columnspan=2, sticky=E, pady=(8,0))
        ttk.Button(btns, text="Close", command=win.destroy).pack(side=RIGHT, padx=8)
        ttk.Button(btns, text="Apply", command=apply_and_close).pack(side=RIGHT)

    def _export_csv(self):
        # Export the same data currently displayed (page, filter, sort)
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not filename:
            return
        try:
            # Re-query page
            rows, total = self.da.query_page(
                q=self.q.get().strip(),
                sort_col=self.sort_col.get(),
                sort_dir=self.sort_dir.get(),
                page_size=self.page_size.get(),
                page_index=self.page_index.get()
            )
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                headers = [c[1] for c in ALL_COLUMNS if c[0] in self.visible_columns]
                fields = [c[0] for c in ALL_COLUMNS if c[0] in self.visible_columns]
                writer.writerow(headers)
                for r in rows:
                    writer.writerow([r.get(k, "") if r.get(k, "") is not None else "" for k in fields])
            messagebox.showinfo("Export", f"Exported {len(rows)} rows to:\n{filename}")
        except Exception as ex:
            messagebox.showerror("Export Failed", str(ex))

    def _on_double_click(self, event):
        try:
            sel = self.tree.selection()
            if not sel:
                return
            rec_id = self.tree.item(sel[0])["values"][0]  # Assuming first column is ID

            def on_saved():
                self.refresh_table()

            EditDialog(self, self.da, rec_id, on_saved)
        except Exception as e:
            print("Double-click error:", e)

    # --- Data refresh ---
    def refresh_table(self):
        rows, total = self.da.query_page(
            q=self.q.get().strip(),
            sort_col=self.sort_col.get(),
            sort_dir=self.sort_dir.get(),
            page_size=self.page_size.get(),
            page_index=self.page_index.get()
        )
        # If page index too high (e.g. after filter change), reset to last page
        max_page_idx = max((total - 1) // self.page_size.get(), 0)
        if self.page_index.get() > max_page_idx:
            self.page_index.set(max_page_idx)
            rows, total = self.da.query_page(
                q=self.q.get().strip(),
                sort_col=self.sort_col.get(),
                sort_dir=self.sort_dir.get(),
                page_size=self.page_size.get(),
                page_index=self.page_index.get()
            )

        for i in self.tree.get_children():
            self.tree.delete(i)

        # Insert rows
        for r in rows:
            values = [r.get(c[0], "") if r.get(c[0]) is not None else "" for c in ALL_COLUMNS]
            self.tree.insert("", END, values=values)

        # Update page info
        start = self.page_index.get() * self.page_size.get()
        end = start + len(rows)
        if total == 0:
            label = "No results"
        else:
            label = f"Page {self.page_index.get()+1} / {max_page_idx+1}  —  items {start+1} {end} of {total}"
        self.page_info.config(text=label)

# ------------------------ LEFT PANEL (ACTIONS + STATS) ------------------------

class LeftPanel(ttk.Frame):
    def __init__(self, master, data_access: DataAccess, on_sync):
        super().__init__(master)
        self.da = data_access
        self.on_sync = on_sync
        self.status_label = None
        self.progress = None
        self._build_ui()
        # self.left_panel.pack(fill=Y, expand=False)
        # self.table.pack(fill=BOTH, expand=True)
        self.refresh_stats()

    def _build_ui(self):
        # Action buttons
        actions = ttk.Frame(self)
        actions.pack(fill=X, pady=6)
        ttk.Button(actions, text="Sync", command=self.on_sync).pack(fill=X, pady=(0,8))
        self.status_label = ttk.Label(actions, text="", foreground=TOKYO["muted"])
        self.status_label.pack(fill=X, pady=(0,8))
        self.progress = ttk.Progressbar(actions, mode="indeterminate")
        # Not packing by default; pack when syncing

        # Stats
        sep = ttk.Separator(self)
        sep.pack(fill=X, pady=6)
        ttk.Label(self, text="Dashboard Stats", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0,6))

        self.stats_total = ttk.Label(self, text="Total: —", font=("Segoe UI", 10))
        self.stats_total.pack(anchor="w", pady=2)

        self.stats_status = ttk.Frame(self)
        self.stats_status.pack(fill=X, pady=2)

        self.stats_countries = ttk.Frame(self)
        self.stats_countries.pack(fill=X, pady=6)

    def refresh_stats(self):
        stats = self.da.get_stats()
        self.stats_total.config(text=f"Total suppliers: {stats.get('total', 0)}")

        # By status
        for w in self.stats_status.winfo_children():
            w.destroy()
        ttk.Label(self.stats_status, text="By status:", foreground=TOKYO["muted"]).pack(anchor="w")
        for (status, c) in stats.get("by_status", []):
            color = TOKYO["success"] if (status or "").lower() == "active" else TOKYO["warn"]
            ttk.Label(self.stats_status, text=f"• {status}: {c}", foreground=color).pack(anchor="w")

        # Top countries
        for w in self.stats_countries.winfo_children():
            w.destroy()
        ttk.Label(self.stats_countries, text="Top countries:", foreground=TOKYO["muted"]).pack(anchor="w")
        for (ctry, c) in stats.get("top_countries", []):
            ttk.Label(self.stats_countries, text=f"• {ctry}: {c}").pack(anchor="w")

    # ---- Sync visual states ----
    def show_sync_start(self, msg="Syncing..."):
        self.status_label.config(text=msg, foreground=TOKYO["accent"])
        self.progress.pack(fill=X)
        self.progress.start(12)

    def show_sync_progress(self, i, total):
        self.status_label.config(text=f"Updating DB: {i}/{total}")

    def show_sync_done(self, msg="Sync complete"):
        self.progress.stop()
        self.progress.pack_forget()
        self.status_label.config(text=msg, foreground=TOKYO["success"])
        self.refresh_stats()

    def show_sync_error(self, msg):
        self.progress.stop()
        self.progress.pack_forget()
        self.status_label.config(text=msg, foreground=TOKYO["error"])

# ------------------------ APP ------------------------

class SupplierApp(Tk):
    def __init__(self):
        super().__init__()
        self.title("Supplier Dashboard")
        self.geometry("1280x720")
        self.configure(bg=TOKYO["bg"])
        self.minsize(1100, 600)

        # Style / theme
        self._apply_tokyo_ttk_theme()

        # Data
        self.da = DataAccess(DB_FILE)
        self.da.seed_demo_if_empty()

        # Layout: left panel (controls+stats), right panel (table)
        root = ttk.Frame(self)
        root.pack(fill=BOTH, expand=True)

        left = ttk.Frame(root, padding=8)
        left.configure(style="Left.TFrame")
        left.pack(side=LEFT, fill=Y)
        right = ttk.Frame(root, padding=8)
        right.pack(side=RIGHT, fill=BOTH, expand=True)

        self.progress_queue = queue.Queue()
        self.sync_worker = None

        # Left panel
        self.left_panel = LeftPanel(left, self.da, self._start_sync)

        # Right panel: header + table
        header = ttk.Frame(right)
        header.pack(fill=X, pady=(0,8))
        ttk.Label(header, text="Suppliers", font=("Segoe UI", 13, "bold")).pack(side=LEFT)
        self.table = TableView(right, self.da)
        self._poll_progress_queue()

    def _apply_tokyo_ttk_theme(self):
        style = ttk.Style()
        # Use 'clam' as base to allow color customizations
        try:
            style.theme_use("clam")
        except:
            pass

        # General colors
        style.configure(".", background=TOKYO["bg"], foreground=TOKYO["fg"], fieldbackground=TOKYO["bg_lighter"])
        style.configure("TFrame", background=TOKYO["bg"])
        style.configure("Left.TFrame", background=TOKYO["bg_darker"])
        style.configure("TLabel", background=TOKYO["bg"], foreground=TOKYO["fg"])
        style.configure("TButton",
                        background=TOKYO["bg_lighter"],
                        foreground=TOKYO["fg"],
                        bordercolor=TOKYO["border"],
                        focusthickness=3,
                        focuscolor=TOKYO["selection"])
        style.map("TButton",
                  background=[("active", TOKYO["bg_lighter"])],
                  foreground=[("disabled", TOKYO["muted"])])
        style.configure("TEntry",
                        fieldbackground=TOKYO["bg_lighter"],
                        foreground=TOKYO["fg"],
                        bordercolor=TOKYO["border"])
        style.configure("TCombobox",
                        fieldbackground=TOKYO["bg_lighter"],
                        background=TOKYO["bg_lighter"],
                        foreground=TOKYO["fg"])
        style.configure("Treeview",
                        background=TOKYO["bg_lighter"],
                        foreground=TOKYO["fg"],
                        fieldbackground=TOKYO["bg_lighter"],
                        bordercolor=TOKYO["border"])
        style.configure("Treeview.Heading",
                        background=TOKYO["bg_darker"],
                        foreground=TOKYO["fg"])
        style.map("Treeview",
                  background=[("selected", TOKYO["selection"])],
                  foreground=[("selected", TOKYO["fg"])])

        style.configure("TProgressbar",
                        background=TOKYO["accent"],
                        troughcolor=TOKYO["bg_lighter"])

    def _start_sync(self):
        if self.sync_worker and self.sync_worker.is_alive():
            messagebox.showinfo("Sync", "A sync is already running.")
            return

        api_auth = self._resolve_api_auth()
        if not api_auth:
            messagebox.showwarning("API Auth Missing",
                                   "No API auth found. Set environment variable API_AUTH or config.json {\"api_auth\": \"Basic ...\"}")
            return

        self.left_panel.show_sync_start("Fetching from API...")
        self.sync_worker = SyncWorker(DB_FILE, api_auth, self.progress_queue)
        self.sync_worker.start()

    def _resolve_api_auth(self):
        # 1) Env var
        auth_env = os.environ.get("API_AUTH")
        if auth_env:
            return auth_env.strip()
        # 2) config.json
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
                if cfg.get("api_auth"):
                    return cfg["api_auth"].strip()
        except:
            pass
        return None

    def _poll_progress_queue(self):
        try:
            while True:
                msg = self.progress_queue.get_nowait()
                self._handle_progress_message(msg)
        except queue.Empty:
            pass
        self.after(120, self._poll_progress_queue)

    def _handle_progress_message(self, msg):
        if not msg:
            return
        typ = msg[0]
        if typ == "status":
            self.left_panel.status_label.config(text=msg[1], foreground=TOKYO["accent"])
        elif typ == "progress":
            _, i, total = msg
            self.left_panel.show_sync_progress(i, total)
        elif typ == "done":
            self.left_panel.show_sync_done()
            self.table.refresh_table()
        elif typ == "error":
            self.left_panel.show_sync_error(msg[1])
            messagebox.showerror("Sync Error", msg[1])

# ------------------------ MAIN ------------------------

def main():
    app = SupplierApp()
    app.mainloop()

if __name__ == "__main__":
    main()
