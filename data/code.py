#!/usr/bin/env python3
# data/code.py
# Enhanced .dbn renderer for Dobrian with attribute support (buttons in titlebar)
import os
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import xml.etree.ElementTree as ET
import webbrowser

# Optional Pillow for image handling
try:
    from PIL import Image, ImageTk
    PIL = True
except Exception:
    PIL = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # data/
SANDBOX_ROOT = os.path.join(BASE_DIR, "file.dobrian")
ENV_ROOT = os.path.join(BASE_DIR, "app_envs")
os.makedirs(ENV_ROOT, exist_ok=True)

# -------------------------
# Helpers
# -------------------------
def _attr(el, name, default=None):
    try:
        return el.attrib.get(name, default)
    except Exception:
        return default

def _text(el):
    try:
        return (el.text or "").strip()
    except Exception:
        return ""

def _safe_color(s, fallback="#2f2f2f"):
    if not s:
        return fallback
    s = s.strip()
    if s.startswith("#") and len(s) in (4,7,9):
        return s
    return fallback

def _parse_size(value, fallback=None):
    if value is None:
        return fallback
    v = str(value).strip()
    if not v:
        return fallback
    try:
        if v.endswith("px"):
            return int(v[:-2])
        if v.endswith("%"):
            return v
        return int(v)
    except Exception:
        return fallback

def _resolve_sandbox_path(path_str):
    if not path_str:
        return None
    p = path_str.strip()
    if p.startswith("/"):
        candidate = os.path.join(SANDBOX_ROOT, p.lstrip("/"))
        return candidate
    candidate = os.path.join(SANDBOX_ROOT, p)
    return candidate

def _list_files_with_ext(ext, base=None):
    matches = []
    if base is None:
        base = SANDBOX_ROOT
    for root, dirs, files in os.walk(base):
        for f in files:
            if f.lower().endswith("." + ext.lower()):
                matches.append(os.path.join(root, f))
    return matches

# --- new utilities -----------------------------------------------------
def authenticate_sync(parent_canvas=None, parent_toplevel=None):
    try:
        from auth import AuthWindow
    except Exception:
        return None
    result = {"res": None}
    def cb(res):
        result["res"] = res
    try:
        AuthWindow(parent_canvas=parent_canvas, parent_toplevel=parent_toplevel, callback=cb)
    except Exception:
        try:
            AuthWindow(parent_canvas=parent_canvas, parent_toplevel=parent_toplevel, internal=False, callback=cb)
        except Exception:
            return None
    parent = parent_canvas or parent_toplevel
    if parent is None:
        return None
    while result["res"] is None:
        try:
            parent.update()
        except Exception:
            pass
        time.sleep(0.05)
    return result["res"]

def create_isolated_env(name):
    if not name:
        return None
    path = os.path.join(ENV_ROOT, name)
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path

