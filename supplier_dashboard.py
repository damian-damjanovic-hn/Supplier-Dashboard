#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modern Supplier Dashboard - Tkinter + SQLite
Author: Damian Damjanovic (assisted by M365 Copilot)
Description:
  - Dark "Tokyo Night" themed dashboard with left stats and right data table
  - Full CRUD via dialogs
  - Sorting by clicking table headers (ASC/DESC)
  - Pagination with selectable page size, prev/next, counts
  - Column visibility toggles (persisted)
  - CSV export of current page respecting filter and visibility
  - Background worker threads for DB fetches to keep UI responsive
  - Minimal dependencies (standard library only)

Tested with Python 3.10+ on Windows/macOS/Linux.
"""

import os
import sqlite3
import threading
import queue
import random
import string
import json
import csv
from datetime import datetime
import tkinter as tk

from tkinter import (
    Tk, Toplevel, StringVar, IntVar, BooleanVar, BOTH, LEFT, RIGHT, X, Y, W, E, N, S, END, DISABLED, NORMAL
)
from tkinter import messagebox, filedialog
from tkinter import ttk

# ---------------------- Theming (Tokyo Night) ---------------------- #
TOKYO = {
    "bg": "#1a1b26",
    "bg_alt": "#24283b",
    "bg_alt2": "#1f2335",
    "fg": "#c0caf5",
    "muted": "#565f89",
    "accent": "#7aa2f7",
    "green": "#9ece6a",
    "orange": "#ff9e64",
    "magenta": "#bb9af7",
    "red": "#f7768e",
    "cyan": "#7dcfff",
    "yellow": "#e0af68",
    "row_odd": "#1e2233",
    "row_even": "#1b1f30",
    "border": "#2e344a",
}

APP_TITLE = "Modern Supplier Dashboard"
DB_FILE = "suppliers.db"
SETTINGS_FILE = "supplier_dashboard_settings.json"

# ---------------------- Columns Configuration ---------------------- #
COLUMNS = [
    {"id": "id",               "text": "ID",                 "width": 70,  "anchor": "center", "visible": False},
    {"id": "name",             "text": "Name",               "width": 220, "anchor": "w",      "visible": True},
    {"id": "account_id",       "text": "Account ID",         "width": 110, "anchor": "center", "visible": True},
    {"id": "sap_id",           "text": "Supplier SAP ID",    "width": 120, "anchor": "center", "visible": True},
    {"id": "status",           "text": "Status",             "width": 110, "anchor": "center", "visible": True},
    {"id": "product_category", "text": "Product Category",   "width": 150, "anchor": "w",      "visible": True},
    {"id": "contact",          "text": "Contact",            "width": 170, "anchor": "w",      "visible": False},
    {"id": "address",          "text": "Address",            "width": 220, "anchor": "w",      "visible": False},
    {"id": "website",          "text": "Website",            "width": 160, "anchor": "w",      "visible": False},
    {"id": "vendor_manager",   "text": "Vendor Manager",     "width": 150, "anchor": "w",      "visible": False},
    {"id": "platform",         "text": "Platform",           "width": 120, "anchor": "center", "visible": False},
    {"id": "api_integration",  "text": "API Integration",    "width": 130, "anchor": "center", "visible": False},
    {"id": "payment_terms",    "text": "Payment Terms",      "width": 130, "anchor": "center", "visible": False},
    {"id": "freight_matrix",   "text": "Freight Matrix",     "width": 130, "anchor": "center", "visible": False},
    {"id": "abn",              "text": "ABN",                "width": 140, "anchor": "center", "visible": True},
    {"id": "country",          "text": "Country",            "width": 80,  "anchor": "center", "visible": True},
    {"id": "postcode",         "text": "Postcode",           "width": 90,  "anchor": "center", "visible": False},
    {"id": "source",           "text": "Source",             "width": 90,  "anchor": "center", "visible": False},
]

DEFAULT_PAGE_SIZE = 25
PAGE_SIZES = [10, 25, 50, 100, 200]

# ---------------------- Database Utilities ---------------------- #

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    account_id TEXT,
    sap_id TEXT,
    status TEXT,
    product_category TEXT,
    contact TEXT,
    address TEXT,
    website TEXT,
    vendor_manager TEXT,
    platform TEXT,
    api_integration TEXT,
    payment_terms TEXT,
    freight_matrix TEXT,
    abn TEXT,
    country TEXT,
    postcode TEXT,
    source TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

TRIGGER_UPDATED_AT = """
CREATE TRIGGER IF NOT EXISTS trg_suppliers_updated_at
AFTER UPDATE ON suppliers
FOR EACH ROW BEGIN
    UPDATE suppliers SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
