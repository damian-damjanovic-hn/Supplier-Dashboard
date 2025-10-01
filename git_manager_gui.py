import os
import sys
import shlex
import queue
import shutil
import threading
import subprocess
import platform
import datetime as dt
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap import Style
from ttkbootstrap.constants import *
from tkinter import filedialog, messagebox

# ---------------------------
# Utilities
# ---------------------------

def is_windows():
    return platform.system().lower().startswith("win")

def safe_run(args, cwd=None):
    """
    Run a git command and return (stdout, stderr, returncode).
    Args must be a list. No shell=True for safety.
    """
    try:
        proc = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True
        )
        return proc.stdout, proc.stderr, proc.returncode
    except Exception as e:
        return "", str(e), 1

def parse_status_porcelain(text):
    """
    Parse 'git status --porcelain' output to list of dicts:
    [{'path': 'file', 'status': 'Modified', 'index': 'M', 'worktree': ' '}, ...]
    """
    items = []
    for line in text.splitlines():
        if not line.strip():
            continue
        x = line[:2]
        rest = line[3:]
        index_flag = x[0]
        wt_flag = x[1]
        if line.startswith("??"):
            items.append({"path": line[3:].strip(), "status": "Untracked", "index": "?", "worktree": "?"})
            continue

        # Handle rename format: 'R  src -> dst'
        if "->" in rest:
            try:
                _, dst = rest.split("->", 1)
                path = dst.strip()
                status = "Renamed"
            except Exception:
                path = rest.strip()
                status = "Renamed"
        else:
            path = rest.strip()
            mapping = {
                "M": "Modified",
                "A": "Added",
                "D": "Deleted",
                "R": "Renamed",
                "C": "Copied",
                "U": "Unmerged",
                " ": " "
            }
            status = "Changed"
            if index_flag != " ":
                status = mapping.get(index_flag, index_flag)
            elif wt_flag != " ":
                status = mapping.get(wt_flag, wt_flag)

        items.append({"path": path, "status": status, "index": index_flag, "worktree": wt_flag})
    return items

def parse_ahead_behind(short_status_line):
    # Example: "## main...origin/main [ahead 2, behind 1]"
    ahead = behind = 0
    if "[" in short_status_line and "]" in short_status_line:
        bracket = short_status_line[short_status_line.index("[")+1 : short_status_line.index("]")]
        parts = [p.strip() for p in bracket.split(",")]
        for p in parts:
            if p.startswith("ahead"):
                try:
                    ahead = int(p.split()[1])
                except Exception:
                    pass
            if p.startswith("behind"):
                try:
                    behind = int(p.split()[1])
                except Exception:
                    pass
    return ahead, behind

def timestamp():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ---------------------------
# Main App
# ---------------------------

class GitManagerApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master.title("Git Manager Pro")
        self.master.geometry("1120x720")
        self.master.minsize(980, 640)

        # State
        self.repo_path = tk.StringVar(value="")
        self.user_name = tk.StringVar(value="")
        self.user_email = tk.StringVar(value="")
        self.commit_msg = tk.StringVar(value="")
        self.reset_depth = tk.IntVar(value=1)
        self.stage_all = tk.BooleanVar(value=True)
        self.current_branch = tk.StringVar(value="")
        self.selected_branch = tk.StringVar(value="")
        self.new_branch_name = tk.StringVar(value="")
        self.rename_branch_to = tk.StringVar(value="")
        self.commits_to_show = tk.IntVar(value=50)
        self.stash_message = tk.StringVar(value="")
        self.stash_include_untracked = tk.BooleanVar(value=True)

        # Async queue
        self.result_queue = queue.Queue()
        self.running_task = False

        # Build UI
        self._build_topbar()
        self._build_body()
        self._build_statusbar()

        self._bind_shortcuts()
        self._load_global_config()

    # ---------------------------
    # UI Construction
    # ---------------------------

    def _build_topbar(self):
        top = ttk.Frame(self.master)
        top.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(8, 4))

        ttk.Label(top, text="Repository:", bootstyle="info").grid(row=0, column=0, sticky="w")
        self.repo_entry = ttk.Entry(top, textvariable=self.repo_path, width=80)
        self.repo_entry.grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(top, text="Browse…", command=self.choose_repo, bootstyle="secondary-outline").grid(row=0, column=2, padx=4)

        # Progress bar (thin)
        self.progress = ttk.Progressbar(top, mode="indeterminate", bootstyle="striped")
        self.progress.grid(row=1, column=0, columnspan=3, sticky="we", pady=(8,0))

        top.grid_columnconfigure(1, weight=1)

    def _build_body(self):
        paned = ttk.Panedwindow(self.master, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # Left: tabbed controls
        left = ttk.Frame(paned, padding=(6,6))
        paned.add(left, weight=1)

        # Right: content tabs
        right = ttk.Frame(paned)
        paned.add(right, weight=3)

        # ----- Left Tabs -----
        self.left_tabs = ttk.Notebook(left, bootstyle="secondary")
        self.left_tabs.pack(fill=tk.BOTH, expand=True)

        # Repo tab
        self.tab_repo = ttk.Frame(self.left_tabs, padding=8)
        self.left_tabs.add(self.tab_repo, text="Repository")
        self._build_tab_repository(self.tab_repo)

        # Branches tab
        self.tab_branch = ttk.Frame(self.left_tabs, padding=8)
        self.left_tabs.add(self.tab_branch, text="Branches")
        self._build_tab_branches(self.tab_branch)

        # Commit tab
        self.tab_commit = ttk.Frame(self.left_tabs, padding=8)
        self.left_tabs.add(self.tab_commit, text="Commit")
        self._build_tab_commit(self.tab_commit)

        # Reset tab
        self.tab_reset = ttk.Frame(self.left_tabs, padding=8)
        self.left_tabs.add(self.tab_reset, text="Reset")
        self._build_tab_reset(self.tab_reset)

        # Stash tab
        self.tab_stash = ttk.Frame(self.left_tabs, padding=8)
        self.left_tabs.add(self.tab_stash, text="Stash")
        self._build_tab_stash(self.tab_stash)

        # Settings tab
        self.tab_settings = ttk.Frame(self.left_tabs, padding=8)
        self.left_tabs.add(self.tab_settings, text="Settings")
        self._build_tab_settings(self.tab_settings)

        # ----- Right: Content Tabs -----
        self.tabs = ttk.Notebook(right, bootstyle="dark")
        self.tabs.pack(fill=tk.BOTH, expand=True)

        # Changes tab
        self.changes_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.changes_tab, text="Changes")

        cols = ("status", "path")
        self.tree = ttk.Treeview(self.changes_tab, columns=cols, show="headings", height=18, bootstyle="dark")
        self.tree.heading("status", text="Status")
        self.tree.heading("path", text="Path")
        self.tree.column("status", width=110, anchor="w")
        self.tree.column("path", width=720, anchor="w")
        self.tree.grid(row=0, column=0, columnspan=4, sticky="nsew")

        ttk.Button(self.changes_tab, text="Stage Selected", command=self.stage_selected, bootstyle="primary").grid(row=1, column=0, sticky="w", pady=(8,0))
        ttk.Button(self.changes_tab, text="Unstage Selected", command=self.unstage_selected, bootstyle="warning").grid(row=1, column=1, sticky="w", padx=6, pady=(8,0))
        ttk.Button(self.changes_tab, text="Discard Selected", command=self.discard_selected, bootstyle="danger-outline").grid(row=1, column=2, sticky="w", padx=6, pady=(8,0))
        ttk.Button(self.changes_tab, text="Refresh", command=self.refresh_all, bootstyle="secondary-outline").grid(row=1, column=3, sticky="e", pady=(8,0))

        self.changes_tab.grid_rowconfigure(0, weight=1)
        self.changes_tab.grid_columnconfigure(0, weight=1)
        self.changes_tab.grid_columnconfigure(1, weight=0)
        self.changes_tab.grid_columnconfigure(2, weight=0)
        self.changes_tab.grid_columnconfigure(3, weight=0)

        # Commits tab
        self.log_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.log_tab, text="Commits")

        topbar = ttk.Frame(self.log_tab)
        topbar.pack(fill=tk.X)
        ttk.Label(topbar, text="Show last").pack(side=tk.LEFT)
        ttk.Spinbox(topbar, from_=10, to=500, textvariable=self.commits_to_show, width=5).pack(side=tk.LEFT, padx=6)
        ttk.Button(topbar, text="Refresh Log", command=self.load_log, bootstyle="secondary-outline").pack(side=tk.LEFT)
        ttk.Button(topbar, text="Revert Selected SHA", command=self.revert_selected_sha, bootstyle="danger-outline").pack(side=tk.LEFT, padx=8)

        self.log_list = ttk.Treeview(self.log_tab, columns=("sha", "msg"), show="headings", height=16, bootstyle="dark")
        self.log_list.heading("sha", text="SHA")
        self.log_list.heading("msg", text="Message")
        self.log_list.column("sha", width=100, anchor="w")
        self.log_list.column("msg", width=760, anchor="w")
        self.log_list.pack(fill=tk.BOTH, expand=True, pady=(8,0))
        ttk.Button(self.log_tab, text="Copy Selected SHA", command=self.copy_selected_sha, bootstyle="secondary").pack(side=tk.RIGHT, pady=6)

        # Console tab
        self.console_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.console_tab, text="Console")

        toolbar = ttk.Frame(self.console_tab)
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="Copy All", command=self.copy_console, bootstyle="secondary").pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Clear", command=self.clear_console, bootstyle="secondary").pack(side=tk.LEFT, padx=6)
        ttk.Button(toolbar, text="Export Log…", command=self.export_console, bootstyle="info").pack(side=tk.LEFT, padx=6)

        self.console = tk.Text(self.console_tab, height=20, wrap="word", bg="#101214", fg="#D0FFD0")
        self.console.pack(fill=tk.BOTH, expand=True, pady=(6,0))

    def _build_statusbar(self):
        status = ttk.Frame(self.master)
        status.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=6)
        self.status_left = ttk.Label(status, text="Ready", anchor="w")
        self.status_left.pack(side=tk.LEFT)
        self.status_right = ttk.Label(status, text="", anchor="e")
        self.status_right.pack(side=tk.RIGHT)

    # ----- Left tab builders -----

    def _build_tab_repository(self, parent):
        r = parent
        row = 0
        ttk.Button(r, text="Open Folder", command=self.open_folder, bootstyle="secondary").grid(row=row, column=0, columnspan=2, sticky="we"); row += 1
        ttk.Button(r, text="Open Terminal", command=self.open_terminal, bootstyle="secondary").grid(row=row, column=0, columnspan=2, sticky="we", pady=(6,0)); row += 1

        ttk.Separator(r).grid(row=row, column=0, columnspan=2, sticky="we", pady=8); row += 1

        ttk.Button(r, text="Init Repo in Folder…", command=self.init_repo, bootstyle="secondary-outline").grid(row=row, column=0, columnspan=2, sticky="we"); row += 1

        ttk.Label(r, text="Clone URL").grid(row=row, column=0, sticky="w", pady=(8,0))
        self.clone_url = tk.StringVar()
        ttk.Entry(r, textvariable=self.clone_url, width=28).grid(row=row, column=1, sticky="we", padx=6, pady=(8,0)); row += 1
        ttk.Button(r, text="Clone to Folder…", command=self.clone_repo, bootstyle="secondary-outline").grid(row=row, column=0, columnspan=2, sticky="we", pady=(6,0)); row += 1

        r.grid_columnconfigure(1, weight=1)

    def _build_tab_branches(self, parent):
        b = parent
        row = 0
        ttk.Label(b, text="Current/Select Branch").grid(row=row, column=0, sticky="w"); row += 1
        self.branch_combo = ttk.Combobox(b, textvariable=self.selected_branch, width=28, state="readonly")
        self.branch_combo.grid(row=row, column=0, columnspan=2, sticky="we"); row += 1

        btns = ttk.Frame(b)
        btns.grid(row=row, column=0, columnspan=2, sticky="we", pady=(6,0)); row += 1
        ttk.Button(btns, text="Checkout", command=self.checkout_selected, bootstyle="primary").pack(side=tk.LEFT)
        ttk.Button(btns, text="Fetch", command=self.fetch, bootstyle="warning").pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="Pull", command=self.pull, bootstyle="success").pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="Push", command=self.push, bootstyle="danger").pack(side=tk.LEFT, padx=6)

        ttk.Separator(b).grid(row=row, column=0, columnspan=2, sticky="we", pady=8); row += 1

        ttk.Label(b, text="New branch").grid(row=row, column=0, sticky="w")
        ttk.Entry(b, textvariable=self.new_branch_name, width=18).grid(row=row, column=1, sticky="we", padx=6); row += 1
        ttk.Button(b, text="Create & Checkout", command=self.create_branch, bootstyle="primary").grid(row=row, column=0, columnspan=2, sticky="we", pady=(6,0)); row += 1

        ttk.Label(b, text="Rename current to").grid(row=row, column=0, sticky="w", pady=(8,0))
        ttk.Entry(b, textvariable=self.rename_branch_to, width=18).grid(row=row, column=1, sticky="we", padx=6, pady=(8,0)); row += 1
        ttk.Button(b, text="Rename", command=self.rename_branch, bootstyle="warning").grid(row=row, column=0, columnspan=2, sticky="we"); row += 1

        ttk.Button(b, text="Delete selected", command=self.delete_selected_branch, bootstyle="danger-outline").grid(row=row, column=0, columnspan=2, sticky="we", pady=(6,0)); row += 1

        b.grid_columnconfigure(1, weight=1)

    def _build_tab_commit(self, parent):
        c = parent
        row = 0
        ttk.Label(c, text="Message").grid(row=row, column=0, sticky="w")
        ttk.Entry(c, textvariable=self.commit_msg, width=28).grid(row=row, column=1, sticky="we", padx=6); row += 1

        ttk.Checkbutton(c, text="Stage all (incl. untracked)", variable=self.stage_all).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6,0)); row += 1

        ttk.Button(c, text="Commit  (Ctrl+Enter)", command=self.commit_changes, bootstyle="success").grid(row=row, column=0, columnspan=2, sticky="we", pady=(8,0)); row += 1
        ttk.Button(c, text="Amend (no edit)", command=self.amend_commit, bootstyle="warning-outline").grid(row=row, column=0, sticky="we", pady=(6,0))
        ttk.Button(c, text="Amend (edit message)", command=self.change_commit_msg, bootstyle="warning-outline").grid(row=row, column=1, sticky="we", pady=(6,0))

        c.grid_columnconfigure(1, weight=1)

    def _build_tab_reset(self, parent):
        r = parent
        row = 0
        ttk.Label(r, text="Depth (N)").grid(row=row, column=0, sticky="w")
        ttk.Spinbox(r, from_=1, to=50, textvariable=self.reset_depth, width=6).grid(row=row, column=1, sticky="w", padx=6); row += 1

        ttk.Button(r, text="Soft Reset HEAD~N", command=self.soft_reset, bootstyle="secondary-outline").grid(row=row, column=0, columnspan=2, sticky="we", pady=(6,0)); row += 1
        ttk.Button(r, text="Hard Reset HEAD~N", command=self.hard_reset, bootstyle="danger-outline").grid(row=row, column=0, columnspan=2, sticky="we", pady=(6,0)); row += 1
        ttk.Button(r, text="Reset to origin/<branch>", command=self.reset_to_remote, bootstyle="danger").grid(row=row, column=0, columnspan=2, sticky="we", pady=(6,0)); row += 1

        r.grid_columnconfigure(1, weight=1)

    def _build_tab_stash(self, parent):
        s = parent
        row = 0
        ttk.Label(s, text="Message (optional)").grid(row=row, column=0, sticky="w")
        ttk.Entry(s, textvariable=self.stash_message, width=28).grid(row=row, column=1, sticky="we", padx=6); row += 1

        ttk.Checkbutton(s, text="Include untracked (-u)", variable=self.stash_include_untracked).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6,0)); row += 1

        ttk.Button(s, text="Stash Save", command=self.stash_save, bootstyle="secondary-outline").grid(row=row, column=0, sticky="we"); 
        ttk.Button(s, text="Stash Pop", command=self.stash_pop, bootstyle="secondary-outline").grid(row=row, column=1, sticky="we", padx=6); row += 1
        ttk.Button(s, text="List in Console", command=self.stash_list, bootstyle="secondary-outline").grid(row=row, column=0, columnspan=2, sticky="we", pady=(6,0)); row += 1

        s.grid_columnconfigure(1, weight=1)

    def _build_tab_settings(self, parent):
        g = parent
        row = 0
        ttk.Label(g, text="User Name").grid(row=row, column=0, sticky="w")
        ttk.Entry(g, textvariable=self.user_name, width=28).grid(row=row, column=1, sticky="we", padx=6); row += 1
        ttk.Label(g, text="User Email").grid(row=row, column=0, sticky="w", pady=(6,0))
        ttk.Entry(g, textvariable=self.user_email, width=28).grid(row=row, column=1, sticky="we", padx=6, pady=(6,0)); row += 1
        ttk.Button(g, text="Set Global Config", command=self.set_config, bootstyle="secondary").grid(row=row, column=0, columnspan=2, pady=(10,0), sticky="we")

        g.grid_columnconfigure(1, weight=1)

    def _bind_shortcuts(self):
        self.master.bind("<Control-Return>", lambda e: self.commit_changes())

    # ---------------------------
    # Repo Utilities
    # ---------------------------

    def choose_repo(self):
        path = filedialog.askdirectory()
        if path:
            self.repo_path.set(path)
            self.refresh_all()

    def open_folder(self):
        path = self.repo_path.get().strip()
        if not path:
            messagebox.showinfo("Open Folder", "Select a repository folder first.")
            return
        if is_windows():
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def open_terminal(self):
        path = self.repo_path.get().strip()
        if not path:
            messagebox.showinfo("Open Terminal", "Select a repository folder first.")
            return
        try:
            if is_windows():
                cmd = ["wt.exe", "-d", path] if shutil.which("wt.exe") else ["cmd.exe", "/K", f"cd /d {path}"]
                subprocess.Popen(cmd)
            elif sys.platform == "darwin":
                script = f'tell application "Terminal" to do script "cd {shlex.quote(path)}"'
                subprocess.Popen(["osascript", "-e", script])
            else:
                term = shutil.which("gnome-terminal") or shutil.which("konsole") or shutil.which("xterm")
                if term and "gnome-terminal" in term:
                    subprocess.Popen([term, "--", "bash", "-lc", f"cd {shlex.quote(path)}; exec bash"])
                elif term and "konsole" in term:
                    subprocess.Popen([term, "--workdir", path])
                elif term and "xterm" in term:
                    subprocess.Popen([term, "-e", f"bash -lc 'cd {shlex.quote(path)}; exec bash'"])
                else:
                    messagebox.showinfo("Open Terminal", "No supported terminal found; opening folder instead.")
                    subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Open Terminal", str(e))

    # ---------------------------
    # Async Command Runners
    # ---------------------------

    def run_git_async(self, args, cwd=None, label=None, refresh=False):
        """Run a single git command asynchronously."""
        self.run_git_chain([args], cwd=cwd, label=label, refresh=refresh)

    def run_git_chain(self, commands, cwd=None, label=None, refresh=False):
        """
        Run a sequence of git commands asynchronously as one task.
        `commands` is a list of arg lists: [["git","add","-A"], ["git","commit","-m","msg"]]
        """
        if not cwd:
            cwd = self.repo_path.get().strip() or None
        if cwd and not os.path.isdir(cwd):
            self._log(f"[{timestamp()}] ERROR: Invalid repository path: {cwd}\n", is_err=True)
            return
        if self.running_task:
            self._log("Another operation is still running. Please wait…\n")
            return

        self.running_task = True
        self.progress.start(8)
        if label:
            self._set_status(label)

        def worker():
            full_log = ""
            final_rc = 0
            for args in commands:
                out, err, rc = safe_run(args, cwd=cwd)
                cmd_str = " ".join(shlex.quote(a) for a in args)
                full_log += f"\n$ {cmd_str}\n"
                if out:
                    full_log += out
                if err:
                    full_log += err
                final_rc = rc
                if rc != 0:
                    break
            self.result_queue.put((full_log, final_rc, refresh))

        threading.Thread(target=worker, daemon=True).start()
        self.master.after(60, self._poll_results)

    def _poll_results(self):
        try:
            full_log, rc, refresh = self.result_queue.get_nowait()
            self.progress.stop()
            self.running_task = False
            self._log(full_log, is_err=(rc != 0))
            self._set_status(f"Done ({'OK' if rc == 0 else 'Error'})")
            if refresh:
                self.refresh_all()
        except queue.Empty:
            self.master.after(60, self._poll_results)

    def _log(self, text, is_err=False):
        self.console.insert(tk.END, text)
        self.console.see(tk.END)

    def _set_status(self, text):
        self.status_left.configure(text=text)

    # ---------------------------
    # Actions
    # ---------------------------

    def _load_global_config(self):
        out, _, rc = safe_run(["git", "config", "--global", "user.name"])
        if rc == 0 and out.strip():
            self.user_name.set(out.strip())
        out, _, rc = safe_run(["git", "config", "--global", "user.email"])
        if rc == 0 and out.strip():
            self.user_email.set(out.strip())

    def set_config(self):
        name = self.user_name.get().strip()
        email = self.user_email.get().strip()
        if not name or not email:
            messagebox.showwarning("Config", "User name and email are required.")
            return
        self.run_git_chain(
            [
                ["git", "config", "--global", "user.name", name],
                ["git", "config", "--global", "user.email", email],
            ],
            label="Setting global user config"
        )

    def init_repo(self):
        path = filedialog.askdirectory(title="Select folder to initialize as Git repo")
        if not path:
            return
        self.repo_path.set(path)
        self.run_git_async(["git", "init"], cwd=path, label="Initializing repository", refresh=True)

    def clone_repo(self):
        url = self.clone_url.get().strip()
        if not url:
            messagebox.showwarning("Clone", "Please enter a clone URL.")
            return
        dest = filedialog.askdirectory(title="Select destination folder for clone")
        if not dest:
            return
        self.run_git_async(["git", "clone", url], cwd=dest, label="Cloning repository", refresh=True)

    def commit_changes(self):
        if not self._repo_selected():
            return
        msg = self.commit_msg.get().strip()
        if not msg:
            messagebox.showwarning("Commit", "Please enter a commit message.")
            return
        chain = []
        if self.stage_all.get():
            chain.append(["git", "add", "-A"])
        chain.append(["git", "commit", "-m", msg])
        self.run_git_chain(chain, label="Committing changes", refresh=True)

    def amend_commit(self):
        if not self._repo_selected():
            return
        self.run_git_async(["git", "commit", "--amend", "--no-edit"], label="Amending commit", refresh=True)

    def change_commit_msg(self):
        if not self._repo_selected():
            return
        self.run_git_async(["git", "commit", "--amend"], label="Amending (edit message)", refresh=True)

    def soft_reset(self):
        if not self._repo_selected():
            return
        n = self.reset_depth.get()
        if n < 1:
            messagebox.showwarning("Reset", "Depth must be >= 1.")
            return
        self.run_git_async(["git", "reset", f"HEAD~{n}"], label=f"Soft reset HEAD~{n}", refresh=True)

    def hard_reset(self):
        if not self._repo_selected():
            return
        n = self.reset_depth.get()
        if not messagebox.askyesno("Hard Reset", f"This will discard changes.\nProceed with hard reset to HEAD~{n}?"):
            return
        self.run_git_async(["git", "reset", f"HEAD~{n}", "--hard"], label=f"Hard reset HEAD~{n}", refresh=True)

    def reset_to_remote(self):
        if not self._repo_selected():
            return
        br = (self.selected_branch.get() or self.current_branch.get()).strip()
        if not br:
            messagebox.showwarning("Reset to Remote", "No branch selected.")
            return
        if not messagebox.askyesno("Reset to Remote", f"This will set your working tree to origin/{br}.\nAll local changes will be lost. Continue?"):
            return
        self.run_git_chain(
            [
                ["git", "fetch", "origin"],
                ["git", "reset", "--hard", f"origin/{br}"],
            ],
            label=f"Reset to origin/{br}",
            refresh=True
        )

    def pull(self):
        if not self._repo_selected():
            return
        self.run_git_async(["git", "pull"], label="Pulling", refresh=True)

    def fetch(self):
        if not self._repo_selected():
            return
        self.run_git_async(["git", "fetch", "--all", "--prune"], label="Fetching", refresh=True)

    def push(self):
        if not self._repo_selected():
            return
        self.run_git_async(["git", "push"], label="Pushing", refresh=True)

    def create_branch(self):
        if not self._repo_selected():
            return
        name = self.new_branch_name.get().strip()
        if not name:
            messagebox.showwarning("Branch", "Enter a new branch name.")
            return
        self.run_git_async(["git", "checkout", "-b", name], label=f"Create & checkout {name}", refresh=True)

    def rename_branch(self):
        if not self._repo_selected():
            return
        newname = self.rename_branch_to.get().strip()
        if not newname:
            messagebox.showwarning("Rename Branch", "Enter new branch name.")
            return
        self.run_git_async(["git", "branch", "-m", newname], label=f"Renaming branch → {newname}", refresh=True)

    def delete_selected_branch(self):
        if not self._repo_selected():
            return
        br = self.selected_branch.get().strip()
        if not br:
            messagebox.showwarning("Delete Branch", "Select a branch to delete.")
            return
        if br == self.current_branch.get().strip():
            messagebox.showwarning("Delete Branch", "Cannot delete the current branch.")
            return
        if not messagebox.askyesno("Delete Branch", f"Delete branch '{br}'? (Unmerged work may be lost)"):
            return
        self.run_git_async(["git", "branch", "-D", br], label=f"Deleting {br}", refresh=True)

    def checkout_selected(self):
        if not self._repo_selected():
            return
        br = self.selected_branch.get().strip()
        if not br:
            messagebox.showwarning("Checkout", "Select a branch to checkout.")
            return
        self.run_git_async(["git", "checkout", br], label=f"Checking out {br}", refresh=True)

    def stash_save(self):
        if not self._repo_selected():
            return
        msg = self.stash_message.get().strip()
        cmd = ["git", "stash", "push"]
        if msg:
            cmd += ["-m", msg]
        if self.stash_include_untracked.get():
            cmd += ["-u"]
        self.run_git_async(cmd, label="Stash save", refresh=True)

    def stash_pop(self):
        if not self._repo_selected():
            return
        self.run_git_async(["git", "stash", "pop"], label="Stash pop", refresh=True)

    def stash_list(self):
        if not self._repo_selected():
            return
        self.run_git_async(["git", "stash", "list"], label="Stash list", refresh=False)

    def stage_selected(self):
        if not self._repo_selected():
            return
        items = self.tree.selection()
        if not items:
            messagebox.showinfo("Stage", "Select one or more files in the Changes list.")
            return
        paths = [self.tree.set(i, "path") for i in items]
        self.run_git_async(["git", "add"] + paths, label=f"Staging {len(paths)} file(s)", refresh=True)

    def unstage_selected(self):
        if not self._repo_selected():
            return
        items = self.tree.selection()
        if not items:
            messagebox.showinfo("Unstage", "Select one or more files in the Changes list.")
            return
        paths = [self.tree.set(i, "path") for i in items]
        self.run_git_async(["git", "restore", "--staged"] + paths, label=f"Unstaging {len(paths)} file(s)", refresh=True)

    def discard_selected(self):
        if not self._repo_selected():
            return
        items = self.tree.selection()
        if not items:
            messagebox.showinfo("Discard", "Select one or more files in the Changes list.")
            return
        paths = [self.tree.set(i, "path") for i in items]
        if not messagebox.askyesno("Discard Changes", f"This will discard local changes in {len(paths)} file(s).\nThis cannot be undone. Continue?"):
            return
        # Use modern restore to reset working tree files
        self.run_git_async(["git", "restore", "--worktree", "--source=HEAD", "--"] + paths, label=f"Discarding {len(paths)} file(s)", refresh=True)

    def load_log(self):
        if not self._repo_selected():
            return
        n = self.commits_to_show.get()
        out, err, rc = safe_run(["git", "log", f"--pretty=%h|%s", f"-{n}"], cwd=self.repo_path.get())
        # Update treeview
        for i in self.log_list.get_children():
            self.log_list.delete(i)
        if rc == 0 and out:
            for line in out.splitlines():
                if "|" in line:
                    sha, msg = line.split("|", 1)
                    self.log_list.insert("", tk.END, values=(sha.strip(), msg.strip()))
        elif err:
            self._log(err + "\n", is_err=True)

    def copy_selected_sha(self):
        sel = self.log_list.selection()
        if not sel:
            return
        sha = self.log_list.set(sel[0], "sha")
        self.master.clipboard_clear()
        self.master.clipboard_append(sha)
        self._set_status(f"Copied SHA: {sha}")

    def revert_selected_sha(self):
        if not self._repo_selected():
            return
        sel = self.log_list.selection()
        if not sel:
            messagebox.showinfo("Revert", "Select a commit SHA in the Commits tab.")
            return
        sha = self.log_list.set(sel[0], "sha")
        if not messagebox.askyesno("Revert Commit", f"Create a new commit that reverts {sha}?"):
            return
        self.run_git_async(["git", "revert", sha], label=f"Reverting {sha}", refresh=True)

    # Console helpers
    def copy_console(self):
        text = self.console.get("1.0", tk.END)
        self.master.clipboard_clear()
        self.master.clipboard_append(text)
        self._set_status("Console copied")

    def clear_console(self):
        self.console.delete("1.0", tk.END)

    def export_console(self):
        fname = filedialog.asksaveasfilename(
            title="Export Console Log",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not fname:
            return
        with open(fname, "w", encoding="utf-8") as f:
            f.write(self.console.get("1.0", tk.END))
        self._set_status(f"Exported log to {os.path.basename(fname)}")

    # ---------------------------
    # Refresh / Status
    # ---------------------------

    def refresh_all(self):
        path = self.repo_path.get().strip()
        if not path or not os.path.isdir(path):
            return

        # Current branch & ahead/behind
        out, err, rc = safe_run(["git", "status", "-sb"], cwd=path)
        if rc == 0 and out:
            first = out.splitlines()[0].strip()
            self.current_branch.set(first.replace("## ", "").split("...")[0])
            ahead, behind = parse_ahead_behind(first)
            self.status_right.configure(text=f"Branch: {self.current_branch.get()} | ↑ {ahead} ↓ {behind}")
        else:
            self.current_branch.set("")
            self.status_right.configure(text="")

        # Branch list
        out, _, rc = safe_run(["git", "branch", "--list"], cwd=path)
        branches = []
        if rc == 0 and out:
            for line in out.splitlines():
                name = line.replace("*", "").strip()
                if name:
                    branches.append(name)
        self.branch_combo["values"] = branches
        # Keep selection coherent
        if self.current_branch.get() and self.current_branch.get() in branches:
            self.branch_combo.set(self.current_branch.get())
            self.selected_branch.set(self.current_branch.get())
        elif branches:
            self.branch_combo.set(branches[0])
            self.selected_branch.set(branches[0])

        # Changes list
        out, _, rc = safe_run(["git", "status", "--porcelain"], cwd=path)
        for i in self.tree.get_children():
            self.tree.delete(i)
        if rc == 0 and out:
            for item in parse_status_porcelain(out):
                self.tree.insert("", tk.END, values=(item["status"], item["path"]))

        # Log
        self.load_log()

    def _repo_selected(self):
        path = self.repo_path.get().strip()
        if not path:
            messagebox.showinfo("Repository", "Select or initialize a repository first.")
            return False
        if not os.path.isdir(path):
            messagebox.showerror("Repository", "Selected path is not a directory.")
            return False
        git_dir = os.path.join(path, ".git")
        if not os.path.isdir(git_dir):
            messagebox.showwarning("Repository", "This folder does not look like a Git repository (missing .git).")
            return False
        return True

# ---------------------------
# Entry Point
# ---------------------------

def main():
    style = Style("darkly")  # keeps your dark theme preference
    app = GitManagerApp(style.master)
    app.pack(fill=tk.BOTH, expand=True)
    style.master.mainloop()

if __name__ == "__main__":
    main()
