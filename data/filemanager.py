#!/usr/bin/env python3
# data/filemanager.py
# Explorateur sandboxé pour Dobrian
#
# - Ouvre les fichiers .dbn via data/code.py (si présent) en fenêtres internes sur le même Canvas.
# - Fenêtre interne (ou Toplevel) avec arbre, aperçu et éditeur texte.
# - Auth pour dossier system via auth.AuthWindow (optionnel).
# - Icônes depuis file.dobrian/system/assets/
#
# Usage:
#   from filemanager import FileManagerWindow
#   FileManagerWindow(parent_canvas=canvas, x=100, y=100, width=760, height=480, internal=True, username="user", register_callback=cb)
#
# register_callback (optionnel) : callable(win_dict) pour enregistrer la fenêtre dans le Task Panel du App.

import os
import shutil
import json
import hashlib
import time
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox

# Pillow optionnel
try:
    from PIL import Image, ImageTk
    PIL = True
except Exception:
    PIL = False

# --- chemins et sandbox ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))   # data/
SANDBOX_ROOT = os.path.join(BASE_DIR, "file.dobrian")
SYSTEM_DIR = os.path.join(SANDBOX_ROOT, "system")
ASSETS_DIR = os.path.join(SYSTEM_DIR, "assets")
FILE_SYS = os.path.join(SYSTEM_DIR, "file.sys")
ACCOUNTS_FILE = os.path.join(BASE_DIR, "dobrian_accounts.json")  # data/dobrian_accounts.json