END;
"""

def get_conn():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_db(seed_demo=False):
    conn = get_conn()
    with conn:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(TRIGGER_UPDATED_AT)
    if seed_demo:
        seed_demo_data(conn, n=250)
    conn.close()

def seed_demo_data(conn, n=250):
    statuses = ["Active", "Inactive", "Onboard", "Pending"]
    categories = ["Electronics", "Apparel", "Home", "Beauty", "Sports", "Grocery"]
    platforms = ["Shopify", "Magento", "Custom", "BigCommerce", "SAP Commerce"]
    sources = ["Manual", "API", "CSV Import"]
    payment_terms = ["Prepaid", "Net 7", "Net 14", "Net 30", "Net 45"]
    countries = ["AU", "NZ", "US", "CN", "DE", "IN", "UK"]

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM suppliers")
    count = cur.fetchone()[0]
    if count > 0:
        return
    rng = random.Random(42)
    rows = []
    for i in range(n):
        name = f"Supplier {i+1} - {rng.choice(['Alpha','Beta','Gamma','Delta','Epsilon'])}"
        account_id = f"ACC{rng.randint(10000, 99999)}"
        sap_id = f"SAP{rng.randint(100000, 999999)}"
        status = rng.choice(statuses)
        category = rng.choice(categories)
        contact = f"{rng.choice(['Liam','Olivia','Noah','Emma','Amelia','Ava'])} {rng.choice(['Smith','Brown','Taylor','Wilson','Martin'])} <{rng.choice(['ops','sales','admin'])}@example.com>"
        address = f"{rng.randint(10, 999)} Example St, {rng.choice(['Sydney','Melbourne','Brisbane','Perth','Adelaide'])}"
        website = f"https://www.supplier{i+1}.com"
        vendor_manager = rng.choice(['J. Wong','K. Patel','S. Chen','L. Brown','D. Jones'])
        platform = rng.choice(platforms)
        api_integration = rng.choice(['Yes','No'])
        terms = rng.choice(payment_terms)
        freight = rng.choice(['Included','Excluded','Mixed'])
        abn = "".join(rng.choice(string.digits) for _ in range(11))
        country = rng.choice(countries)
        postcode = str(rng.randint(2000, 7999))
        source = rng.choice(sources)
        rows.append((
            name, account_id, sap_id, status, category, contact, address, website,
            vendor_manager, platform, api_integration, terms, freight, abn,
            country, postcode, source
        ))
    with conn:
        conn.executemany("""
            INSERT INTO suppliers
            (name, account_id, sap_id, status, product_category, contact, address, website,
             vendor_manager, platform, api_integration, payment_terms, freight_matrix, abn,
             country, postcode, source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)

# ---------------------- Settings Persistence ---------------------- #

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_settings(data: dict):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

# ---------------------- App ---------------------- #