# Small utility to create a scrollable frame
class ScrollableFrame(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, bg=self.cget("bg"))
        self._canvas = canvas
        vsb = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(canvas, bg=self.cget("bg"))
        self._win = canvas.create_window((0,0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(self._win, width=e.width))

# Local resizer / maximize helper (kept simple)
def _add_local_resizer(canvas, frame, window_id, titlebar, min_w=200, min_h=120):
    try:
        state = {"maximized": False, "orig": None}
        def toggle():
            try:
                cw = int(canvas.winfo_width() or canvas.winfo_reqwidth())
                ch = int(canvas.winfo_height() or canvas.winfo_reqheight())
                avail_h = max(100, ch - 60)
                if not state["maximized"]:
                    coords = canvas.coords(window_id)
                    try:
                        orig_w = int(canvas.itemcget(window_id, "width") or frame.winfo_width() or min_w)
                        orig_h = int(canvas.itemcget(window_id, "height") or frame.winfo_height() or min_h)
                        state["orig"] = (coords[0], coords[1], orig_w, orig_h)
                    except Exception:
                        state["orig"] = None
                    canvas.coords(window_id, 0, 0)
                    canvas.itemconfig(window_id, width=cw, height=avail_h)
                    state["maximized"] = True
                else:
                    if state.get("orig"):
                        ox, oy, ow, oh = state["orig"]
                        canvas.coords(window_id, ox, oy)
                        canvas.itemconfig(window_id, width=ow, height=oh)
                    state["maximized"] = False
            except Exception:
                pass
        btn = tk.Button(titlebar, text="◻", bg=titlebar.cget("bg"), fg="white", bd=0, padx=6, pady=0, command=toggle)
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
                btn.pack(side="right", before=close_widget, padx=4)
            else:
                btn.pack(side="right", padx=4)
        except Exception:
            try:
                btn.pack(side="right", padx=4)
            except Exception:
                pass
        grip = tk.Frame(frame, width=12, height=12, bg=frame.cget("bg"), cursor="size_nw_se")
        try:
            grip.place(relx=1.0, rely=1.0, x=-12, y=-12, anchor="se")
        except Exception:
            try:
                grip.pack(side="right", anchor="se")
            except Exception:
                pass
    except Exception:
        pass

# Render helpers for interactive elements
def _open_file_popup(parent, file_path, title=None, icon_photo=None):
    try:
        if not os.path.exists(file_path):
            messagebox.showerror("Fichier introuvable", f"{file_path} introuvable.")
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = f.read()
            dlg = tk.Toplevel(parent)
            dlg.title(title or os.path.basename(file_path))
            if icon_photo:
                try:
                    dlg.iconphoto(False, icon_photo)
                except Exception:
                    pass
            txt = tk.Text(dlg, wrap="word")
            txt.pack(fill="both", expand=True)
            txt.insert("1.0", data)
            txt.config(state="disabled")
            return dlg
        except Exception:
            messagebox.showinfo("Fichier", f"Impossible d'afficher le contenu de {os.path.basename(file_path)}.")
            return None
    except Exception:
        return None

def _edit_file_popup(parent, file_path, title=None, icon_photo=None):
    try:
        if not os.path.exists(file_path):
            try:
                with open(file_path, "w", encoding="utf-8"):
                    pass
            except Exception:
                pass
        dlg = tk.Toplevel(parent)
        dlg.title(title or os.path.basename(file_path))
        if icon_photo:
            try:
                dlg.iconphoto(False, icon_photo)
            except Exception:
                pass
        txt = tk.Text(dlg, wrap="word")
        txt.pack(fill="both", expand=True)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                txt.insert("1.0", f.read())
        except Exception:
            pass
        def _save():
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(txt.get("1.0", "end-1c"))
                messagebox.showinfo("Enregistré", "Fichier enregistré.")
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible d'enregistrer: {e}")
        btn = tk.Button(dlg, text="Enregistrer", command=_save)
        btn.pack(side="bottom", pady=4)
        return dlg
    except Exception:
        return None

# -------------------------
# Main renderer
# -------------------------
def render_dbn(parent_canvas, x=120, y=120, width=640, height=360, path=None, register_callback=None):
    if parent_canvas is None:
        raise ValueError("parent_canvas is required")

    app_name = "DBN App"
    author = ""
    theme_color = "#2f2f2f"
    default_height = height
    default_width = width
    app_icon_path = None
    app_icon_photo = None
    # store button images to keep references
    _title_button_images = []

    content_text = ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content_text = f.read()
    except Exception as e:
        frame = tk.Frame(parent_canvas, bd=2, relief="raised", bg="white")
        titlebar = tk.Frame(frame, bg="#2f2f2f", height=28)
        titlebar.pack(fill="x", side="top")
        tk.Label(titlebar, text="App Error", fg="white", bg="#2f2f2f").pack(side="left", padx=6)
        btn_close = tk.Button(titlebar, text="✕", bg="#2f2f2f", fg="white", bd=0)
        btn_close.pack(side="right", padx=4)
        content_frame = tk.Frame(frame, bg="white")
        content_frame.pack(fill="both", expand=True, padx=8, pady=8)
        tk.Label(content_frame, text=f"Impossible de lire {os.path.basename(path)}: {e}", bg="white", fg="#a00").pack()
        win_id = parent_canvas.create_window(x, y, window=frame, anchor="nw", width=width, height=height)
        def close():
            try:
                parent_canvas.delete(win_id)
            except Exception:
                pass
        btn_close.config(command=close)
        _add_local_resizer(parent_canvas, frame, win_id, titlebar)
        win_dict = {"id": win_id, "title": f"Error: {os.path.basename(path)}", "bring_to_front": lambda: parent_canvas.tag_raise(win_id), "close": close}
        if callable(register_callback):
            try:
                register_callback(win_dict)
            except Exception:
                pass
        return win_dict

    # parse XML (tolerant)
    root = None
    try:
        root = ET.fromstring(content_text)
    except Exception:
        try:
            root = ET.fromstring("<root>" + content_text + "</root>")
        except Exception:
            root = None

    # extract settings and attributes
    if root is not None:
        settings = None
        if root.tag.lower() == "dobrian":
            settings = root.find("settings")
        else:
            settings = root.find(".//settings")
        if settings is not None:
            for d in settings.findall("def"):
                name = _attr(d, "name")
                author_attr = _attr(d, "author")
                color_attr = _attr(d, "color")
                height_attr = _attr(d, "height") or _attr(d, "h")
                width_attr = _attr(d, "width") or _attr(d, "weight") or _attr(d, "w")
                icon_attr = _attr(d, "icon")
                if name:
                    app_name = name
                if author_attr:
                    author = author_attr
                if color_attr:
                    theme_color = _safe_color(color_attr, theme_color)
                if height_attr:
                    parsed = _parse_size(height_attr, fallback=None)
                    if isinstance(parsed, int):
                        default_height = parsed
                if width_attr:
                    parsed = _parse_size(width_attr, fallback=None)
                    if isinstance(parsed, int):
                        default_width = parsed
                if icon_attr:
                    resolved_icon = _resolve_sandbox_path(icon_attr)
                    if resolved_icon and os.path.exists(resolved_icon):
                        app_icon_path = resolved_icon

    # parse <app> section for titlebar buttons (outside <main>)
    app_buttons = []
    if root is not None:
        app_section = None
        if root.tag.lower() == "dobrian":
            app_section = root.find("app")
        else:
            app_section = root.find(".//app")
        if app_section is not None:
            for b in app_section.findall("button"):
                btn_icon = _attr(b, "icon")
                btn_web = _attr(b, "web")
                btn_label = _attr(b, "label") or _attr(b, "title") or None
                # store raw attrs; resolution/loading happens later when building UI
                app_buttons.append({"icon": btn_icon, "web": btn_web, "label": btn_label})

    # prepare app icon image if present
    if app_icon_path:
        try:
            if PIL:
                img = Image.open(app_icon_path).convert("RGBA")
                img.thumbnail((20, 20), Image.LANCZOS)
                app_icon_photo = ImageTk.PhotoImage(img)
            else:
                app_icon_photo = tk.PhotoImage(file=app_icon_path)
        except Exception:
            app_icon_photo = None

    # build UI window on canvas
    frame = tk.Frame(parent_canvas, bd=2, relief="raised", bg="white")
    frame.pack_propagate(False)
    titlebar = tk.Frame(frame, bg=theme_color, height=28)
    titlebar.pack(fill="x", side="top")

    # If icon exists, pack it first
    if app_icon_photo:
        try:
            icon_lbl = tk.Label(titlebar, image=app_icon_photo, bg=theme_color)
            icon_lbl.image = app_icon_photo
            icon_lbl.pack(side="left", padx=(6, 4))
        except Exception:
            pass

    title_lbl = tk.Label(titlebar, text=app_name, fg="white", bg=theme_color)
    title_lbl.pack(side="left", padx=6)

    # create titlebar buttons from <app><button .../>
    # pack them to the right, before the close button
    def _create_title_button(btn_def):
        icon_path = btn_def.get("icon")
        web_target = btn_def.get("web")
        label = btn_def.get("label")
        tkimg = None
        if icon_path:
            resolved = _resolve_sandbox_path(icon_path)
            if resolved and os.path.exists(resolved):
                try:
                    if PIL:
                        img = Image.open(resolved).convert("RGBA")
                        img.thumbnail((18, 18), Image.LANCZOS)
                        tkimg = ImageTk.PhotoImage(img)
                    else:
                        tkimg = tk.PhotoImage(file=resolved)
                except Exception:
                    tkimg = None
        # action: open web if provided, else noop
        def _on_click(url=web_target):
            if url:
                try:
                    webbrowser.open(url)
                except Exception:
                    messagebox.showerror("Erreur", f"Impossible d'ouvrir: {url}")
        # create button
        try:
            if tkimg:
                btn = tk.Button(titlebar, image=tkimg, bg=theme_color, bd=0, relief="flat", cursor="hand2", command=_on_click)
                btn.image = tkimg
                _title_button_images.append(tkimg)
            else:
                text = label or (web_target or "Btn")
                btn = tk.Button(titlebar, text=text, bg=theme_color, fg="white", bd=0, relief="flat", cursor="hand2", command=_on_click)
            # pack before the close button if present; we'll pack close after creating these
            btn.pack(side="right", padx=4)
        except Exception:
            pass

    # create all titlebar buttons
    for bdef in app_buttons:
        _create_title_button(bdef)

    # close button
    btn_close = tk.Button(titlebar, text="✕", bg=theme_color, fg="white", bd=0)
    btn_close.pack(side="right", padx=4)

    content_frame = tk.Frame(frame, bg="white")
    content_frame.pack(fill="both", expand=True, padx=8, pady=8)

    win_id = parent_canvas.create_window(x, y, window=frame, anchor="nw", width=default_width, height=default_height)

    def _close():
        try:
            parent_canvas.delete(win_id)
        except Exception:
            pass

    btn_close.config(command=_close)
    _add_local_resizer(parent_canvas, frame, win_id, titlebar, min_w=200, min_h=120)

    # --- Dragging support ---
    _drag_state = {"dragging": False, "start_mouse": (0, 0), "start_pos": (x, y)}
    def _canvas_mouse_to_canvas_coords(evt):
        try:
            mx = parent_canvas.canvasx(evt.x_root - parent_canvas.winfo_rootx())
            my = parent_canvas.canvasy(evt.y_root - parent_canvas.winfo_rooty())
            return mx, my
        except Exception:
            try:
                return parent_canvas.canvasx(evt.x), parent_canvas.canvasy(evt.y)
            except Exception:
                return evt.x, evt.y
    def _on_title_press(evt):
        try:
            parent_canvas.tag_raise(win_id)
            mx, my = _canvas_mouse_to_canvas_coords(evt)
            _drag_state["start_mouse"] = (mx, my)
            coords = parent_canvas.coords(win_id)
            if coords and len(coords) >= 2:
                _drag_state["start_pos"] = (coords[0], coords[1])
            else:
                _drag_state["start_pos"] = (x, y)
            _drag_state["dragging"] = True
        except Exception:
            _drag_state["dragging"] = False
    def _on_title_motion(evt):
        if not _drag_state.get("dragging"):
            return
        try:
            mx, my = _canvas_mouse_to_canvas_coords(evt)
            sx, sy = _drag_state["start_mouse"]
            ox, oy = _drag_state["start_pos"]
            dx = mx - sx
            dy = my - sy
            new_x = int(max(0, ox + dx))
            new_y = int(max(0, oy + dy))
            parent_canvas.coords(win_id, new_x, new_y)
        except Exception:
            pass
    def _on_title_release(evt):
        _drag_state["dragging"] = False
    try:
        titlebar.bind("<ButtonPress-1>", _on_title_press, add="+")
        titlebar.bind("<B1-Motion>", _on_title_motion, add="+")
        titlebar.bind("<ButtonRelease-1>", _on_title_release, add="+")
        titlebar.bind("<Button-1>", lambda e: parent_canvas.tag_raise(win_id), add="+")
    except Exception:
        pass
    # --- end dragging support ---

    # render main content (unchanged)
    if root is not None:
        main = None
        if root.tag.lower() == "dobrian":
            main = root.find("main")
        else:
            main = root.find(".//main")
        if main is not None:
            sc = ScrollableFrame(content_frame, bg="white")
            sc.pack(fill="both", expand=True)
            container = sc.inner
            for child in list(main):
                tag = (child.tag or "").lower()
                def _get_align(el, default="w"):
                    a = (_attr(el, "align") or _attr(el, "alignment") or "").lower()
                    if a in ("center", "c", "middle"):
                        return "center"
                    if a in ("right", "r"):
                        return "e"
                    return default
                def _get_color(el, default="#111"):
                    return _safe_color(_attr(el, "color") or _attr(el, "colour") or None, default)
                def _get_height(el, fallback=None):
                    return _parse_size(_attr(el, "height") or _attr(el, "h"), fallback)
                def _get_width(el, fallback=None):
                    return _parse_size(_attr(el, "width") or _attr(el, "weight") or _attr(el, "w"), fallback)
                if tag == "print":
                    txt = _text(child)
                    color = _get_color(child, "#111")
                    align = _get_align(child, default="w")
                    h = _get_height(child, fallback=None)
                    w_attr = _get_width(child, fallback=None)
                    wrap = (w_attr or default_width) - 40 if isinstance(w_attr, int) else default_width - 40
                    lbl = tk.Label(container, text=txt, bg="white", fg=color, anchor=align, justify="left", wraplength=wrap)
                    if isinstance(h, int):
                        lbl.pack(fill="x", pady=(2,2), ipady=max(0, int(h/6)))
                    else:
                        lbl.pack(fill="x", pady=4, anchor="w")
                elif tag == "custom":
                    for c in list(child):
                        ctag = (c.tag or "").lower()
                        if ctag == "line":
                            color = "#444444"
                            align = "w"
                            h = None
                            w_attr = None
                            for d in list(c):
                                if (d.tag or "").lower() == "def":
                                    color = _safe_color(_attr(d, "color") or _text(d) or color)
                                    align = _get_align(d, default="w")
                                    h = _get_height(d, fallback=None)
                                    w_attr = _get_width(d, fallback=None)
                            line_canvas = tk.Canvas(container, height=(h if isinstance(h, int) else 8), bg="white", highlightthickness=0)
                            line_canvas.pack(fill="x", pady=8)
                            try:
                                wdraw = (w_attr if isinstance(w_attr, int) else max(10, default_width - 40))
                                if align == "center":
                                    x0 = (default_width - wdraw) // 2
                                    line_canvas.create_line(x0+6, (h if isinstance(h, int) else 4), x0 + wdraw, (h if isinstance(h, int) else 4), fill=color, width=4, capstyle="round")
                                else:
                                    line_canvas.create_line(6, (h if isinstance(h, int) else 4), wdraw, (h if isinstance(h, int) else 4), fill=color, width=4, capstyle="round")
                            except Exception:
                                pass
                        else:
                            txt = _text(c)
                            if txt:
                                lbl = tk.Label(container, text=txt, bg="white", fg="#333", anchor="w", justify="left", wraplength=default_width-40)
                                lbl.pack(fill="x", pady=2, anchor="w")
                elif tag == "img":
                    p = _attr(child, "path") or _text(child)
                    resolved = _resolve_sandbox_path(p)
                    h = _get_height(child, fallback=None)
                    w_attr = _get_width(child, fallback=None)
                    if resolved and os.path.exists(resolved):
                        try:
                            if PIL:
                                img = Image.open(resolved).convert("RGBA")
                                max_w = w_attr if isinstance(w_attr, int) else max(40, default_width - 80)
                                max_h = h if isinstance(h, int) else 240
                                img.thumbnail((max_w, max_h), Image.LANCZOS)
                                tkimg = ImageTk.PhotoImage(img)
                                lbl = tk.Label(container, image=tkimg, bg="white")
                                lbl.image = tkimg
                                lbl.pack(pady=6)
                            else:
                                tkimg = tk.PhotoImage(file=resolved)
                                lbl = tk.Label(container, image=tkimg, bg="white")
                                lbl.image = tkimg
                                lbl.pack(pady=6)
                        except Exception:
                            lbl = tk.Label(container, text=f"[Image erreur: {os.path.basename(resolved)}]", bg="white", fg="#a00")
                            lbl.pack(pady=4)
                    else:
                        lbl = tk.Label(container, text=f"[Image introuvable: {p}]", bg="white", fg="#a00")
                        lbl.pack(pady=4)
                elif tag == "link":
                    ltype = (_attr(child, "type") or "web").lower()
                    lpath = _attr(child, "path") or _text(child)
                    display = _attr(child, "label") or lpath
                    if ltype == "web":
                        def _open_web(url=lpath):
                            try:
                                webbrowser.open(url)
                            except Exception:
                                messagebox.showerror("Erreur", f"Impossible d'ouvrir le lien: {url}")
                        btn = tk.Button(container, text=f"🔗 {display}", anchor="w", relief="flat", bg="white", fg="#0b6cff", cursor="hand2", command=_open_web)
                        btn.pack(fill="x", pady=4, anchor="w")
                    elif ltype == "file":
                        resolved = _resolve_sandbox_path(lpath)
                        def _open_file(res=resolved, label=display):
                            if not res or not os.path.exists(res):
                                messagebox.showerror("Fichier introuvable", f"{label} introuvable.")
                                return
                            _open_file_popup(parent_canvas.master if hasattr(parent_canvas, "master") else container, res, title=display, icon_photo=app_icon_photo)
                        btn = tk.Button(container, text=f"📄 {display}", anchor="w", relief="flat", bg="white", fg="#0b6cff", cursor="hand2", command=_open_file)
                        btn.pack(fill="x", pady=4, anchor="w")
                    else:
                        lbl = tk.Label(container, text=f"[Lien: {display} ({ltype})]", bg="white", fg="#333", anchor="w", justify="left", wraplength=default_width-40)
                        lbl.pack(fill="x", pady=4, anchor="w")
                elif tag == "explorer":
                    etype = (_attr(child, "type") or "file").lower()
                    secure = _attr(child, "secure", "").lower() in ("1", "true", "yes")
                    env_name = _attr(child, "env")
                    base_dir = SANDBOX_ROOT
                    if env_name:
                        base_dir = create_isolated_env(env_name) or base_dir
                    if etype == "file":
                        open_ext = (_attr(child, "open") or _text(child) or "").lstrip(".").lower()
                        box = tk.Frame(container, bg="#f7f7f7", bd=1, relief="solid")
                        title = f"Explorer: fichiers .{open_ext}"
                        if env_name:
                            title += f" (env {env_name})"
                        tk.Label(box, text=title, bg="#f7f7f7").pack(anchor="w", padx=6, pady=(4,2))
                        listbox = tk.Listbox(box, height=6)
                        listbox.pack(fill="both", expand=True, padx=6, pady=(0,6))
                        authenticated = not secure
                        def try_auth():
                            nonlocal authenticated
                            if authenticated:
                                return True
                            creds = authenticate_sync(parent_canvas=parent_canvas)
                            if creds is None:
                                messagebox.showerror("Authentification", "Accès refusé.")
                                return False
                            authenticated = True
                            return True
                        def refresh_list():
                            listbox.delete(0, "end")
                            files_list = _list_files_with_ext(open_ext, base=base_dir) if open_ext else []
                            for fp in files_list:
                                listbox.insert("end", os.path.relpath(fp, base_dir))
                            return files_list
                        files = []
                        if not secure or try_auth():
                            files = refresh_list()
                        def _on_open_selected(evt=None, lb=listbox, files_list_ref=lambda: files):
                            if secure and not authenticated and not try_auth():
                                return
                            sel = lb.curselection()
                            if not sel:
                                return
                            idx = sel[0]
                            fp = files_list_ref()[idx]
                            if env_name:
                                _edit_file_popup(parent_canvas.master if hasattr(parent_canvas, "master") else container, fp, title=os.path.basename(fp), icon_photo=app_icon_photo)
                            else:
                                _open_file_popup(parent_canvas.master if hasattr(parent_canvas, "master") else container, fp, title=os.path.basename(fp), icon_photo=app_icon_photo)
                        def _on_delete_selected(lb=listbox, files_list_ref=lambda: files):
                            sel = lb.curselection()
                            if not sel:
                                return
                            idx = sel[0]
                            fp = files_list_ref()[idx]
                            if messagebox.askyesno("Supprimer", f"Supprimer {os.path.basename(fp)} ?"):
                                try:
                                    os.remove(fp)
                                except Exception:
                                    pass
                                refresh_list()
                        def _create_new():
                            name = tk.simpledialog.askstring("Nouveau fichier", "Nom du fichier :", parent=parent_canvas.master if hasattr(parent_canvas, "master") else container)
                            if not name:
                                return
                            dst = os.path.join(base_dir, name)
                            try:
                                with open(dst, "w", encoding="utf-8"):
                                    pass
                            except Exception:
                                messagebox.showerror("Erreur", "Impossible de créer le fichier.")
                            refresh_list()
                        btn_row = tk.Frame(box, bg="#f7f7f7")
                        btn_row.pack(fill="x", padx=6, pady=(0,6))
                        tk.Button(btn_row, text="Ouvrir", command=_on_open_selected).pack(side="left", padx=4)
                        if env_name:
                            tk.Button(btn_row, text="Supprimer", command=_on_delete_selected).pack(side="left", padx=4)
                            tk.Button(btn_row, text="Nouveau", command=_create_new).pack(side="left", padx=4)
                        tk.Button(btn_row, text="Rafraîchir", command=lambda: refresh_list()).pack(side="left", padx=4)
                        if secure:
                            tk.Button(btn_row, text="Se connecter", command=lambda: (try_auth() and refresh_list())).pack(side="right", padx=4)
                        box.pack(fill="x", pady=6)
                    else:
                        lbl = tk.Label(container, text=f"[Explorer type {etype} non pris en charge]", bg="white", fg="#666")
                        lbl.pack(fill="x", pady=4)
                else:
                    txt = _text(child)
                    if txt:
                        lbl = tk.Label(container, text=txt, bg="white", fg="#333", anchor="w", justify="left", wraplength=default_width-40)
                        lbl.pack(fill="x", pady=2, anchor="w")
        else:
            tk.Label(content_frame, text="(Aucune section <main> trouvée dans l'application)", bg="white", fg="#666").pack(pady=8)
    else:
        tk.Label(content_frame, text="(Impossible d'analyser le fichier .dbn)", bg="white", fg="#a00").pack(pady=8)

    win_dict = {
        "id": win_id,
        "title": app_name,
        "bring_to_front": lambda: parent_canvas.tag_raise(win_id),
        "close": _close,
        "frame": frame,
        "titlebar": titlebar,
        "path": path
    }
    if callable(register_callback):
        try:
            register_callback(win_dict)
        except Exception:
            pass
    return win_dict
