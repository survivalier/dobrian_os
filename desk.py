#!/usr/bin/env python3
# desk.py
# Contains the desktop UI logic extracted from main.py

import os
import sys
import time
import shutil
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import hashlib
import webbrowser
import importlib

# --- data directory setup ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

if DATA_DIR not in sys.path:
    sys.path.insert(0, DATA_DIR)

# --- try imports from data/ ---
try:
    from terminal import TerminalWindow
except Exception as e:
    TerminalWindow = None
    _term_import_error = e

try:
    from filemanager import FileManagerWindow
except Exception as e:
    FileManagerWindow = None
    _fm_import_error = e

try:
    from panel import PanelWindow
except Exception as e:
    PanelWindow = None
    _panel_import_error = e

# try to import code runner (for .dbn apps)
try:
    import code as code_module  # data/code.py
    CodeModuleAvailable = True
except Exception as e:
    code_module = None
    CodeModuleAvailable = False
    _code_import_error = e

# --- Attempt to use customtkinter for modern look, fallback to tkinter widgets ---
try:
    import customtkinter as ctk
    CTK_AVAILABLE = True
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
except Exception:
    CTK_AVAILABLE = False
    class _FakeCTK:
        CTk = tk.Tk
        CTkFrame = tk.Frame
        CTkButton = tk.Button
        CTkLabel = tk.Label
        CTkEntry = tk.Entry
        CTkOptionMenu = lambda *a, **k: ttk.Combobox(*a, **k)
    ctk = _FakeCTK()

# --- files inside data/ ---
ACCOUNTS_FILE = os.path.join(DATA_DIR, "dobrian_accounts.json")
LOGO_FILE = os.path.join(DATA_DIR, "logo.png")
ABOUT_ICON_FILE = os.path.join(DATA_DIR, "about.png")
BG_ICON_FILE = os.path.join(DATA_DIR, "background_app.png")
BACKGROUND_FILE = os.path.join(DATA_DIR, "file.dobrian", "system", "background", "background.png")
LOGIN_BG_FILE = os.path.join(DATA_DIR, "main.png")

# --- utilities for accounts ---
def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

def load_accounts():
    if not os.path.exists(ACCOUNTS_FILE):
        return {}
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_accounts(accounts):
    try:
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2)
    except Exception:
        pass

# --- Pillow optional for nicer icons ---
try:
    from PIL import Image, ImageTk
    PIL = True
except Exception:
    PIL = False