class SupplierApp(Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1400x820")
        self.minsize(1100, 700)
        self.configure(bg=TOKYO["bg"])

        # State
        self.settings = load_settings()
        self.page = 1
        self.page_size = int(self.settings.get("page_size", DEFAULT_PAGE_SIZE))
        self.sort_by = self.settings.get("sort_by", "name")
        self.sort_dir = self.settings.get("sort_dir", "ASC")
        self.search_text = ""
        # Column visibility override from settings
        self.column_visibility = {c["id"]: self.settings.get("columns", {}).get(c["id"], c["visible"]) for c in COLUMNS}

        # Worker queues
        self.data_queue = queue.Queue()
        self.stats_queue = queue.Queue()
        self.loading = False

        # DB connection (one per app, threads use their own or safe usage)
        self.conn = get_conn()

        # UI
        self._setup_style()
        self._build_layout()
        self.bind_events()

        # Initial load
        self.refresh_stats_async()
        self.refresh_data_async()

    # ------------------ UI Setup ------------------ #
    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Base colors
        style.configure("TFrame", background=TOKYO["bg"])
        style.configure("Left.TFrame", background=TOKYO["bg_alt2"])
        style.configure("Toolbar.TFrame", background=TOKYO["bg_alt"])
        style.configure("TLabel", foreground=TOKYO["fg"], background=TOKYO["bg"])
        style.configure("Heading.TLabel", font=("Segoe UI Semibold", 12), foreground=TOKYO["fg"], background=TOKYO["bg_alt"])
        style.configure("Small.TLabel", font=("Segoe UI", 9), foreground=TOKYO["muted"], background=TOKYO["bg"])
        style.configure("Accent.TLabel", foreground=TOKYO["accent"], background=TOKYO["bg_alt2"], font=("Segoe UI Semibold", 11))

        style.configure("TButton", padding=8, relief="flat", background=TOKYO["bg_alt"], foreground=TOKYO["fg"])
        style.map("TButton", background=[("active", TOKYO["bg_alt2"])], relief=[("pressed", "sunken")])

        style.configure("Accent.TButton", background=TOKYO["accent"], foreground="#0b1021")
        style.map("Accent.TButton", background=[("active", "#8fb2ff")])

        style.configure("Danger.TButton", background=TOKYO["red"], foreground="#0b1021")
        style.map("Danger.TButton", background=[("active", "#ff9aa8")])

        style.configure("TEntry", fieldbackground=TOKYO["bg_alt"], foreground=TOKYO["fg"])
        style.configure("TCombobox", fieldbackground=TOKYO["bg_alt"], background=TOKYO["bg_alt"], foreground=TOKYO["fg"])
        style.configure("Horizontal.TSeparator", background=TOKYO["border"])

        # Treeview style
        style.configure("Modern.Treeview",
                        background=TOKYO["row_even"],
                        fieldbackground=TOKYO["bg_alt"],
                        foreground=TOKYO["fg"],
                        bordercolor=TOKYO["border"],
                        rowheight=26,
                        borderwidth=0)
        style.map("Modern.Treeview", background=[("selected", "#33467C")], foreground=[("selected", "#ffffff")])
        style.configure("Modern.Treeview.Heading",
                        background=TOKYO["bg_alt"],
                        foreground=TOKYO["fg"],
                        relief="flat",
                        bordercolor=TOKYO["border"])
        style.map("Modern.Treeview.Heading",
                  background=[("active", TOKYO["bg_alt2"])],
                  relief=[("pressed", "sunken")])

    def _build_layout(self):
        # Paned view: left dashboard, right content
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # Left Dashboard
        self.left_frame = ttk.Frame(self, style="Left.TFrame", padding=(12, 12))
        self.left_frame.grid(row=0, column=0, sticky=N+S)
        self.left_frame.rowconfigure(10, weight=1)

        ttk.Label(self.left_frame, text="Supplier Overview", style="Accent.TLabel").grid(row=0, column=0, sticky=W, pady=(0, 8))

        self.stat_total = self._stat_block(self.left_frame, "Total Suppliers", "-", TOKYO["accent"])
        self.stat_active = self._stat_block(self.left_frame, "Active", "-", TOKYO["green"])
        self.stat_inactive = self._stat_block(self.left_frame, "Inactive", "-", TOKYO["red"])
        self.stat_categories = self._stat_block(self.left_frame, "Categories", "-", TOKYO["magenta"])
        self.stat_platforms = self._stat_block(self.left_frame, "Platforms", "-", TOKYO["cyan"])

        self.stat_total.grid(row=1, column=0, sticky=E+W, pady=4)
        self.stat_active.grid(row=2, column=0, sticky=E+W, pady=4)
        self.stat_inactive.grid(row=3, column=0, sticky=E+W, pady=4)
        self.stat_categories.grid(row=4, column=0, sticky=E+W, pady=4)
        self.stat_platforms.grid(row=5, column=0, sticky=E+W, pady=4)

        # Right Content
        self.right_frame = ttk.Frame(self, padding=(0,0))
        self.right_frame.grid(row=0, column=1, sticky=N+S+E+W)
        self.right_frame.columnconfigure(0, weight=1)
        self.right_frame.rowconfigure(2, weight=1)

        # Toolbar
        self.toolbar = ttk.Frame(self.right_frame, style="Toolbar.TFrame", padding=(12, 10))
        self.toolbar.grid(row=0, column=0, sticky=E+W)
        self.toolbar.columnconfigure(5, weight=1)

        self.search_var = StringVar()
        self.search_entry = ttk.Entry(self.toolbar, textvariable=self.search_var, width=40)
        self.search_entry.insert(0, "")
        ttk.Label(self.toolbar, text="Search:", background=TOKYO["bg_alt"]).grid(row=0, column=0, sticky=W, padx=(0,6))
        self.search_entry.grid(row=0, column=1, sticky=W)
        self.search_entry.bind("<Return>", lambda e: self.on_search())

        self.btn_search = ttk.Button(self.toolbar, text="Go", command=self.on_search)
        self.btn_clear = ttk.Button(self.toolbar, text="Clear", command=self.on_clear_search)
        self.btn_search.grid(row=0, column=2, padx=(6, 0))
        self.btn_clear.grid(row=0, column=3, padx=(6, 0))

        self.btn_add = ttk.Button(self.toolbar, text="New Supplier", style="Accent.TButton", command=self.on_add)
        self.btn_add.grid(row=0, column=4, padx=(18, 0))

        # Spacer col=5 stretches
        self.btn_columns = ttk.Button(self.toolbar, text="Columns", command=self.on_columns)
        self.btn_export = ttk.Button(self.toolbar, text="Export CSV", command=self.on_export_csv)
        self.btn_columns.grid(row=0, column=6, padx=(0,6), sticky=E)
        self.btn_export.grid(row=0, column=7, sticky=E)

        # Separator
        ttk.Separator(self.right_frame, orient="horizontal").grid(row=1, column=0, sticky=E+W)

        # Table frame
        table_container = ttk.Frame(self.right_frame, padding=(12, 12))
        table_container.grid(row=2, column=0, sticky=N+S+E+W)
        table_container.columnconfigure(0, weight=1)
        table_container.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(table_container, style="Modern.Treeview", show="headings", selectmode="browse")
        self.hsb = ttk.Scrollbar(table_container, orient="horizontal", command=self.tree.xview)
        self.vsb = ttk.Scrollbar(table_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(xscrollcommand=self.hsb.set, yscrollcommand=self.vsb.set)
        self.tree.grid(row=0, column=0, sticky=N+S+E+W)
        self.vsb.grid(row=0, column=1, sticky=N+S)
        self.hsb.grid(row=1, column=0, sticky=E+W)

        # Context menu for table
        self.menu = tkinter_context_menu(self.tree, [
            ("Edit", self.on_edit_selected),
            ("Delete", self.on_delete_selected),
            ("Copy Cell", self.on_copy_cell),
        ])

        # Pagination bar
        self.pagination = ttk.Frame(self.right_frame, style="Toolbar.TFrame", padding=(12, 10))
        self.pagination.grid(row=3, column=0, sticky=E+W)
        self.pagination.columnconfigure(6, weight=1)

        ttk.Label(self.pagination, text="Page size:", background=TOKYO["bg_alt"]).grid(row=0, column=0, sticky=W)
        self.page_size_var = IntVar(value=self.page_size)
        self.page_size_cb = ttk.Combobox(self.pagination, values=PAGE_SIZES, textvariable=self.page_size_var, width=6, state="readonly")
        self.page_size_cb.grid(row=0, column=1, sticky=W, padx=(6, 12))
        self.page_size_cb.bind("<<ComboboxSelected>>", lambda e: self.on_change_page_size())

        self.btn_prev = ttk.Button(self.pagination, text="◀ Prev", command=self.on_prev_page)
        self.btn_next = ttk.Button(self.pagination, text="Next ▶", command=self.on_next_page)
        self.btn_prev.grid(row=0, column=2)
        self.btn_next.grid(row=0, column=3, padx=(6,0))

        self.page_info_var = StringVar(value="Page 1 of 1 (0 rows)")
        self.page_info = ttk.Label(self.pagination, textvariable=self.page_info_var, background=TOKYO["bg_alt"])
        self.page_info.grid(row=0, column=5, sticky=E)

        # Progress bar for background loads
        self.progress = ttk.Progressbar(self.pagination, mode="indeterminate", length=150)
        self.progress.grid(row=0, column=6, sticky=E)

        # Configure columns
        self._setup_columns()

    def _stat_block(self, parent, title, value, color):
        f = ttk.Frame(parent, style="Left.TFrame", padding=(10, 8))
        # border via inner frame to simulate card
        card = ttk.Frame(f, style="Left.TFrame", padding=(10, 8))
        card.pack(fill=X)
        t = ttk.Label(card, text=title, font=("Segoe UI", 10), background=TOKYO["bg_alt2"], foreground=TOKYO["muted"])
        v = ttk.Label(card, text=value, font=("Segoe UI Semibold", 16), foreground=color, background=TOKYO["bg_alt2"])
        t.pack(anchor=W)
        v.pack(anchor=W)
        # return references
        f.title_label = t
        f.value_label = v
        return f

    def _setup_columns(self):
        # Determine visible columns and configure tree
        self.tree_columns = [c["id"] for c in COLUMNS if self.column_visibility.get(c["id"], c["visible"])]
        self.tree["columns"] = self.tree_columns

        for c in COLUMNS:
            cid = c["id"]
            if cid in self.tree_columns:
                self.tree.column(cid, width=c["width"], anchor=c["anchor"], stretch=True)
                heading_text = c["text"]
                if cid == self.sort_by:
                    heading_text += " ▲" if self.sort_dir == "ASC" else " ▼"
                self.tree.heading(cid, text=heading_text, command=lambda col=cid: self.on_sort(col))

        # “Gridline” look via zebra striping tags
        self.tree.tag_configure("oddrow", background=TOKYO["row_odd"])
        self.tree.tag_configure("evenrow", background=TOKYO["row_even"])

    # ------------------ Events & Actions ------------------ #
    def bind_events(self):
        # self.tree.bind("<Double-1>", lambda e: self.on_edit_selected())
        self.tree.bind("<Double-1>", self.on_tree_double_click)
        self.tree.bind("<Button-3>", self.menu.show)  # right click
        self.bind("<Control-n>", lambda e: self.on_add())
        self.bind("<Control-f>", lambda e: self.search_entry.focus_set())
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Poll queues
        self.after(100, self._poll_queues)

    def on_close(self):
        # persist settings
        self.settings["page_size"] = self.page_size
        self.settings["sort_by"] = self.sort_by
        self.settings["sort_dir"] = self.sort_dir
        self.settings["columns"] = self.column_visibility
        save_settings(self.settings)
        try:
            self.conn.close()
        except Exception:
            pass
        self.destroy()

    def on_search(self):
        self.search_text = self.search_var.get().strip()
        self.page = 1
        self.refresh_data_async()

    def on_clear_search(self):
        self.search_var.set("")
        self.on_search()

    def on_add(self):
        SupplierDialog(self, self.conn, on_saved=self.on_dialog_saved)

    def on_edit_selected(self):
        item = self.tree.selection()
        if not item:
            return
        supplier_id = int(self.tree.item(item[0], "values")[self._col_index("id") if "id" in self.tree_columns else 0])
        SupplierDialog(self, self.conn, supplier_id=supplier_id, on_saved=self.on_dialog_saved)

    # Add to SupplierApp (class method)
    def on_tree_double_click(self, event):
        # Only trigger when double-clicking a cell, not headers/empty space
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        try:
            supplier_id = int(iid)  # iid is set to DB id when inserting
        except ValueError:
            return
        # Open edit dialog in a new window
        SupplierDialog(self, self.conn, supplier_id=supplier_id, on_saved=self.on_dialog_saved)


    def on_delete_selected(self):
        item = self.tree.selection()
        if not item:
            return
        # ID may be hidden; get via stored row id (we store 'iid' as str(id))
        iid = item[0]
        try:
            supplier_id = int(iid)
        except ValueError:
            # fallback to first col
            vals = self.tree.item(iid, "values")
            supplier_id = int(vals[self._col_index("id")]) if "id" in self.tree_columns else None
        if supplier_id is None:
            messagebox.showwarning("Delete", "Could not determine selected row ID.")
            return
        if messagebox.askyesno("Delete Supplier", "Are you sure you want to delete this supplier?"):
            with self.conn:
                self.conn.execute("DELETE FROM suppliers WHERE id=?", (supplier_id,))
            self.refresh_stats_async()
            self.refresh_data_async()

    def on_copy_cell(self):
        item = self.tree.selection()
        if not item:
            return
        # Determine clicked column from focus
        focus = self.tree.focus()
        if not focus:
            focus = item[0]
        values = self.tree.item(focus, "values")
        # default copy first visible col if not advanced hit-test
        text = str(values[0]) if values else ""
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            pass

    def on_columns(self):
        ColumnDialog(self, COLUMNS, self.column_visibility, on_apply=self.apply_column_visibility)

    def apply_column_visibility(self, vis_map):
        self.column_visibility = vis_map
        # Rebuild columns
        for col in self.tree.get_children():
            self.tree.delete(col)
        self._setup_columns()
        self.refresh_data_async()

    def on_export_csv(self):
        fname = filedialog.asksaveasfilename(
            title="Export CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not fname:
            return
        # Export current page with current visibility
        rows = self.current_rows if hasattr(self, "current_rows") else []
        visible_cols = [c for c in COLUMNS if self.column_visibility.get(c["id"], c["visible"])]
        try:
            with open(fname, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([c["text"] for c in visible_cols])
                for r in rows:
                    writer.writerow([r[c["id"]] for c in visible_cols])
            messagebox.showinfo("Export CSV", f"Exported {len(rows)} rows to:\n{fname}")
        except Exception as ex:
            messagebox.showerror("Export CSV", f"Failed to export:\n{ex}")

    def on_sort(self, col):
        if self.sort_by == col:
            self.sort_dir = "DESC" if self.sort_dir == "ASC" else "ASC"
        else:
            self.sort_by = col
            self.sort_dir = "ASC"
        # Update heading arrows
        for c in COLUMNS:
            cid = c["id"]
            if cid in self.tree_columns:
                heading_text = c["text"]
                if cid == self.sort_by:
                    heading_text += " ▲" if self.sort_dir == "ASC" else " ▼"
                self.tree.heading(cid, text=heading_text)
        self.page = 1
        self.refresh_data_async()

    def on_change_page_size(self):
        try:
            self.page_size = int(self.page_size_var.get())
        except ValueError:
            self.page_size = DEFAULT_PAGE_SIZE
        self.page = 1
        self.refresh_data_async()

    def on_prev_page(self):
        if self.page > 1:
            self.page -= 1
            self.refresh_data_async()

    def on_next_page(self):
        # guard by total_pages
        if hasattr(self, "total_pages") and self.page < self.total_pages:
            self.page += 1
            self.refresh_data_async()

    def on_dialog_saved(self, supplier_id):
        # Refresh stats & current page
        self.refresh_stats_async()
        self.refresh_data_async(select_id=supplier_id)

    # ------------------ Data Loading (Async) ------------------ #

    def refresh_data_async(self, select_id=None):
        if self.loading:
            return
        self.loading = True
        self.progress.start(8)
        t = threading.Thread(target=self._load_data_worker, args=(self.page, self.page_size, self.sort_by, self.sort_dir, self.search_text, select_id), daemon=True)
        t.start()

    def _load_data_worker(self, page, page_size, sort_by, sort_dir, search_text, select_id):
        try:
            # Separate connection for thread safety
            conn = get_conn()
            where = ""
            params = []
            if search_text:
                like = f"%{search_text}%"
                where = """WHERE (name LIKE ? OR account_id LIKE ? OR sap_id LIKE ? OR product_category LIKE ? OR status LIKE ?)"""
                params.extend([like, like, like, like, like])
            # Count
            sql_count = f"SELECT COUNT(*) AS cnt FROM suppliers {where}"
            cur = conn.execute(sql_count, params)
            total_rows = cur.fetchone()["cnt"]

            # Sorting (safe whitelist)
            valid_cols = {c["id"] for c in COLUMNS}
            if sort_by not in valid_cols:
                sort_by = "name"
            sort_expr = f"{sort_by} COLLATE NOCASE" if sort_by not in ("id",) else sort_by
            sort_dir = "ASC" if sort_dir.upper() not in ("ASC","DESC") else sort_dir.upper()

            # Pagination
            offset = (page - 1) * page_size
            sql = f"""
                SELECT {", ".join([c["id"] for c in COLUMNS])}
                FROM suppliers
                {where}
                ORDER BY {sort_expr} {sort_dir}
                LIMIT ? OFFSET ?
            """
            rows = conn.execute(sql, (*params, page_size, offset)).fetchall()
            # Convert to list of dicts
            data = [dict(row) for row in rows]

            # Compute total pages
            total_pages = max(1, (total_rows + page_size - 1) // page_size)
            self.data_queue.put({
                "data": data,
                "total_rows": total_rows,
                "total_pages": total_pages,
                "page": page,
                "select_id": select_id
            })
            conn.close()
        except Exception as ex:
            self.data_queue.put({"error": str(ex)})
        # no finally: UI thread stops spinner

    def refresh_stats_async(self):
        t = threading.Thread(target=self._load_stats_worker, daemon=True)
        t.start()

    def _load_stats_worker(self):
        try:
            conn = get_conn()
            total = conn.execute("SELECT COUNT(*) AS c FROM suppliers").fetchone()["c"]
            active = conn.execute("SELECT COUNT(*) AS c FROM suppliers WHERE status='Active'").fetchone()["c"]
            inactive = conn.execute("SELECT COUNT(*) AS c FROM suppliers WHERE status='Inactive'").fetchone()["c"]
            categories = conn.execute("SELECT COUNT(DISTINCT product_category) AS c FROM suppliers").fetchone()["c"]
            platforms = conn.execute("SELECT COUNT(DISTINCT platform) AS c FROM suppliers WHERE platform IS NOT NULL AND platform <> ''").fetchone()["c"]
            conn.close()
            self.stats_queue.put({
                "total": total,
                "active": active,
                "inactive": inactive,
                "categories": categories,
                "platforms": platforms
            })
        except Exception as ex:
            self.stats_queue.put({"error": str(ex)})

    def _poll_queues(self):
        # Data queue
        try:
            item = self.data_queue.get_nowait()
        except queue.Empty:
            item = None

        if item:
            self.progress.stop()
            self.loading = False
            if "error" in item:
                messagebox.showerror("Load Data", item["error"])
            else:
                self._update_table(item["data"])
                self.current_rows = item["data"]
                self.total_rows = item["total_rows"]
                self.total_pages = item["total_pages"]
                self.page = item["page"]
                self.page_info_var.set(f"Page {self.page} of {self.total_pages} ({self.total_rows} rows)")
                # Auto-select row if requested
                if item.get("select_id"):
                    iid = str(item["select_id"])
                    if iid in self.tree.get_children():
                        self.tree.selection_set(iid)
                        self.tree.see(iid)

        # Stats queue
        try:
            st = self.stats_queue.get_nowait()
        except queue.Empty:
            st = None
        if st:
            if "error" in st:
                # do nothing visually
                pass
            else:
                self.stat_total.value_label.config(text=str(st["total"]))
                self.stat_active.value_label.config(text=str(st["active"]))
                self.stat_inactive.value_label.config(text=str(st["inactive"]))
                self.stat_categories.value_label.config(text=str(st["categories"]))
                self.stat_platforms.value_label.config(text=str(st["platforms"]))

        self.after(120, self._poll_queues)

    def _update_table(self, rows):
        # Clear
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        # Insert
        for idx, r in enumerate(rows):
            row_vals = [r[cid] for cid in self.tree_columns]
            tag = "evenrow" if idx % 2 == 0 else "oddrow"
            iid = str(r["id"])  # stable iid = DB id
            self.tree.insert("", "end", iid=iid, values=row_vals, tags=(tag,))

    def _col_index(self, col_id):
        try:
            return self.tree_columns.index(col_id)
        except ValueError:
            return -1

# ---------------------- Dialogs ---------------------- #

class SupplierDialog(Toplevel):
    FIELDS = [c["id"] for c in COLUMNS if c["id"] != "id"]

    def __init__(self, parent: SupplierApp, conn, supplier_id=None, on_saved=None):
        super().__init__(parent)
        self.parent = parent
        self.conn = conn
        self.supplier_id = supplier_id
        self.on_saved = on_saved
        self.title("Edit Supplier" if supplier_id else "New Supplier")
        self.configure(bg=TOKYO["bg"])
        self.resizable(True, True)
        self.geometry("780x640")
        self.grab_set()

        self.vars = {f: StringVar() for f in self.FIELDS}

        self._build_form()
        if supplier_id:
            self._load_data(supplier_id)

    def _build_form(self):
        frm = ttk.Frame(self, padding=(16, 16))
        frm.pack(fill=BOTH, expand=True)
        # Grid config
        for i in range(4):
            frm.columnconfigure(i, weight=1)

        # Place fields in two columns
        labels = {
            "name": "Name*",
            "account_id": "Account ID",
            "sap_id": "Supplier SAP ID",
            "status": "Status",
            "product_category": "Product Category",
            "contact": "Contact",
            "address": "Address",
            "website": "Website",
            "vendor_manager": "Vendor Manager",
            "platform": "Platform",
            "api_integration": "API Integration (Yes/No)",
            "payment_terms": "Payment Terms",
            "freight_matrix": "Freight Matrix",
            "abn": "ABN",
            "country": "Country",
            "postcode": "Postcode",
            "source": "Source",
        }
        # Order providing a sensible layout
        order = [
            "name","status","account_id","sap_id",
            "product_category","platform","api_integration","payment_terms",
            "abn","country","postcode","source",
            "vendor_manager","contact","website","address","freight_matrix",
        ]
        r = 0
        for i, key in enumerate(order):
            c = 0 if i % 2 == 0 else 2
            if i % 2 == 0 and i > 0:
                r += 1
            ttk.Label(frm, text=labels.get(key, key)).grid(row=r, column=c, sticky=W, pady=(4,2), padx=(0,8))
            e = ttk.Entry(frm, textvariable=self.vars[key])
            e.grid(row=r, column=c+1, sticky=E+W, pady=(4,2))
        # Address as wider entry
        addr = frm.grid_slaves(row=r, column=3)[0] if frm.grid_slaves(row=r, column=3) else None
        if addr:
            addr.configure(width=50)

        # Buttons
        btns = ttk.Frame(frm, padding=(0, 12))
        btns.grid(row=r+2, column=0, columnspan=4, sticky=E+W, pady=(12,0))
        btns.columnconfigure(0, weight=1)
        if self.supplier_id:
            btn_delete = ttk.Button(btns, text="Delete", style="Danger.TButton", command=self._delete)
            btn_delete.grid(row=0, column=1, sticky=W)
        btn_cancel = ttk.Button(btns, text="Cancel", command=self.destroy)
        btn_save = ttk.Button(btns, text="Save", style="Accent.TButton", command=self._save)
        btn_cancel.grid(row=0, column=2, sticky=E, padx=(0, 6))
        btn_save.grid(row=0, column=3, sticky=E)

    def _load_data(self, supplier_id):
        row = self.conn.execute(f"SELECT {', '.join(['id'] + self.FIELDS)} FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
        if not row:
            messagebox.showerror("Edit Supplier", "Supplier not found.")
            self.destroy()
            return
        for k in self.FIELDS:
            self.vars[k].set(row[k] if row[k] is not None else "")

    def _save(self):
        data = {k: self.vars[k].get().strip() for k in self.FIELDS}
        if not data["name"]:
            messagebox.showwarning("Validation", "Name is required.")
            return
        cols = ", ".join(self.FIELDS)
        placeholders = ", ".join(["?"] * len(self.FIELDS))
        vals = [data[k] for k in self.FIELDS]
        with self.conn:
            if self.supplier_id:
                set_clause = ", ".join([f"{k}=?" for k in self.FIELDS])
                self.conn.execute(f"UPDATE suppliers SET {set_clause} WHERE id=?", (*vals, self.supplier_id))
                sid = self.supplier_id
            else:
                cur = self.conn.execute(f"INSERT INTO suppliers ({cols}) VALUES ({placeholders})", vals)
                sid = cur.lastrowid
        if self.on_saved:
            self.on_saved(sid)
        self.destroy()

    def _delete(self):
        if not self.supplier_id:
            return
        if messagebox.askyesno("Delete Supplier", "Are you sure you want to delete this supplier?"):
            with self.conn:
                self.conn.execute("DELETE FROM suppliers WHERE id=?", (self.supplier_id,))
            if self.on_saved:
                self.on_saved(None)
            self.destroy()

class ColumnDialog(Toplevel):
    def __init__(self, parent: SupplierApp, columns_config, vis_map: dict, on_apply=None):
        super().__init__(parent)
        self.title("Column Visibility")
        self.configure(bg=TOKYO["bg"])
        self.resizable(False, False)
        self.columns_config = columns_config
        self.vars = {}
        self.on_apply = on_apply

        frm = ttk.Frame(self, padding=(16,16))
        frm.pack(fill=BOTH, expand=True)

        ttk.Label(frm, text="Show/Hide Columns").pack(anchor=W, pady=(0,8))
        # Checkboxes in two columns
        list_frame = ttk.Frame(frm)
        list_frame.pack(fill=BOTH, expand=True)
        left = ttk.Frame(list_frame)
        right = ttk.Frame(list_frame)
        left.pack(side=LEFT, padx=(0,16))
        right.pack(side=RIGHT)

        half = (len(columns_config)+1)//2
        for idx, c in enumerate(columns_config):
            if c["id"] == "id":
                # keep in dialog too
                pass
            var = BooleanVar(value=vis_map.get(c["id"], c["visible"]))
            self.vars[c["id"]] = var
            target = left if idx < half else right
            ttk.Checkbutton(target, text=c["text"], variable=var).pack(anchor=W, pady=2)

        btns = ttk.Frame(frm)
        btns.pack(fill=X, pady=(10,0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side=RIGHT)
        ttk.Button(btns, text="Apply", style="Accent.TButton", command=self._apply).pack(side=RIGHT, padx=(0,6))

    def _apply(self):
        result = {k: v.get() for k, v in self.vars.items()}
        if self.on_apply:
            self.on_apply(result)
        self.destroy()

# ---------------------- Context Menu Helper ---------------------- #

# class tkinter_context_menu:
#     def __init__(self, widget, items):
#         self.widget = widget
#         self.menu = ttk.Menu(widget, tearoff=0)
#         for label, cmd in items:
#             self.menu.add_command(label=label, command=cmd)

#     def show(self, event):
#         try:
#             self.menu.tk_popup(event.x_root, event.y_root)
#         finally:
#             self.menu.grab_release()

# ---------------------- Context Menu Helper ---------------------- #

class tkinter_context_menu:
    def __init__(self, widget, items):
        self.widget = widget
        # Use tk.Menu (ttk doesn't have a Menu widget)
        self.menu = tk.Menu(widget, tearoff=0)

        # Optional: style-ish tweaks (limited options on tk.Menu)
        try:
            self.menu.configure(
                bg=TOKYO["bg_alt"], fg=TOKYO["fg"],
                activebackground=TOKYO["bg_alt2"], activeforeground="#ffffff",
                bd=0
            )
        except Exception:
            pass

        for label, cmd in items:
            self.menu.add_command(label=label, command=cmd)

        # Ensure right-click selects the row under the cursor (Windows/Linux)
        widget.bind("<Button-3>", self._popup, add="+")
        # macOS: Control-Click behaves like right-click
        widget.bind("<Control-Button-1>", self._popup, add="+")

    def _popup(self, event):
        # Select item under cursor before showing menu
        iid = self.widget.identify_row(event.y)
        if iid:
            self.widget.selection_set(iid)
            self.widget.focus(iid)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    # Keep original API in case you also call .show()
    def show(self, event):
        self._popup(event)


# ---------------------- Main ---------------------- #

def main():
    # Ensure DB exists; set seed_demo=True for initial test data
    ensure_db(seed_demo=True)  # ← set to False in production
    app = SupplierApp()
    app.mainloop()

if __name__ == "__main__":
    main()