# Ensure sandbox and defaults exist
def _ensure_sandbox():
    os.makedirs(SANDBOX_ROOT, exist_ok=True)
    for d in ("home", "system"):
        os.makedirs(os.path.join(SANDBOX_ROOT, d), exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    # default file.sys if missing
    if not os.path.exists(FILE_SYS):
        try:
            with open(FILE_SYS, "w", encoding="utf-8") as f:
                f.write("# Format: ext = editor|preview|editor,preview ;\n")
                f.write("txt = editor;\n")
                f.write("png = preview;\n")
                f.write("svg = editor, preview;\n")
        except Exception:
            pass

_ensure_sandbox()

# --- style constants (light theme) ---
DEFAULT_BG = "white"        # main background
DEFAULT_FG = "black"        # primary text color
TOOLBAR_BG = "#f5f5f5"      # toolbar background
TITLEBAR_BG = "#2f2f2f"     # titlebar / header
BTN_BG = "#f5f5f5"          # button background
BTN_ACTIVE_BG = "#ddd"      # button active background
PREVIEW_BG = "#f0f0f0"      # preview pane background
EDITOR_BG = "white"         # editor background
EDITOR_FG = "black"         # editor foreground


# --- helpers sandbox / accounts ---
def _is_within_sandbox(path):
    try:
        rp = os.path.realpath(path)
        root = os.path.realpath(SANDBOX_ROOT)
        return os.path.commonpath([rp, root]) == root
    except Exception:
        return False


def _hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

def _verify_credentials(username: str, password: str) -> bool:
    if not os.path.exists(ACCOUNTS_FILE):
        return False
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            accounts = json.load(f)
        return username in accounts and accounts[username] == _hash_password(password)
    except Exception:
        return False

# --- load file.sys rules ---
def load_file_sys_rules():
    rules = {}
    if not os.path.exists(FILE_SYS):
        return rules
    try:
        with open(FILE_SYS, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.endswith(";"):
                    line = line[:-1].strip()
                if "=" not in line:
                    continue
                left, right = line.split("=", 1)
                ext = left.strip().lower()
                parts = [p.strip().lower() for p in right.replace(",", " ").split() if p.strip()]
                allowed = set()
                for p in parts:
                    if p in ("editor", "preview"):
                        allowed.add(p)
                if ext:
                    rules[ext] = allowed
    except Exception:
        pass
    return rules

# --- image loader for icons and previews ---
def _load_image(path, maxsize=None):
    if not os.path.exists(path):
        return None
    try:
        if PIL:
            img = Image.open(path).convert("RGBA")
            if maxsize:
                img.thumbnail(maxsize, Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        else:
            return tk.PhotoImage(file=path)
    except Exception:
        return None

# --- import auth window (optional) ---
try:
    from auth import AuthWindow
except Exception:
    AuthWindow = None

# --- import code runner for .dbn apps (optional) ---
try:
    import code as code_module   # data/code.py
except Exception:
    code_module = None

# --- external editor (notepad) ---
try:
    # use relative import when inside package
    from . import notpad
except Exception:
    notpad = None

# --- FileManagerWindow class ---
class FileManagerWindow:
    """
    FileManagerWindow(parent_canvas=..., parent_toplevel=..., x=80, y=80, width=760, height=480,
                      internal=True, username='user', title='File Manager', register_callback=None)
    register_callback: optional callable(win_dict) used to register created internal windows in App.
    """

    def __init__(self,
                 parent_canvas=None,
                 parent_toplevel=None,
                 x=80, y=80,
                 width=760, height=480,
                 internal=True,
                 username="user",
                 title="File Manager",
                 register_callback=None):
        self.internal = internal
        self.username = username
        self._editing_path = None
        self._preview_image_ref = None
        self._info_icon_ref = None
        self._icons = {}
        self._rules = load_file_sys_rules()
        self._system_unlocked = False  # per-instance unlock flag
        self._dir_cache = {}          # cache for directory listings to speed navigation
        self.register_callback = register_callback

        # initialize ttk style for consistent theming
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        # treeview styling
        self.style.configure("Treeview",
                             background=DEFAULT_BG,
                             foreground=DEFAULT_FG,
                             fieldbackground=DEFAULT_BG,
                             font=("Segoe UI", 10),
                             rowheight=22)

        self.style.map("Treeview", background=[("selected", "#c0c0c0")])
        self.style.configure("Treeview.Heading",
                             background=TITLEBAR_BG,
                             foreground=DEFAULT_FG,
                             relief="flat")


        # load icons from assets
        self._load_icons()

        # create UI container (internal or toplevel)
        if internal:
            if parent_canvas is None:
                raise ValueError("parent_canvas required for internal=True")
            self.canvas = parent_canvas
            self.frame = tk.Frame(self.canvas, bd=2, relief="raised", bg=DEFAULT_BG)
            self.frame.pack_propagate(False)
            self.window_id = self.canvas.create_window(x, y, window=self.frame, anchor="nw", width=width, height=height)
            # titlebar
            self.titlebar = tk.Frame(self.frame, bg=TITLEBAR_BG, height=28)
            self.titlebar.pack(fill="x", side="top")
            tk.Label(self.titlebar, text=title, fg=DEFAULT_FG, bg=TITLEBAR_BG).pack(side="left", padx=6)
            tk.Button(self.titlebar, text="✕", bg=TITLEBAR_BG, fg=DEFAULT_FG, bd=0,
                      activebackground=BTN_ACTIVE_BG, command=self.close).pack(side="right", padx=4)
            # content
            self.content = tk.Frame(self.frame, bg=DEFAULT_BG)
            self.content.pack(fill="both", expand=True)
            # drag support
            self._drag = {"start_x":0, "start_y":0, "orig_x":x, "orig_y":y, "w":width, "h":height}
            self.titlebar.bind("<ButtonPress-1>", self._on_press)
            self.titlebar.bind("<B1-Motion>", self._on_motion)
        else:
            if parent_toplevel is None:
                raise ValueError("parent_toplevel required for internal=False")
            self.win = tk.Toplevel(parent_toplevel)
            self.win.title(title)
            self.content = tk.Frame(self.win, bg=DEFAULT_BG)
            self.content.pack(fill="both", expand=True)

        # build UI and populate
        self._build_ui()
        self.view_mode = "tree"
        self._refresh()

        try:
            self.content.after_idle(lambda: self.tree.focus_set())
        except Exception:
            pass

    # --- icons loader ---
    def _load_icons(self):
        """
        Charge les icônes depuis ASSETS_DIR. On s'attend à trouver :
        new_folder.png, new_file.png, import.png, delete.png, rename.png, edit.png, save.png
        ainsi que des icônes pour dossiers/fichiers (folder.png, home.png, hdd.png, default.png, txt.png, etc.)
        """
        default_map = {
            "hdd": "hdd.png",
            "home": "home.png",
            "assets": "settings.png",
            "folder": "folder.png",
            "default": "default.png",
            "txt": "txt.png",
            # toolbar icons (keys used in _build_ui)
            "new_folder": "new_folder.png",
            "new_file": "new_file.png",
            "import": "import.png",
            "delete": "delete.png",
            "rename": "rename.png",
            "edit": "edit.png",
            "save": "save.png",
            "refresh": "refresh.png"
        }
        os.makedirs(ASSETS_DIR, exist_ok=True)
        # load the default_map first (ensures toolbar icons are available under known keys)
        for key, fname in default_map.items():
            path = os.path.join(ASSETS_DIR, fname)
            img = _load_image(path, maxsize=(20,20))
            if img:
                self._icons[key] = img
        # load any additional pngs in assets as extension icons (e.g., png, svg, etc.)
        try:
            for fname in os.listdir(ASSETS_DIR):
                if not fname.lower().endswith(".png"):
                    continue
                name = os.path.splitext(fname)[0].lower()
                if name in self._icons:
                    continue
                path = os.path.join(ASSETS_DIR, fname)
                img = _load_image(path, maxsize=(18,18))
                if img:
                    self._icons[name] = img
        except Exception:
            pass

    # --- drag handlers for internal window ---
    def _on_press(self, event):
        try:
            cx = self.canvas.canvasx(event.x_root - self.canvas.winfo_rootx())
            cy = self.canvas.canvasy(event.y_root - self.canvas.winfo_rooty())
            coords = self.canvas.coords(self.window_id)
            self._drag["start_x"] = cx
            self._drag["start_y"] = cy
            self._drag["orig_x"] = coords[0]
            self._drag["orig_y"] = coords[1]
        except Exception:
            pass

    def _on_motion(self, event):
        try:
            cx = self.canvas.canvasx(event.x_root - self.canvas.winfo_rootx())
            cy = self.canvas.canvasy(event.y_root - self.canvas.winfo_rooty())
            dx = cx - self._drag["start_x"]
            dy = cy - self._drag["start_y"]
            new_x = int(self._drag["orig_x"] + dx)
            new_y = int(self._drag["orig_y"] + dy)
            pw = int(self.canvas.winfo_width() or self.canvas.winfo_reqwidth())
            ph = int(self.canvas.winfo_height() or self.canvas.winfo_reqheight())
            w = self._drag["w"]
            h = self._drag["h"]
            new_x = max(0, min(new_x, pw - w))
            new_y = max(0, min(new_y, ph - h - 60))
            self.canvas.coords(self.window_id, new_x, new_y)
            self.canvas.update_idletasks()
        except Exception:
            pass

    # --- UI build ---
    def _build_ui(self):
        toolbar = tk.Frame(self.content, bg=TOOLBAR_BG)
        toolbar.pack(fill="x", padx=6, pady=(6,4))

        def _icon_btn(parent, icon_key, cmd, side="left", padx=4, tooltip=None):
            """
            Crée un bouton n'affichant que l'icône (si disponible).
            Si l'icône est absente, affiche un petit bouton texte en fallback.
            """
            img = self._icons.get(icon_key)
            if img:
                b = tk.Button(parent, image=img, command=cmd, bg=BTN_BG, bd=0,
                              activebackground=BTN_ACTIVE_BG, fg=DEFAULT_FG)
                b.image = img
                # give a consistent size/padding
                b.config(width=36, height=28)
            else:
                # fallback: small text button
                label = icon_key.replace("_", " ").title()
                b = tk.Button(parent, text=label, command=cmd, bg=BTN_BG,
                              activebackground=BTN_ACTIVE_BG, fg=DEFAULT_FG)
            b.pack(side=side, padx=padx)
            # optional tooltip (simple hover using bind)
            if tooltip:
                def on_enter(e):
                    x = e.x_root + 10
                    y = e.y_root + 10
                    self._show_tooltip(tooltip, x, y)
                def on_leave(e):
                    self._hide_tooltip()
                b.bind("<Enter>", on_enter)
                b.bind("<Leave>", on_leave)
            return b

        # Replace text buttons by icon-only buttons (icons loaded from ASSETS_DIR)
        _icon_btn(toolbar, "new_folder", self.create_folder)
        _icon_btn(toolbar, "new_file", self.create_file)
        _icon_btn(toolbar, "import", self.import_file)
        _icon_btn(toolbar, "delete", self.delete_selected)
        _icon_btn(toolbar, "rename", self.rename_selected)
        _icon_btn(toolbar, "edit", self.edit_selected)

        # View toggle buttons (tree/list/details)
        tk.Button(toolbar, text="Tree", command=lambda: self._set_view("tree"), bg=BTN_BG,
                  activebackground=BTN_ACTIVE_BG, fg=DEFAULT_FG).pack(side="left", padx=4)
        tk.Button(toolbar, text="List", command=lambda: self._set_view("list"), bg=BTN_BG,
                  activebackground=BTN_ACTIVE_BG, fg=DEFAULT_FG).pack(side="left", padx=4)
        tk.Button(toolbar, text="Details", command=lambda: self._set_view("details"), bg=BTN_BG,
                  activebackground=BTN_ACTIVE_BG, fg=DEFAULT_FG).pack(side="left", padx=4)

        # Save button (icon-only if available)
        img_save = self._icons.get("save")
        if img_save:
            self.save_btn = tk.Button(toolbar, image=img_save, command=self.save_editor, state="disabled", bg=BTN_BG, bd=0,
                                         activebackground=BTN_ACTIVE_BG, fg=DEFAULT_FG)
            self.save_btn.image = img_save
            self.save_btn.config(width=36, height=28)
        else:
            self.save_btn = tk.Button(toolbar, text="Save", command=self.save_editor, state="disabled", bg=BTN_BG,
                                         activebackground=BTN_ACTIVE_BG, fg=DEFAULT_FG)
        self.save_btn.pack(side="left", padx=8)

        # Refresh on the right (icon-only)
        img_refresh = self._icons.get("refresh")
        if img_refresh:
            b_refresh = tk.Button(toolbar, image=img_refresh, command=self._refresh, bg=BTN_BG, bd=0,
                                     activebackground=BTN_ACTIVE_BG, fg=DEFAULT_FG)
            b_refresh.image = img_refresh
            b_refresh.config(width=36, height=28)
        else:
            b_refresh = tk.Button(toolbar, text="Rafraîchir", command=self._refresh, bg=BTN_BG,
                                     activebackground=BTN_ACTIVE_BG, fg=DEFAULT_FG)
        b_refresh.pack(side="right", padx=4)

        # tooltip container (hidden by default)
        self._tooltip = None
        self._tooltip_win = None

        main = tk.PanedWindow(self.content, orient="horizontal")

        main.pack(fill="both", expand=True, padx=6, pady=6)

        # Treeview
        tree_frame = tk.Frame(main, bg=DEFAULT_BG)
        # store reference to tree_frame for view switching
        self.tree_frame = tree_frame
        self.tree = ttk.Treeview(tree_frame, show="tree")
        # alternating row colors
        self.tree.tag_configure("odd", background=DEFAULT_BG)
        self.tree.tag_configure("even", background=TOOLBAR_BG)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        main.add(tree_frame, width=260)

        # Right pane: info + preview/editor (same area)
        right = tk.Frame(main, bg=DEFAULT_BG)
        self.info_label = tk.Label(right, text="Sélectionnez un fichier ou dossier", anchor="w", bg=DEFAULT_BG, fg=DEFAULT_FG, compound="left")
        self.info_label.pack(fill="x", padx=6, pady=(0,4))

        # preview frame (top)
        self.preview_frame = tk.Frame(right, bg=PREVIEW_BG, height=180)
        self.preview_frame.pack(fill="x", padx=6, pady=(0,6))
        self.preview_frame.pack_propagate(False)
        self.preview_label = tk.Label(self.preview_frame, bg=PREVIEW_BG)
        self.preview_label.pack(expand=True)

        # editor (bottom / full)
        self.editor = tk.Text(right, bg=EDITOR_BG, fg=EDITOR_FG, insertbackground=DEFAULT_FG)
        self.editor.pack(fill="both", expand=True, padx=6, pady=4)

        editor_buttons = tk.Frame(right, bg=DEFAULT_BG)
        editor_buttons.pack(fill="x", padx=6, pady=(0,6))
        tk.Button(editor_buttons, text="Annuler", command=self.clear_editor).pack(side="left", padx=4)

        main.add(right)

    # --- simple tooltip helpers (very small, best-effort) ---
    def _show_tooltip(self, text, x, y):
        try:
            self._hide_tooltip()
            self._tooltip_win = tk.Toplevel(self.content)
            self._tooltip_win.overrideredirect(True)
            self._tooltip_win.attributes("-topmost", True)
            lbl = tk.Label(self._tooltip_win, text=text, bg=TITLEBAR_BG, fg=DEFAULT_FG, padx=6, pady=2, font=("Segoe UI", 9))
            lbl.pack()
            self._tooltip_win.geometry(f"+{x}+{y}")
        except Exception:
            self._hide_tooltip()

    def _hide_tooltip(self):
        try:
            if self._tooltip_win:
                self._tooltip_win.destroy()
        except Exception:
            pass
        self._tooltip_win = None

    # --- view management (tree / list / details) ---
    def _set_view(self, mode):
        """Switch between view modes."""
        if mode == getattr(self, 'view_mode', None):
            return
        self.view_mode = mode
        # clear left pane
        for child in self.tree_frame.winfo_children():
            child.destroy()

        if mode == "tree":
            self._setup_treeview()
        elif mode == "list":
            self._setup_listview()
            self._populate_list()
        elif mode == "details":
            self._setup_detailsview()
            self._populate_details()

    def _setup_treeview(self):
        # rebuild the original treeview in tree_frame
        self.tree = ttk.Treeview(self.tree_frame, show="tree")
        self.tree.tag_configure("odd", background=DEFAULT_BG)
        self.tree.tag_configure("even", background=TOOLBAR_BG)
        vsb = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        # reload tree contents
        self._load_tree()

    def _setup_listview(self):
        self.listbox = tk.Listbox(self.tree_frame)
        vsb = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=vsb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)

    def _setup_detailsview(self):
        self.details = ttk.Treeview(self.tree_frame, columns=("size","modified"), show="headings")
        self.details.heading("size", text="Size")
        self.details.heading("modified", text="Modified")
        self.details.column("size", width=80, anchor="e")
        self.details.column("modified", width=120, anchor="center")
        vsb = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.details.yview)
        self.details.configure(yscrollcommand=vsb.set)
        self.details.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.details.bind("<<TreeviewSelect>>", self._on_details_select)

    def _populate_list(self):
        self.listbox.delete(0, "end")
        for root, dirs, files in os.walk(SANDBOX_ROOT):
            for name in dirs + files:
                rel = os.path.relpath(os.path.join(root, name), SANDBOX_ROOT)
                self.listbox.insert("end", rel)

    def _populate_details(self):
        for item in self.details.get_children():
            self.details.delete(item)
        for root, dirs, files in os.walk(SANDBOX_ROOT):
            for name in dirs + files:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, SANDBOX_ROOT)
                try:
                    size = os.path.getsize(full) if os.path.isfile(full) else ""
                    mtime = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(full)))
                except Exception:
                    size = ""
                    mtime = ""
                self.details.insert("", "end", values=(rel, size, mtime))

    def _on_list_select(self, event):
        sel = event.widget.curselection()
        if not sel:
            return
        val = event.widget.get(sel[0])
        path = os.path.join(SANDBOX_ROOT, val)
        if os.path.exists(path) and not os.path.isdir(path):
            if self._is_path_in_system(path) and not self._system_unlocked:
                self._require_system_auth(on_success=lambda: self._handle_file(path))
            else:
                self._handle_file(path)

    def _on_details_select(self, event):
        sel = event.widget.selection()
        if not sel:
            return
        val = event.widget.item(sel[0], "values")[0]
        path = os.path.join(SANDBOX_ROOT, val)
        if os.path.exists(path) and not os.path.isdir(path):
            if self._is_path_in_system(path) and not self._system_unlocked:
                self._require_system_auth(on_success=lambda: self._handle_file(path))
            else:
                self._handle_file(path)

    # --- tree population with icons and special folder icons ---
    def _load_tree(self):
        # reset row counter for alternating colors
        self._row_count = 0
        for i in self.tree.get_children():
            self.tree.delete(i)

        def insert_node(parent, path):
            try:
                # use cached listing
                dirs, files = self._list_dir(path)

                # insert directories first
                for name in dirs:
                    full = os.path.join(path, name)
                    base = os.path.basename(full).lower()
                    if os.path.realpath(full) == os.path.realpath(SANDBOX_ROOT):
                        img = self._icons.get("hdd") or self._icons.get("folder") or self._icons.get("default")
                    elif base == "home":
                        img = self._icons.get("home") or self._icons.get("folder") or self._icons.get("default")
                    elif base == "assets":
                        img = self._icons.get("assets") or self._icons.get("settings") or self._icons.get("folder") or self._icons.get("default")
                    else:
                        img = self._icons.get("folder") or self._icons.get("default")
                    tag = "even" if (self._row_count % 2) == 0 else "odd"
                    node = self.tree.insert(parent, "end", text=name, values=(full,), image=img, tags=(tag,))
                    self._row_count += 1
                    if img:
                        try:
                            self.tree.item(node, image=img)
                        except Exception:
                            pass
                    # add dummy so folder is expandable
                    self.tree.insert(node, "end", text="__dummy__")

                # then insert files
                for name in files:
                    full = os.path.join(path, name)
                    name_l = name.lower()
                    ext = os.path.splitext(name_l)[1].lstrip(".")
                    img = None
                    if ext:
                        img = self._icons.get(ext)
                    if not img and name_l.endswith(".txt"):
                        img = self._icons.get("txt")
                    if not img:
                        img = self._icons.get("default")
                    tag = "even" if (self._row_count % 2) == 0 else "odd"
                    node = self.tree.insert(parent, "end", text=name, values=(full,), image=img, tags=(tag,))
                    self._row_count += 1
                    if img:
                        try:
                            self.tree.item(node, image=img)
                        except Exception:
                            pass
            except PermissionError:
                pass

        root_icon = self._icons.get("hdd") or self._icons.get("folder") or self._icons.get("default")
        root_id = self.tree.insert("", "end", text=os.path.basename(SANDBOX_ROOT), open=True, values=(SANDBOX_ROOT,), image=root_icon)
        insert_node(root_id, SANDBOX_ROOT)
        self.tree.bind("<<TreeviewOpen>>", self._on_open)

    def _refresh(self):
        """Clear internal cache and rebuild tree/list/detail views."""
        try:
            self._dir_cache.clear()
        except Exception:
            pass
        self._load_tree()
        if self.view_mode == "list":
            self._populate_list()
        elif self.view_mode == "details":
            self._populate_details()

    def _open_in_notepad(self, path):
        """Launch external NotepadWindow to edit given file."""
        if notpad is None:
            messagebox.showerror("Erreur", "Module notpad introuvable.")
            return
        try:
            # compute coordinates relative to this window
            x, y = 160, 140
            w, h = 640, 360
            try:
                if self.internal:
                    coords = self.canvas.coords(self.window_id)
                    if coords and len(coords) >= 2:
                        x = int(coords[0] + 40)
                        y = int(coords[1] + 40)
            except Exception:
                pass
            win = notpad.NotepadWindow(parent_canvas=self.canvas if self.internal else None,
                                       parent_toplevel=(None if self.internal else getattr(self, "win", None)),
                                       x=x, y=y, width=w, height=h, internal=self.internal,
                                       path=path)
            if isinstance(win, dict) and callable(self.register_callback):
                try:
                    self.register_callback(win)
                except Exception:
                    pass
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir l'éditeur: {e}")

    def _handle_file(self, path):
        """Shared logic for handling a file path (update info, run .dbn or preview/edit)."""
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lstrip(".").lower()
        icon = self._icons.get(ext) or (self._icons.get("txt") if name.lower().endswith(".txt") else None) or self._icons.get("default")
        self._info_icon_ref = icon
        self.info_label.config(image=icon, text=f"  Fichier: {os.path.relpath(path, SANDBOX_ROOT)}")

        if ext == "dbn":
            if code_module is None:
                messagebox.showerror("Erreur", "Impossible d'exécuter l'application : module code.py introuvable dans data/.")
                return
            try:
                # compute placement relative to this FileManager window (if internal)
                x, y = 160, 140
                w, h = 640, 360
                try:
                    if self.internal:
                        coords = self.canvas.coords(self.window_id)
                        if coords and len(coords) >= 2:
                            x = int(coords[0] + 40)
                            y = int(coords[1] + 40)
                except Exception:
                    pass

                # call renderer; prefer render_dbn, fallback to run_dbn
                win_info = None
                if hasattr(code_module, "render_dbn"):
                    win_info = code_module.render_dbn(parent_canvas=self.canvas, x=x, y=y, width=w, height=h, path=path, register_callback=self.register_callback)
                elif hasattr(code_module, "run_dbn"):
                    win_info = code_module.run_dbn(parent_canvas=self.canvas, x=x, y=y, width=w, height=h, path=path, register_callback=self.register_callback)
                else:
                    messagebox.showerror("Erreur", "code.py ne propose pas de fonction render_dbn ou run_dbn.")
                    return

                if isinstance(win_info, dict) and callable(self.register_callback):
                    try:
                        self.register_callback(win_info)
                    except Exception:
                        pass
                return
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible d'exécuter {name} : {e}")
                return

        allowed = self._rules.get(ext)
        if allowed is None:
            self._show_editor_text("[Type non pris en charge par file.sys]", editable=False)
            self._hide_preview()
            return

        if "editor" in allowed:
            self._open_in_notepad(path)
            return

        if "preview" in allowed:
            if path.lower().endswith(".png") and os.path.exists(path):
                self._show_image_preview(path)
            else:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = f.read()
                    self._show_editor_text(data, editable=False)
                except Exception:
                    self._show_editor_text("[Aperçu non disponible]", editable=False)
            self._hide_editor_area()
            return

        # otherwise nothing

    def _on_open(self, event):
        item = self.tree.focus()
        if not item:
            return
        path = self._item_path(item)
        # If expanding a folder under system, require auth first (asynchronous)
        if self._is_path_in_system(path) and not self._system_unlocked:
            # request auth and, on success, re-open this node
            self._require_system_auth(on_success=lambda: self._expand_node_after_auth(item))
            # collapse for now
            try:
                self.tree.item(item, open=False)
            except Exception:
                pass
            return

        children = self.tree.get_children(item)
        if len(children) == 1 and self.tree.item(children[0], "text") == "__dummy__":
            self.tree.delete(children[0])
            try:
                dirs, files = self._list_dir(path)

                # insert directories first
                for name in dirs:
                    full = os.path.join(path, name)
                    base = os.path.basename(full).lower()
                    if os.path.realpath(full) == os.path.realpath(SANDBOX_ROOT):
                        img = self._icons.get("hdd") or self._icons.get("folder") or self._icons.get("default")
                    elif base == "home":
                        img = self._icons.get("home") or self._icons.get("folder") or self._icons.get("default")
                    elif base == "assets":
                        img = self._icons.get("assets") or self._icons.get("settings") or self._icons.get("folder") or self._icons.get("default")
                    else:
                        img = self._icons.get("folder") or self._icons.get("default")
                    tag = "even" if (self._row_count % 2) == 0 else "odd"
                    node = self.tree.insert(item, "end", text=name, values=(full,), image=img, tags=(tag,))
                    self._row_count += 1
                    if img:
                        try:
                            self.tree.item(node, image=img)
                        except Exception:
                            pass
                    self.tree.insert(node, "end", text="__dummy__")

                # then insert files
                for name in files:
                    full = os.path.join(path, name)
                    ext = os.path.splitext(name)[1].lstrip(".").lower()
                    img = self._icons.get(ext) or self._icons.get("txt") or self._icons.get("default")
                    tag = "even" if (self._row_count % 2) == 0 else "odd"
                    node = self.tree.insert(item, "end", text=name, values=(full,), image=img, tags=(tag,))
                    self._row_count += 1
                    if img:
                        try:
                            self.tree.item(node, image=img)
                        except Exception:
                            pass
            except Exception:
                pass

    def _expand_node_after_auth(self, item):
        try:
            # re-open node now that auth succeeded
            self.tree.item(item, open=True)
            # trigger open handler to populate
            self._on_open(None)
        except Exception:
            pass

    def _item_path(self, item):
        vals = self.tree.item(item, "values")
        if vals:
            return vals[0]
        parts = []
        cur = item
        while cur:
            parts.append(self.tree.item(cur, "text"))
            cur = self.tree.parent(cur)
        parts.reverse()
        rel = os.path.join(*parts[1:]) if len(parts) > 1 else ""
        return os.path.join(SANDBOX_ROOT, rel)

    def _is_path_in_system(self, path):
        try:
            return os.path.commonpath([os.path.realpath(path), os.path.realpath(SYSTEM_DIR)]) == os.path.realpath(SYSTEM_DIR)
        except Exception:
            return False

    def _list_dir(self, path):
        """Cached directory listing: returns (dirs, files)"""
        if path in self._dir_cache:
            return self._dir_cache[path]
        try:
            entries = sorted(os.listdir(path))
            dirs = [n for n in entries if os.path.isdir(os.path.join(path, n))]
            files = [n for n in entries if not os.path.isdir(os.path.join(path, n))]
            self._dir_cache[path] = (dirs, files)
            return dirs, files
        except Exception:
            return [], []

    # --- authentication flow using auth.AuthWindow (asynchronous) ---
    def _require_system_auth(self, on_success=None):
        """
        Opens the internal AuthWindow (from data/auth.py) and verifies credentials.
        If successful, sets self._system_unlocked = True and calls on_success() if provided.
        Returns immediately (asynchronous).
        """
        if AuthWindow is None:
            messagebox.showerror("Erreur", "Module auth introuvable.")
            return False

        def _cb(result):
            if not result:
                return
            username, password = result
            if _verify_credentials(username, password):
                self._system_unlocked = True
                if callable(on_success):
                    try:
                        on_success()
                    except Exception:
                        pass
            else:
                messagebox.showerror("Échec d'authentification", "Identifiants incorrects.")

        # compute a centered position relative to this internal window (if available)
        x, y = 200, 160
        try:
            if self.internal:
                coords = self.canvas.coords(self.window_id)
                x = int(coords[0] + 40)
                y = int(coords[1] + 40)
        except Exception:
            pass

        # create internal auth window; callback will handle result
        try:
            AuthWindow(parent_canvas=self.canvas if self.internal else None,
                       parent_toplevel=(None if self.internal else getattr(self, "win", None)),
                       x=x, y=y, width=360, height=200, internal=self.internal,
                       callback=_cb, default_username=self.username)
        except Exception:
            # fallback: synchronous simple dialog
            creds = self._fallback_cred_dialog()
            if creds:
                u, p = creds
                if _verify_credentials(u, p):
                    self._system_unlocked = True
                    messagebox.showinfo("Accès autorisé", "Accès au dossier system autorisé pour cette session.")
                    if callable(on_success):
                        try:
                            on_success()
                        except Exception:
                            pass
                else:
                    messagebox.showerror("Échec d'authentification", "Identifiants incorrects.")
        return False

    def _fallback_cred_dialog(self):
        # simple blocking dialog if auth.AuthWindow not usable
        dlg = tk.Toplevel(self.content if not self.internal else self.canvas)
        dlg.title("Authentification")
        dlg.transient(self.content if not self.internal else self.canvas)
        frm = tk.Frame(dlg, padx=12, pady=12)
        frm.pack(fill="both", expand=True)
        tk.Label(frm, text="Nom d'utilisateur").pack(anchor="w")
        uvar = tk.StringVar(value=self.username)
        tk.Entry(frm, textvariable=uvar).pack(fill="x", pady=(0,8))
        tk.Label(frm, text="Mot de passe").pack(anchor="w")
        pvar = tk.StringVar()
        tk.Entry(frm, textvariable=pvar, show="*").pack(fill="x", pady=(0,8))
        res = {"val": None}
        def ok():
            res["val"] = (uvar.get().strip(), pvar.get())
            dlg.destroy()
        def cancel():
            dlg.destroy()
        btns = tk.Frame(frm)
        btns.pack(fill="x", pady=(6,0))
        tk.Button(btns, text="Annuler", command=cancel).pack(side="right", padx=4)
        tk.Button(btns, text="OK", command=ok).pack(side="right", padx=4)
        dlg.grab_set()
        dlg.wait_window()
        return res["val"]

    # --- selection handler (respects file.sys rules and system auth) ---
    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        path = self._item_path(sel[0])

        # If selecting something under system, require auth first (asynchronous)
        if self._is_path_in_system(path) and not self._system_unlocked:
            self._require_system_auth(on_success=lambda: self._on_tree_select_after_auth(sel[0]))
            return

        # clear previous state
        self._clear_preview()
        self._editing_path = None
        try:
            self.save_btn.config(state="disabled")
        except Exception:
            pass
        self._info_icon_ref = None
        self.info_label.config(image="", text="")

        if os.path.isdir(path):
            base = os.path.basename(path).lower()
            if os.path.realpath(path) == os.path.realpath(SANDBOX_ROOT):
                icon = self._icons.get("hdd") or self._icons.get("folder")
            elif base == "home":
                icon = self._icons.get("home") or self._icons.get("folder")
            elif base == "assets":
                icon = self._icons.get("assets") or self._icons.get("settings") or self._icons.get("folder")
            else:
                icon = self._icons.get("folder") or self._icons.get("default")
            self._info_icon_ref = icon
            self.info_label.config(image=icon, text=f"  Dossier: {os.path.relpath(path, SANDBOX_ROOT)}")
            self._show_editor_text(f"[Dossier] {os.path.basename(path)}", editable=False)
            self._hide_preview()
            return

        # non-directory, handle file
        self._handle_file(path)

    def _on_tree_double_click(self, event):
        # double click: if file is .dbn, open; else if folder, expand; else open notepad if editable
        sel = self.tree.selection()
        if not sel:
            return
        path = self._item_path(sel[0])
        if os.path.isdir(path):
            # toggle open
            try:
                cur = sel[0]
                is_open = self.tree.item(cur, "open")
                self.tree.item(cur, open=not is_open)
                if not is_open:
                    self._on_open(None)
            except Exception:
                pass
            return
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lstrip(".").lower()
        if ext == "dbn":
            # reuse selection handler which already handles .dbn
            self._on_tree_select(None)
            return
        # otherwise, if editable, open external editor
        allowed = self._rules.get(ext) or set()
        if "editor" in allowed:
            self._open_in_notepad(path)

    # --- preview/editor helpers ---
    def _clear_preview(self):
        try:
            self._hide_preview()
            self._hide_editor_area()
            self.editor.delete("1.0", "end")
            self._editing_path = None
        except Exception:
            pass

    def _show_image_preview(self, path):
        try:
            self._hide_preview()
            if not os.path.exists(path):
                return
            if PIL:
                img = Image.open(path).convert("RGBA")
                # fit into preview_frame
                w = self.preview_frame.winfo_width() or 320
                h = self.preview_frame.winfo_height() or 160
                img.thumbnail((w-8, h-8), Image.LANCZOS)
                tkimg = ImageTk.PhotoImage(img)
                self._preview_image_ref = tkimg
                self.preview_label.config(image=tkimg, text="")
                self.preview_label.image = tkimg
            else:
                tkimg = tk.PhotoImage(file=path)
                self._preview_image_ref = tkimg
                self.preview_label.config(image=tkimg, text="")
                self.preview_label.image = tkimg
            self.preview_frame.update_idletasks()
        except Exception:
            self._hide_preview()

    def _show_editor_text(self, text, editable=False):
        try:
            self._hide_preview()
            self.editor.config(state="normal")
            self.editor.delete("1.0", "end")
            if text is not None:
                self.editor.insert("1.0", text)
            if not editable:
                self.editor.config(state="disabled")
            else:
                self.editor.config(state="normal")
        except Exception:
            pass

    def _hide_preview(self):
        try:
            self.preview_label.config(image="", text="")
            self._preview_image_ref = None
        except Exception:
            pass

    def _hide_editor_area(self):
        try:
            self.editor.delete("1.0", "end")
            self.editor.config(state="disabled")
        except Exception:
            pass

    # --- toolbar actions (basic implementations) ---
    def create_folder(self):
        # create folder in currently selected directory (or home)
        sel = self.tree.selection()
        base_path = SANDBOX_ROOT
        if sel:
            p = self._item_path(sel[0])
            if os.path.isdir(p):
                base_path = p
            else:
                base_path = os.path.dirname(p)
        name = simpledialog.askstring("Nouveau dossier", "Nom du dossier :", parent=self.content if not self.internal else self.canvas)
        if not name:
            return
        try:
            newp = os.path.join(base_path, name)
            os.makedirs(newp, exist_ok=True)
            self._load_tree()
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de créer le dossier: {e}")

    def create_file(self):
        sel = self.tree.selection()
        base_path = SANDBOX_ROOT
        if sel:
            p = self._item_path(sel[0])
            if os.path.isdir(p):
                base_path = p
            else:
                base_path = os.path.dirname(p)
        name = simpledialog.askstring("Nouveau fichier", "Nom du fichier :", parent=self.content if not self.internal else self.canvas)
        if not name:
            return
        try:
            newp = os.path.join(base_path, name)
            with open(newp, "w", encoding="utf-8") as f:
                f.write("")
            self._load_tree()
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de créer le fichier: {e}")

    def import_file(self):
        src = filedialog.askopenfilename(title="Importer un fichier", initialdir=os.path.expanduser("~"))
        if not src:
            return
        sel = self.tree.selection()
        dest_dir = SANDBOX_ROOT
        if sel:
            p = self._item_path(sel[0])
            if os.path.isdir(p):
                dest_dir = p
            else:
                dest_dir = os.path.dirname(p)
        try:
            dst = os.path.join(dest_dir, os.path.basename(src))
            shutil.copy2(src, dst)
            self._load_tree()
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'importer le fichier: {e}")

    def delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        path = self._item_path(sel[0])
        if not path or not os.path.exists(path):
            return
        if messagebox.askyesno("Supprimer", f"Supprimer {os.path.basename(path)} ?"):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                self._load_tree()
                self._clear_preview()
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible de supprimer: {e}")

    def rename_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        path = self._item_path(sel[0])
        if not path:
            return
        new = simpledialog.askstring("Renommer", "Nouveau nom :", initialvalue=os.path.basename(path), parent=self.content if not self.internal else self.canvas)
        if not new:
            return
        try:
            dst = os.path.join(os.path.dirname(path), new)
            os.rename(path, dst)
            self._load_tree()
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de renommer: {e}")

    def edit_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        path = self._item_path(sel[0])
        if not path or not os.path.isfile(path):
            return
        # if editable, open in notepad
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        allowed = self._rules.get(ext) or set()
        if "editor" in allowed:
            self._open_in_notepad(path)
        else:
            messagebox.showinfo("Édition non autorisée", "Ce type de fichier n'est pas éditable selon file.sys.")

    def save_editor(self):
        # not used when using external notepad; fallback to no-op
        return

    def clear_editor(self):
        try:
            self.editor.delete("1.0", "end")
            self._editing_path = None
            try:
                self.save_btn.config(state="disabled")
            except Exception:
                pass
        except Exception:
            pass

    # --- close / cleanup ---
    def close(self):
        try:
            if self.internal:
                try:
                    self.canvas.delete(self.window_id)
                except Exception:
                    pass
            else:
                try:
                    self.win.destroy()
                except Exception:
                    pass
        except Exception:
            pass

# If run directly, demo the file manager
if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("1100x700")
    c = tk.Canvas(root, bg="#0b1220")
    c.pack(fill="both", expand=True)
    fm = FileManagerWindow(parent_canvas=c, x=60, y=60, width=900, height=560, internal=True, username="demo")
    root.mainloop()