def safe_load_photo(path, size=None):
    """Return PhotoImage or None without raising."""
    if not path or not os.path.exists(path):
        return None
    if PIL and size:
        try:
            img = Image.open(path).convert("RGBA")
            img = img.resize(size, Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None
    else:
        try:
            return tk.PhotoImage(file=path)
        except Exception:
            return None

# --- ensure defaults for data/ and sandbox ---
def ensure_defaults():
    os.makedirs(DATA_DIR, exist_ok=True)
    sandbox = os.path.join(DATA_DIR, "file.dobrian")
    system_dir = os.path.join(sandbox, "system")
    assets_dir = os.path.join(system_dir, "assets")
    background_dir = os.path.join(system_dir, "background")
    os.makedirs(assets_dir, exist_ok=True)
    os.makedirs(background_dir, exist_ok=True)

    auth_sys = os.path.join(system_dir, "auth.sys")
    if not os.path.exists(auth_sys):
        try:
            with open(auth_sys, "w", encoding="utf-8") as f:
                f.write("# scope = unlock|lock, 0|1\n")
                f.write("home = unlock, 0\n")
                f.write("system = lock, 1\n")
        except Exception:
            pass

    file_sys = os.path.join(system_dir, "file.sys")
    if not os.path.exists(file_sys):
        try:
            with open(file_sys, "w", encoding="utf-8") as f:
                f.write("# Format: ext = editor|preview|editor,preview ;\n")
                f.write("txt = editor;\n")
                f.write("png = preview;\n")
                f.write("svg = editor, preview;\n")
        except Exception:
            pass

    if not os.path.exists(ACCOUNTS_FILE):
        try:
            pw = hashlib.sha256("admin".encode("utf-8")).hexdigest()
            with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                json.dump({"admin": pw}, f, indent=2)
        except Exception:
            pass

# -------------------------
# Helpers: maximize button + resizer grip for internal windows
# -------------------------
def _add_maximize_and_resizer(canvas: tk.Canvas, frame: tk.Frame, window_id, titlebar: tk.Frame,
                              min_w=200, min_h=120):
    try:
        if not hasattr(frame, "_resizer_state"):
            frame._resizer_state = {"maximized": False, "orig": None}

        def _toggle_maximize():
            try:
                st = frame._resizer_state
                cw = int(canvas.winfo_width() or canvas.winfo_reqwidth())
                ch = int(canvas.winfo_height() or canvas.winfo_reqheight())
                avail_h = max(100, ch - 60)
                if not st["maximized"]:
                    try:
                        coords = canvas.coords(window_id)
                        orig_w = int(canvas.itemcget(window_id, "width") or frame.winfo_width() or min_w)
                        orig_h = int(canvas.itemcget(window_id, "height") or frame.winfo_height() or min_h)
                        st["orig"] = (coords[0], coords[1], orig_w, orig_h)
                    except Exception:
                        st["orig"] = None
                    try:
                        canvas.coords(window_id, 0, 0)
                        canvas.itemconfig(window_id, width=cw, height=avail_h)
                    except Exception:
                        pass
                    st["maximized"] = True
                else:
                    if st.get("orig"):
                        ox, oy, ow, oh = st["orig"]
                        try:
                            canvas.coords(window_id, ox, oy)
                            canvas.itemconfig(window_id, width=ow, height=oh)
                        except Exception:
                            pass
                    st["maximized"] = False
            except Exception:
                pass

        try:
            if CTK_AVAILABLE:
                btn_max = ctk.CTkButton(titlebar, text="◻", fg_color=titlebar.cget("bg"), text_color="white", width=28, height=22, command=_toggle_maximize)
            else:
                btn_max = tk.Button(titlebar, text="◻", bg=titlebar.cget("bg"), fg="white", bd=0, padx=6, pady=0, command=_toggle_maximize)
        except Exception:
            btn_max = tk.Button(titlebar, text="◻", bg=titlebar.cget("bg"), fg="white", bd=0, padx=6, pady=0, command=_toggle_maximize)

        try:
            close_widget = None
            for c in titlebar.winfo_children():
                try:
                    if isinstance(c, tk.Button) and c.cget("text") == "✕":
                        close_widget = c
                        break
                except Exception:
                    pass
            if close_widget:
                btn_max.pack(side="right", before=close_widget, padx=4)
            else:
                btn_max.pack(side="right", padx=4)
        except Exception:
            try:
                btn_max.pack(side="right", padx=4)
            except Exception:
                pass

        grip_size = 12
        grip = tk.Frame(frame, width=grip_size, height=grip_size, bg=frame.cget("bg"), cursor="size_nw_se")
        try:
            grip.place(relx=1.0, rely=1.0, x=-grip_size, y=-grip_size, anchor="se")
        except Exception:
            try:
                grip.pack(side="right", anchor="se")
            except Exception:
                pass

        def _start_resize(e):
            try:
                frame._resizer_state["resizing"] = True
                frame._resizer_state["start_x"] = e.x_root
                frame._resizer_state["start_y"] = e.x_root
                try:
                    frame._resizer_state["orig_w"] = int(canvas.itemcget(window_id, "width") or frame.winfo_width() or min_w)
                    frame._resizer_state["orig_h"] = int(canvas.itemcget(window_id, "height") or frame.winfo_height() or min_h)
                except Exception:
                    frame._resizer_state["orig_w"] = frame.winfo_width() or min_w
                    frame._resizer_state["orig_h"] = frame.winfo_height() or min_h
            except Exception:
                pass

        def _do_resize(e):
            try:
                if not frame._resizer_state.get("resizing"):
                    return
                dx = e.x_root - frame._resizer_state.get("start_x", e.x_root)
                dy = e.x_root - frame._resizer_state.get("start_y", e.x_root)
                new_w = max(min_w, int(frame._resizer_state.get("orig_w", min_w) + dx))
                new_h = max(min_h, int(frame._resizer_state.get("orig_h", min_h) + dy))
                try:
                    canvas.itemconfig(window_id, width=new_w, height=new_h)
                except Exception:
                    pass
            except Exception:
                pass

        def _end_resize(e):
            try:
                frame._resizer_state["resizing"] = False
            except Exception:
                pass

        grip.bind("<ButtonPress-1>", _start_resize)
        grip.bind("<B1-Motion>", _do_resize)
        grip.bind("<ButtonRelease-1>", _end_resize)
    except Exception:
        pass

# -------------------------
# BackgroundApp (internal app)
# -------------------------
class BackgroundApp:
    def __init__(self, canvas: tk.Canvas, x=8, y=8, width=360, height=120, initial_path=None):
        self.canvas = canvas
        base_dir = os.path.join(DATA_DIR, "file.dobrian", "system", "background")
        os.makedirs(base_dir, exist_ok=True)
        self.background_dir = base_dir

        self.bg_path = None
        if initial_path and os.path.exists(initial_path):
            self.bg_path = self._import_to_background_dir(initial_path)
        else:
            self.bg_path = self._find_latest_background()

        self.bg_image_ref = None
        self.bg_item = None
        self.stretch_var = tk.BooleanVar(value=True)
        self._bind_id = None
        self._closed_by_self = False

        ctrl_w = width
        ctrl_h = height
        self.frame = tk.Frame(self.canvas, bd=2, relief="raised", bg="white")
        self.frame.pack_propagate(False)
        self.window_id = self.canvas.create_window(x, y, window=self.frame, anchor="nw", width=ctrl_w, height=ctrl_h)

        self.titlebar = tk.Frame(self.frame, bg="#2f2f2f", height=28)
        self.titlebar.pack(fill="x", side="top")
        tk.Label(self.titlebar, text="Background", fg="white", bg="#2f2f2f").pack(side="left", padx=8)
        tk.Button(self.titlebar, text="✕", bg="#2f2f2f", fg="white", bd=0, command=self._on_close).pack(side="right", padx=4)

        content = tk.Frame(self.frame, bg="white", padx=8, pady=6)
        content.pack(fill="both", expand=True)

        self.lbl_path = tk.Label(content, text=os.path.basename(self.bg_path) if self.bg_path else "Aucun fond défini", bg="white", anchor="w")
        self.lbl_path.pack(fill="x", pady=(0,6))

        btn_row = tk.Frame(content, bg="white")
        btn_row.pack(fill="x")
        tk.Button(btn_row, text="Changer le fond", command=self.change_background).pack(side="left", padx=(0,6))
        chk = tk.Checkbutton(btn_row, text="Ajuster à la fenêtre", variable=self.stretch_var, bg="white", command=self._on_toggle_stretch)
        chk.pack(side="left")

        tk.Label(content, text="Supprimez cette fenêtre via le Task Panel pour retirer le fond.", bg="white", fg="#666", anchor="w").pack(fill="x", pady=(6,0))

        self.titlebar.bind("<ButtonPress-1>", self._start_drag)
        self.titlebar.bind("<B1-Motion>", self._do_drag)

        self.frame.bind("<Destroy>", self._on_destroy_event)

        if self.bg_path:
            self._apply_background(self.bg_path)

        self._bind_canvas_resize()

        _add_maximize_and_resizer(self.canvas, self.frame, self.window_id, self.titlebar, min_w=200, min_h=120)

    def _import_to_background_dir(self, src_path: str) -> str:
        try:
            ext = os.path.splitext(src_path)[1].lower() or ".png"
            name = f"bg_{int(time.time())}{ext}"
            dst = os.path.join(self.background_dir, name)
            shutil.copy2(src_path, dst)
            return dst
        except Exception:
            return src_path

    def _find_latest_background(self):
        try:
            files = []
            for fn in os.listdir(self.background_dir):
                path = os.path.join(self.background_dir, fn)
                if os.path.isfile(path) and fn.lower().split(".")[-1] in ("png","jpg","jpeg","gif","bmp","webp"):
                    files.append(path)
            if not files:
                return None
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            return files[0]
        except Exception:
            return None

    def _start_drag(self, e):
        try:
            coords = self.canvas.coords(self.window_id)
            self._drag = {"sx": e.x_root, "sy": e.y_root, "ox": coords[0], "oy": coords[1]}
        except Exception:
            self._drag = None

    def _do_drag(self, e):
        if not getattr(self, "_drag", None):
            return
        d = self._drag
        dx = e.x_root - d["sx"]
        dy = e.x_root - d["sy"]
        nx = int(d["ox"] + dx)
        ny = int(d["oy"] + dy)
        pw = int(self.canvas.winfo_width() or self.canvas.winfo_reqwidth())
        ph = int(self.canvas.winfo_height() or self.canvas.winfo_reqheight())
        w = int(self.canvas.itemcget(self.window_id, "width") or 360)
        h = int(self.canvas.itemcget(self.window_id, "height") or 120)
        nx = max(0, min(nx, pw - w))
        ny = max(0, min(ny, ph - h - 60))
        try:
            self.canvas.coords(self.window_id, nx, ny)
        except Exception:
            pass

    def change_background(self):
        initial = DATA_DIR
        path = filedialog.askopenfilename(title="Choisir une image de fond", initialdir=initial,
                                          filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.gif;*.bmp;*.webp"), ("All files", "*.*")])
        if not path:
            return
        newpath = self._import_to_background_dir(path)
        self.bg_path = newpath
        self.lbl_path.configure(text=os.path.basename(newpath))
        self._apply_background(newpath)

    def _apply_background(self, path):
        if not path or not os.path.exists(path):
            return
        try:
            if self.stretch_var.get():
                w = int(self.canvas.winfo_width() or self.canvas.winfo_reqwidth())
                h = int(self.canvas.winfo_height() or self.canvas.winfo_reqheight())
                if PIL:
                    img = Image.open(path).convert("RGBA").resize((w, h), Image.LANCZOS)
                    self.bg_image_ref = ImageTk.PhotoImage(img)
                else:
                    self.bg_image_ref = tk.PhotoImage(file=path)
            else:
                if PIL:
                    img = Image.open(path).convert("RGBA")
                    self.bg_image_ref = ImageTk.PhotoImage(img)
                else:
                    self.bg_image_ref = tk.PhotoImage(file=path)
            if self.bg_item:
                try:
                    self.canvas.delete(self.bg_item)
                except Exception:
                    pass
            self.bg_item = self.canvas.create_image(0, 0, anchor="nw", image=self.bg_image_ref)
            # keep reference
        except Exception:
            pass

    def _on_toggle_stretch(self):
        if self.bg_path:
            self._apply_background(self.bg_path)

    def _on_close(self):
        self._closed_by_self = True
        try:
            self.canvas.delete(self.window_id)
        except Exception:
            pass

    def _on_destroy_event(self, e):
        if not self._closed_by_self:
            # user closed via the little ✕ widget on titlebar; unregister
            try:
                self.canvas.delete(self.window_id)
            except Exception:
                pass
        self._unbind_canvas_resize()

    def _bind_canvas_resize(self):
        try:
            root = self.canvas
            self._bind_id = (root, root.bind("<Configure>", self._on_canvas_resize))
        except Exception:
            self._bind_id = None

    def _unbind_canvas_resize(self):
        try:
            if self._bind_id:
                root, cb = self._bind_id
                try:
                    root.unbind("<Configure>", cb)
                except Exception:
                    pass
                self._bind_id = None
        except Exception:
            pass

# -------------------------
# Application principale (App class)
# -------------------------
class App:
    def __init__(self, root):
        self.root = root
        root.title("Dobrian Setup")
        root.geometry("1000x650")
        root.minsize(800, 500)

        # prepare containers (login and desktop will be created later)
        self.login_frame = None
        self.bg_label = None
        self.bg_photo = None
        self.internal_windows = []

        # desktop resources (canvas, images) will be prepared while splash shows
        self.canvas = None
        self.background_app = None
        self._about_img = None
        self._bg_img = None

        # show splash / pre-window first
        self._show_splash()

    def _show_splash(self):
        """Display a preliminary screen with logo & sound before login.
        Also preload desktop components while splash is visible."""
        # preload desktop resources so the UI is ready
        self._prepare_desktop()

        # create a full‑window frame
        self.splash_frame = tk.Frame(self.root, bg="white")
        self.splash_frame.place(relwidth=1, relheight=1)
        # logo image if available
        img = safe_load_photo(LOGO_FILE, size=(200,200)) or safe_load_photo(LOGO_FILE)
        if img:
            lbl = tk.Label(self.splash_frame, image=img, bg="white")
            lbl.image = img
            lbl.pack(expand=True)
        # play start sound asynchronously
        self._play_start_sound()
        # allow click to skip splash
        self.splash_frame.bind("<Button-1>", lambda e: self._end_splash())
        # after a short delay transition to login
        self.root.after(2000, self._end_splash)

    def _play_start_sound(self):
        """Try playing data/start.ogg using pygame or aplay."""
        snd = os.path.join(DATA_DIR, "start.ogg")
        if not os.path.exists(snd):
            return
        try:
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(snd)
            pygame.mixer.music.play()
        except Exception:
            try:
                os.system(f"aplay \"{snd}\" &")
            except Exception:
                pass

# -------------------------
# Application principale (App class)
# -------------------------

# --- Application principale ---
class App:
    def __init__(self, root):
        self.root = root
        root.title("Dobrian Setup")
        root.geometry("1000x650")
        root.minsize(800, 500)


        # prepare containers (login and desktop will be created later)
        self.login_frame = None
        self.bg_label = None
        self.bg_photo = None
        self.internal_windows = []

        # desktop resources (canvas, images) will be prepared while splash shows
        self.canvas = None
        self.background_app = None
        self._about_img = None
        self._bg_img = None

        # show splash / pre-window first
        self._show_splash()

    def _show_splash(self):
        """Display a preliminary screen with logo & sound before login.
        Also preload desktop components while splash is visible."""
        # preload desktop resources so the UI is ready
        self._prepare_desktop()

        # create a full‑window frame
        self.splash_frame = tk.Frame(self.root, bg="white")
        self.splash_frame.place(relwidth=1, relheight=1)
        # logo image if available
        img = safe_load_photo(LOGO_FILE, size=(200,200)) or safe_load_photo(LOGO_FILE)
        if img:
            lbl = tk.Label(self.splash_frame, image=img, bg="white")
            lbl.image = img
            lbl.pack(expand=True)
        # play start sound asynchronously
        self._play_start_sound()
        # allow click to skip splash
        self.splash_frame.bind("<Button-1>", lambda e: self._end_splash())
        # after a short delay transition to login
        self.root.after(2000, self._end_splash)

    def _play_start_sound(self):
        """Try playing data/start.ogg using pygame or aplay."""
        snd = os.path.join(DATA_DIR, "start.ogg")
        if not os.path.exists(snd):
            return
        try:
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(snd)
            pygame.mixer.music.play()
        except Exception:
            try:
                os.system(f"aplay \"{snd}\" &")
            except Exception:
                pass

    def _prepare_desktop(self):
        """Instantiate desktop canvas and pre‑load images while splash is visible.
        The canvas is packed immediately, but the splash frame will sit on top so user only sees the splash.
        Also load application modules and resources so they are ready when user reaches the desktop."""
        if self.canvas is not None:
            return
        # create canvas now so widgets initialize in background; do NOT pack yet
        self.canvas = tk.Canvas(self.root, highlightthickness=0)
        # ensure splash (when created) will cover canvas
        try:
            if hasattr(self, 'splash_frame') and self.splash_frame:
                self.splash_frame.lift()
        except Exception:
            pass
        # pre-load toolbar images
        self._about_img = safe_load_photo(ABOUT_ICON_FILE, size=(28,28)) if PIL else safe_load_photo(ABOUT_ICON_FILE)
        self._bg_img = safe_load_photo(BG_ICON_FILE, size=(28,28)) if PIL else safe_load_photo(BG_ICON_FILE)
        # pre-create background app offscreen (small size) so PIL loads image
        try:
            self.background_app = BackgroundApp(self.canvas, x=0, y=0, width=1, height=1, initial_path=None)
            # immediately hide it
            self.canvas.delete(self.background_app.window_id)
        except Exception:
            self.background_app = None

    def _start_desktop(self, username):
        # previously created canvas should be reused
        if self.canvas is None:
            self.canvas = tk.Canvas(self.root, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # background app: if we pre-created placeholder, recreate properly now
        if self.background_app is None:
            initial_bg = BACKGROUND_FILE if os.path.exists(BACKGROUND_FILE) else None
            self.background_app = BackgroundApp(self.canvas, initial_path=initial_bg)
        else:
            # if we had a placeholder, just reinstantiate real one
            initial_bg = BACKGROUND_FILE if os.path.exists(BACKGROUND_FILE) else None
            self.background_app = BackgroundApp(self.canvas, initial_path=initial_bg)

        self.taskbar = tk.Frame(self.root, bg="#222222")
        self.taskbar.place(relx=0.02, rely=0.92, relwidth=0.96, relheight=0.07)
        inner = tk.Frame(self.taskbar, bg="#2b2b2b")
        inner.place(relx=0.02, rely=0.12, relwidth=0.96, relheight=0.76)

        def _make_btn(parent, text, cmd, **kw):
            if CTK_AVAILABLE:
                btn = ctk.CTkButton(parent, text=text, command=cmd, fg_color="#2b2b2b", text_color="white", corner_radius=6)
            else:
                btn = tk.Button(parent, text=text, command=cmd, bg="#2b2b2b", fg="white", bd=0)
            btn.pack(side="left", padx=8, pady=4)
            return btn

        _make_btn(inner, "Terminal", lambda: self._open_terminal(username))
        _make_btn(inner, "File Manager", lambda: self._open_filemanager(username))
        _make_btn(inner, "Task Panel", self._open_task_panel)
        _make_btn(inner, "Apps", self._open_apps_menu)  # new Apps button to open .dbn files

        right_frame = tk.Frame(inner, bg="#2b2b2b")
        right_frame.pack(side="right", padx=8, pady=4)

        if self._about_img:
            if CTK_AVAILABLE:
                btn_about = ctk.CTkButton(right_frame, text="", image=self._about_img, width=36, height=36, command=self._open_about, fg_color="transparent")
                btn_about.image = self._about_img
            else:
                btn_about = tk.Button(right_frame, image=self._about_img, command=self._open_about, bg="#2b2b2b", bd=0)
                btn_about.image = self._about_img
        else:
            btn_about = (ctk.CTkButton(right_frame, text="About", command=self._open_about) if CTK_AVAILABLE else tk.Button(right_frame, text="About", command=self._open_about))
        btn_about.pack(side="right", padx=(6,0))

        if self._bg_img:
            if CTK_AVAILABLE:
                btn_bg = ctk.CTkButton(right_frame, text="", image=self._bg_img, width=36, height=36, command=self._open_background, fg_color="transparent")
                btn_bg.image = self._bg_img
            else:
                btn_bg = tk.Button(right_frame, image=self._bg_img, command=self._open_background, bg="#2b2b2b", bd=0)
                btn_bg.image = self._bg_img
        else:
            btn_bg = (ctk.CTkButton(right_frame, text="BG", command=self._open_background) if CTK_AVAILABLE else tk.Button(right_frame, text="BG", command=self._open_background))
        btn_bg.pack(side="right", padx=(6,0))

        self.logo_small = self._about_img

    def _end_splash(self):
        try:
            self.splash_frame.destroy()
        except Exception:
            pass
        # build login UI now that splash is gone
        self.login_frame = tk.Frame(self.root, bg="#f0f0f0")
        self.login_frame.place(relwidth=1, relheight=1)
        self._build_login()
        self.root.after(60, self._update_login_bg)

    def _build_login(self):
        # called after splash is removed; login_frame already exists
        # Use CTkFrame if available for nicer look, else tk.Frame
        if CTK_AVAILABLE:
            box = ctk.CTkFrame(self.login_frame, fg_color="white", corner_radius=6, width=420, height=320)
            box.place(relx=0.5, rely=0.5, anchor="center")
            ctk.CTkLabel(box, text="Dobrian Login", font=("Segoe UI", 16, "bold")).pack(pady=(16,8))

            self.user_var = tk.StringVar()
            self.pw_var = tk.StringVar()

            ctk.CTkLabel(box, text="Nom d'utilisateur").pack(anchor="w", padx=20)
            ctk.CTkEntry(box, textvariable=self.user_var, width=360).pack(fill="x", padx=20, pady=(0,8))

            ctk.CTkLabel(box, text="Mot de passe").pack(anchor="w", padx=20)
            ctk.CTkEntry(box, textvariable=self.pw_var, show="*", width=360).pack(fill="x", padx=20, pady=(0,8))

            btn_frame = ctk.CTkFrame(box, fg_color="transparent")
            btn_frame.pack(pady=12)
            ctk.CTkButton(btn_frame, text="Se connecter", command=self._login, width=140).pack(side="left", padx=8)
            ctk.CTkButton(btn_frame, text="Créer un compte", command=self._create_account, width=140).pack(side="left", padx=8)

            ctk.CTkLabel(box, text="Les comptes sont stockés localement (démo).", text_color="#555").pack(side="bottom", pady=8)
        else:
            box = tk.Frame(self.login_frame, bg="white", bd=1, relief="solid")
            box.place(relx=0.5, rely=0.5, anchor="center", width=420, height=320)
            tk.Label(box, text="Dobrian Login", font=("Segoe UI", 16, "bold"), bg="white").pack(pady=(16,8))
            self.user_var = tk.StringVar()
            self.pw_var = tk.StringVar()
            tk.Label(box, text="Nom d'utilisateur", bg="white").pack(anchor="w", padx=20)
            tk.Entry(box, textvariable=self.user_var).pack(fill="x", padx=20, pady=(0,8))
            tk.Label(box, text="Mot de passe", bg="white").pack(anchor="w", padx=20)
            tk.Entry(box, textvariable=self.pw_var, show="*").pack(fill="x", padx=20, pady=(0,8))
            btn_frame = tk.Frame(box, bg="white")
            btn_frame.pack(pady=12)
            tk.Button(btn_frame, text="Se connecter", command=self._login).pack(side="left", padx=8)
            tk.Button(btn_frame, text="Créer un compte", command=self._create_account).pack(side="left", padx=8)
            tk.Label(box, text="Les comptes sont stockés localement (démo).", bg="white", fg="#555").pack(side="bottom", pady=8)

    def _update_login_bg(self):
        # bail out if login frame has been removed or destroyed
        if not getattr(self, 'login_frame', None):
            return
        try:
            if not self.login_frame.winfo_exists():
                return
        except Exception:
            return
        w = max(200, self.root.winfo_width() or 800)
        h = max(150, self.root.winfo_height() or 600)
        if os.path.exists(LOGIN_BG_FILE) and PIL:
            try:
                img = Image.open(LOGIN_BG_FILE).convert("RGBA").resize((w,h), Image.LANCZOS)
                self.bg_photo = ImageTk.PhotoImage(img)
                if not self.bg_label:
                    self.bg_label = tk.Label(self.login_frame, image=self.bg_photo)
                    self.bg_label.place(relx=0, rely=0, relwidth=1, relheight=1)
                else:
                    self.bg_label.configure(image=self.bg_photo)
                if self.bg_label:
                    try: self.bg_label.lower()
                    except Exception: pass
                return
            except Exception:
                pass
        if self.bg_label:
            try: self.bg_label.destroy()
            except Exception: pass
            self.bg_label = None
            self.bg_photo = None
        self.login_frame.configure(bg="#f0f0f0")

    def _login(self):
        user = self.user_var.get().strip()
        pw = self.pw_var.get()
        if not user or not pw:
            messagebox.showwarning("Erreur", "Nom d'utilisateur et mot de passe requis.")
            return
        accounts = load_accounts()
        if user not in accounts or accounts[user] != hash_password(pw):
            messagebox.showerror("Échec", "Identifiants incorrects.")
            return
        self.login_frame.destroy()
        self._start_desktop(user)

    def _create_account(self):
        user = self.user_var.get().strip()
        pw = self.pw_var.get()
        if not user or not pw:
            messagebox.showwarning("Erreur", "Nom d'utilisateur et mot de passe requis.")
            return
        accounts = load_accounts()
        if user in accounts:
            messagebox.showerror("Erreur", "Utilisateur déjà existant.")
            return
        accounts[user] = hash_password(pw)
        save_accounts(accounts)
        messagebox.showinfo("Succès", "Compte créé. Vous êtes connecté.")
        self.login_frame.destroy()
        self._start_desktop(user)

    def _open_about(self):
        frame = tk.Frame(self.canvas, bd=2, relief="raised", bg="white")
        titlebar = tk.Frame(frame, bg="#2f2f2f", height=28)
        titlebar.pack(fill="x", side="top")
        tk.Label(titlebar, text="About Dobrian", fg="white", bg="#2f2f2f").pack(side="left", padx=6)
        btn_close = tk.Button(titlebar, text="✕", bg="#2f2f2f", fg="white", bd=0, command=lambda: self.canvas.delete(win_id))
        btn_close.pack(side="right", padx=4)

        content = tk.Frame(frame, bg="white")
        content.pack(fill="both", expand=True)

        top = tk.Frame(content, bg="white")
        top.pack(fill="x", padx=8, pady=8)

        logo_img = safe_load_photo(LOGO_FILE, size=(64,64)) if PIL else safe_load_photo(LOGO_FILE)
        if logo_img:
            lbl_logo = tk.Label(top, image=logo_img, bg="white")
            lbl_logo.image = logo_img
            lbl_logo.pack(side="left", padx=(0,10))
        else:
            tk.Label(top, text="[logo]", bg="white", width=8).pack(side="left", padx=(0,10))

        txt_frame = tk.Frame(top, bg="white")
        txt_frame.pack(side="left", fill="y", expand=True)

        tk.Label(txt_frame, text="Dobrian OS", font=("Segoe UI", 14, "bold"), bg="white").pack(anchor="w")
        try:
            year = time.localtime().tm_year
        except Exception:
            year = time.strftime("%Y")
        tk.Label(txt_frame, text=f"© {year} ⦁ Survivalier", bg="white", fg="#666").pack(anchor="w", pady=(4,0))

        ttk.Separator(content, orient="horizontal").pack(fill="x", padx=8, pady=6)

        desc = tk.Label(content, text=(
            "Dobrian est un système d'exploitation expérimental\n"
            "conçu pour la simplicité et l'apprentissage. Cette\n"
            "démo montre une interface minimale et des outils\n"
            "intégrés pour prototypage."
        ), justify="left", bg="white")
        desc.pack(fill="x", padx=12)

        link = tk.Label(content, text="https://dobrian.ct.ws/", fg="blue", cursor="hand2", bg="white")
        link.pack(anchor="w", padx=12, pady=(8,0))
        link.bind("<Button-1>", lambda e: webbrowser.open("https://dobrian.ct.ws/"))

        win_id = self.canvas.create_window(80, 80, window=frame, anchor="nw", width=480, height=260)
        _add_maximize_and_resizer(self.canvas, frame, win_id, titlebar, min_w=320, min_h=200)
        self.internal_windows.append({"id": win_id, "title": "About", "bring_to_front": lambda: self.canvas.tag_raise(win_id), "close": lambda: self.canvas.delete(win_id)})

    def _open_background(self):
        try:
            existing = getattr(self, "background_app", None)
            if existing is not None:
                try:
                    win_id = getattr(existing, "window_id", None)
                    if win_id is not None:
                        try:
                            if self.canvas.type(win_id) == "window":
                                try:
                                    self.canvas.tag_raise(win_id)
                                except Exception:
                                    pass
                                return existing
                        except Exception:
                            pass
                except Exception:
                    pass
            initial_bg = BACKGROUND_FILE if os.path.exists(BACKGROUND_FILE) else None
            self.background_app = BackgroundApp(self.canvas, initial_path=initial_bg)
            # register background window in internal_windows for Task Panel
            try:
                self.internal_windows.append({"id": self.background_app.window_id, "title": "Background", "bring_to_front": lambda: self.canvas.tag_raise(self.background_app.window_id), "close": lambda: self.background_app._on_close()})
            except Exception:
                pass
            return self.background_app
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir Background: {e}")
            return None

    def _open_terminal(self, username):
        if TerminalWindow is None:
            messagebox.showerror("Erreur", f"terminal.py introuvable dans data/: {_term_import_error}")
            return
        try:
            term = TerminalWindow(parent_canvas=self.canvas, x=120, y=120, width=700, height=380,
                                   username=username, internal=True)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le terminal: {e}")
            return
        try:
            if hasattr(term, "frame") and hasattr(term, "titlebar") and hasattr(term, "window_id"):
                _add_maximize_and_resizer(self.canvas, term.frame, term.window_id, term.titlebar, min_w=420, min_h=260)
                # register in internal windows
                self.internal_windows.append({"id": term.window_id, "title": getattr(term, "title_label", getattr(term, "prompt_str", "Terminal")), "bring_to_front": lambda wid=term.window_id: self.canvas.tag_raise(wid), "close": lambda wid=term.window_id: self.canvas.delete(wid)})
        except Exception:
            pass



    def _open_filemanager(self, username):
        if FileManagerWindow is None:
            messagebox.showerror("Erreur", f"filemanager.py introuvable dans data/: {_fm_import_error}")
            return
        try:
            fm = FileManagerWindow(parent_canvas=self.canvas, x=140, y=140, width=720, height=420, username=username, internal=True)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le gestionnaire de fichiers: {e}")
            return
        try:
            if hasattr(fm, "frame") and hasattr(fm, "titlebar") and hasattr(fm, "window_id"):
                _add_maximize_and_resizer(self.canvas, fm.frame, fm.window_id, fm.titlebar, min_w=420, min_h=260)
                self.internal_windows.append({"id": fm.window_id, "title": getattr(fm, "title_label", "File Manager"), "bring_to_front": lambda wid=fm.window_id: self.canvas.tag_raise(wid), "close": lambda wid=fm.window_id: self.canvas.delete(wid)})
        except Exception:
            pass

    # -------------------------
    # Apps (.dbn) support
    # -------------------------
    def _open_apps_menu(self):
        # simple file dialog to choose a .dbn file and render it via code_module
        if not CodeModuleAvailable:
            messagebox.showerror("Erreur", f"code.py introuvable dans data/: {_code_import_error}")
            return
        path = filedialog.askopenfilename(title="Ouvrir une application (.dbn)", initialdir=DATA_DIR,
                                          filetypes=[("Dobrian apps", "*.dbn"), ("All files", "*.*")])
        if not path:
            return
        try:
            # code_module is expected to provide render_dbn(canvas, x,y,w,h,path, register_callback)
            # register_callback is a function the code module can call to register the created window in main app
            def register(win_dict):
                # win_dict must contain: id, title, bring_to_front(), close()
                try:
                    self.internal_windows.append(win_dict)
                    self._refresh_internal_registry()
                except Exception:
                    pass

            # choose placement and size
            x, y, w, h = 160, 140, 640, 360
            win_info = None
            try:
                # prefer a function named render_dbn
                if hasattr(code_module, "render_dbn"):
                    win_info = code_module.render_dbn(parent_canvas=self.canvas, x=x, y=y, width=w, height=h, path=path, register_callback=register)
                elif hasattr(code_module, "run_dbn"):
                    win_info = code_module.run_dbn(parent_canvas=self.canvas, x=x, y=y, width=w, height=h, path=path, register_callback=register)
                else:
                    messagebox.showerror("Erreur", "code.py ne propose pas de fonction render_dbn ou run_dbn.")
                    return
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible d'exécuter l'application: {e}")
                return

            # If the code module returned a window dict, register it
            if isinstance(win_info, dict):
                # ensure bring_to_front and close exist
                if "bring_to_front" not in win_info or "close" not in win_info:
                    # try to wrap if it returned a canvas window id
                    wid = win_info.get("id") if "id" in win_info else None
                    if wid:
                        win_info.setdefault("bring_to_front", lambda wid=wid: self.canvas.tag_raise(wid))
                        win_info.setdefault("close", lambda wid=wid: self.canvas.delete(wid))
                self.internal_windows.append(win_info)
                self._refresh_internal_registry()
            else:
                # if nothing returned, rely on register callback
                self._refresh_internal_registry()
        except Exception as e:
            messagebox.showerror("Erreur", f"Erreur lors de l'ouverture de l'application: {e}")

    def _refresh_internal_registry(self):
        # remove entries whose canvas window no longer exists
        cleaned = []
        for w in self.internal_windows:
            wid = w.get("id")
            try:
                if wid and self.canvas.type(wid) == "window":
                    cleaned.append(w)
                else:
                    # if id missing, keep if callable present
                    if not wid and callable(w.get("bring_to_front")):
                        cleaned.append(w)
            except Exception:
                # ignore invalid entries
                pass
        self.internal_windows = cleaned

    def _open_task_panel(self):
        # ensure registry is up to date
        self._refresh_internal_registry()

        # build internal window frame
        frame = tk.Frame(self.canvas, bd=2, relief="raised", bg="white")
        titlebar = tk.Frame(frame, bg="#2f2f2f", height=28)
        titlebar.pack(fill="x", side="top")
        tk.Label(titlebar, text="Task Panel", fg="white", bg="#2f2f2f").pack(side="left", padx=6)
        btn_close = tk.Button(titlebar, text="✕", bg="#2f2f2f", fg="white", bd=0)
        btn_close.pack(side="right", padx=4)

        content = tk.Frame(frame, bg="white")
        content.pack(fill="both", expand=True, padx=8, pady=8)

        listbox = tk.Listbox(content, activestyle="none")
        listbox.pack(fill="both", expand=True, pady=(4,8))

        # populate listbox
        def _populate():
            listbox.delete(0, "end")
            self._refresh_internal_registry()
            for w in self.internal_windows:
                listbox.insert("end", w.get("title", "App"))

        _populate()

        btn_row = tk.Frame(content, bg="white")
        btn_row.pack(fill="x")

        def _bring_selected():
            sel = listbox.curselection()
            if not sel:
                return
            idx = sel[0]
            w = self.internal_windows[idx]
            try:
                w.get("bring_to_front", lambda: None)()
            except Exception:
                pass

        def _close_selected():
            sel = listbox.curselection()
            if not sel:
                return
            idx = sel[0]
            w = self.internal_windows[idx]
            try:
                w.get("close", lambda: None)()
            except Exception:
                pass
            self._refresh_internal_registry()
            _populate()

        def _refresh():
            self._refresh_internal_registry()
            _populate()

        tk.Button(btn_row, text="Rafraîchir", command=_refresh).pack(side="left", padx=6)
        tk.Button(btn_row, text="Basculer", command=_bring_selected).pack(side="left", padx=6)
        tk.Button(btn_row, text="Fermer", command=_close_selected).pack(side="left", padx=6)
        tk.Button(btn_row, text="Fermer tout", command=lambda: [w.get("close", lambda: None)() for w in list(self.internal_windows)]).pack(side="right", padx=6)

        # place the internal window on the canvas
        x, y, w, h = 80, 80, 420, 360
        win_id = self.canvas.create_window(x, y, window=frame, anchor="nw", width=w, height=h)

        # close behavior for the internal window
        def _close_panel():
            try:
                self.canvas.delete(win_id)
            except Exception:
                pass
            # remove any registry entry that references this window id (if present)
            try:
                self.internal_windows = [it for it in self.internal_windows if it.get("id") != win_id]
            except Exception:
                pass

        btn_close.config(command=_close_panel)

        # drag support for the titlebar
        drag = {"sx": 0, "sy": 0, "ox": x, "oy": y, "w": w, "h": h}
        def on_press(e):
            drag["sx"] = e.x_root
            drag["sy"] = e.y_root
            coords = self.canvas.coords(win_id)
            drag["ox"] = coords[0]
            drag["oy"] = coords[1]
            try:
                self.canvas.tag_raise(win_id)
            except Exception:
                pass

        def on_motion(e):
            dx = e.x_root - drag["sx"]
            dy = e.y_root - drag["sy"]
            nx = int(drag["ox"] + dx)
            ny = int(drag["oy"] + dy)
            pw = int(self.canvas.winfo_width() or self.canvas.winfo_reqwidth())
            ph = int(self.canvas.winfo_height() or self.canvas.winfo_reqheight())
            nx = max(0, min(nx, pw - drag["w"]))
            ny = max(0, min(ny, ph - drag["h"] - 60))
            try:
                self.canvas.coords(win_id, nx, ny)
            except Exception:
                pass

        titlebar.bind("<ButtonPress-1>", on_press)
        titlebar.bind("<B1-Motion>", on_motion)

        # add maximize/resize controls
        try:
            _add_maximize_and_resizer(self.canvas, frame, win_id, titlebar, min_w=320, min_h=200)
        except Exception:
            pass

        # register this internal Task Panel window so it appears in the Task Panel list itself
        try:
            self.internal_windows.append({
                "id": win_id,
                "title": "Task Panel",
                "bring_to_front": lambda wid=win_id: self.canvas.tag_raise(wid),
                "close": _close_panel
            })
        except Exception:
            pass


# -------------------------
# Entrypoint
# -------------------------
def main():
    ensure_defaults()
    root = ctk.CTk() if CTK_AVAILABLE else tk.Tk()
    root.title("Dobrian")
    root.geometry("1000x650")

    app = App(root)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
