#!/usr/bin/env python3
# terminal.py
# TerminalWindow : terminal exécutable, utilisable en interne (canvas) ou en Toplevel.
# Usage:
#   from terminal import TerminalWindow
#   # interne:
#   TerminalWindow(parent_canvas=canvas, x=100, y=100, width=700, height=380, username="nathan", internal=True)
#   # toplevel:
#   TerminalWindow(parent_toplevel=root, username="nathan", internal=False)

import os
import json
import hashlib
import tkinter as tk
from datetime import datetime
import subprocess
import threading
import shlex
import signal

# helpers for virtual environments (defined in data/code.py)
from data.code import ENV_ROOT, create_isolated_env
# ensure env root directory exists in case code module hasn't run it yet
os.makedirs(ENV_ROOT, exist_ok=True)

# Path to accounts file (assumes terminal.py lives in data/ alongside dobrian_accounts.json)
ACCOUNTS_FILE = os.path.join(os.path.dirname(__file__), "dobrian_accounts.json")
# Home root for cd command
HOME_ROOT = os.path.join(os.path.dirname(__file__), "file.dobrian", "home")
os.makedirs(HOME_ROOT, exist_ok=True)


def _hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def _load_accounts():
    try:
        if os.path.exists(ACCOUNTS_FILE):
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_accounts(accounts: dict):
    try:
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2)
    except Exception:
        pass


class TerminalWindow:
    """
    TerminalWindow(parent_canvas=..., parent_toplevel=..., x=80, y=80, width=700, height=380,
                   username='user', internal=True, title='Terminal')

    - internal True  -> crée une fenêtre interne sur un Canvas (parent_canvas required)
    - internal False -> crée un Toplevel (parent_toplevel required)
    """

    def __init__(self,
                 parent_canvas=None,
                 parent_toplevel=None,
                 x=80, y=80,
                 width=700, height=380,
                 username="user",
                 internal=True,
                 title="Terminal"):
        self.username = username
        self.internal = internal
        self._proc_lock = threading.Lock()
        self._current_proc = None
        self._history = []
        self._hist_index = None

        # current working directory for cd command (restricted to HOME_ROOT)
        self._cwd = HOME_ROOT

        if internal:
            if parent_canvas is None:
                raise ValueError("parent_canvas requis pour internal=True")
            self.canvas = parent_canvas

            # Frame conteneur fixe (empêche le contenu d'être agrandi par le canvas)
            self.frame = tk.Frame(self.canvas, bd=2, relief="raised", bg="white")
            self.frame.pack_propagate(False)

            # Titlebar (drag)
            self.titlebar = tk.Frame(self.frame, bg="#2f2f2f", height=28)
            self.titlebar.pack(fill="x", side="top")
            self.title_label = tk.Label(self.titlebar, text=title, fg="white", bg="#2f2f2f")
            self.title_label.pack(side="left", padx=6)
            self.btn_close = tk.Button(self.titlebar, text="✕", bg="#2f2f2f", fg="white", bd=0, command=self.close)
            self.btn_close.pack(side="right", padx=4)

            # Content area
            self.content = tk.Frame(self.frame, bg="white")
            self.content.pack(fill="both", expand=True)

            # Place the frame on the canvas with fixed width/height
            self.window_id = self.canvas.create_window(x, y, window=self.frame, anchor="nw", width=width, height=height)

            # Drag support
            self._drag = {"start_x":0, "start_y":0, "orig_x":x, "orig_y":y, "w":width, "h":height}
            for w in (self.titlebar, self.title_label):
                w.bind("<ButtonPress-1>", self._on_press)
                w.bind("<B1-Motion>", self._on_motion)
                w.bind("<ButtonRelease-1>", self._on_release)
            self.frame.bind("<Button-1>", lambda e: self.bring_to_front())
        else:
            if parent_toplevel is None:
                raise ValueError("parent_toplevel requis pour internal=False")
            self.win = tk.Toplevel(parent_toplevel)
            self.win.title(title)
            self.frame = tk.Frame(self.win, bg="white")
            self.frame.pack(fill="both", expand=True)
            self.content = self.frame

        # Build UI inside self.content
        self._build_ui()

        # internal state used when asking for admin password
        self._awaiting_admin = None  # dict holding {'cmd':opt,'args':[..]} when waiting for pwd
        # shutdown callback
        # shutdown callback removed
        self.on_shutdown = None

        # Ensure entry gets focus after mapping
        try:
            self.content.after_idle(lambda: self._ensure_focus())
        except Exception:
            pass

    # --- drag handlers (internal) ---
    def _on_press(self, event):
        self.bring_to_front()
        cx = self.canvas.canvasx(event.x_root - self.canvas.winfo_rootx())
        cy = self.canvas.canvasy(event.y_root - self.canvas.winfo_rooty())
        coords = self.canvas.coords(self.window_id)
        self._drag["start_x"] = cx
        self._drag["start_y"] = cy
        self._drag["orig_x"] = coords[0]
        self._drag["orig_y"] = coords[1]

    def _on_motion(self, event):
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

    def _on_release(self, event):
        pass

    def bring_to_front(self):
        if self.internal:
            try:
                self.canvas.tag_raise(self.window_id)
            except Exception:
                pass
        else:
            try:
                self.win.lift()
            except Exception:
                pass

    # --- UI build ---
    def _build_ui(self):
        # Use grid so bottom entry keeps fixed height and text expands
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=0)
        self.content.grid_columnconfigure(0, weight=1)

        # Text output (read-only)
        self.text = tk.Text(self.content, bg="black", fg="white", insertbackground="white", wrap="word")
        self.text.grid(row=0, column=0, sticky="nsew", padx=4, pady=(4,2))
        # prevent user edits by default
        self.text.config(state="disabled")
        # bind any keypress inside the text widget to ignore it
        self.text.bind("<Key>", lambda e: "break")

        # Configure tags: prompt (blue dark), err (red dark), out (white)
        self.text.tag_configure("prompt", foreground="#0b3d91")
        self.text.tag_configure("err", foreground="#8b0000")
        self.text.tag_configure("out", foreground="#ffffff")

        # Bottom frame with prompt label and entry
        bottom = tk.Frame(self.content, bg="#111")
        bottom.grid(row=1, column=0, sticky="ew", padx=4, pady=(2,4))
        bottom.grid_columnconfigure(1, weight=1)

        # initialize prompt label (will be updated to include cwd)
        self.prompt_str = ""
        self.prompt_label = tk.Label(bottom, text="", fg="#0b3d91", bg="#111", font=("Courier", 10, "bold"))
        self.prompt_label.grid(row=0, column=0, padx=(6,8), pady=6)

        self.entry_var = tk.StringVar()
        self.entry = tk.Entry(bottom, textvariable=self.entry_var, bg="#222", fg="white", insertbackground="white",
                              font=("Courier", 10))
        self.entry.grid(row=0, column=1, sticky="ew", padx=(0,6), pady=6)

        # Bindings
        self.entry.bind("<Return>", self._on_enter)
        self.entry.bind("<Up>", self._history_up)
        self.entry.bind("<Down>", self._history_down)
        self.entry.bind("<Control-c>", self._ctrl_c)
        self.content.bind("<Button-1>", lambda e: self.entry.focus_set())

        # set initial prompt to reflect cwd
        self._update_prompt_label()

        # Welcome message
        self._print("Dobrian Terminal - tapez 'help' pour la liste des commandes.")
        self._print("")

    # --- update prompt label to include current directory relative to HOME_ROOT ---
    def _update_prompt_label(self):
        try:
            rel = os.path.relpath(self._cwd, HOME_ROOT)
            if rel in (".", ""):
                path_display = "/"
            else:
                path_display = "/" + rel.replace(os.sep, "/")
            self.prompt_str = f"{self.username}@dobrian{path_display} >"
            try:
                self.prompt_label.config(text=self.prompt_str)
            except Exception:
                pass
        except Exception:
            # fallback to simple prompt
            self.prompt_str = f"{self.username}@dobrian >"
            try:
                self.prompt_label.config(text=self.prompt_str)
            except Exception:
                pass

    # --- printing helpers ---
    def _print(self, s="", tag=None):
        # enable widget temporarily to insert text, then disable again
        try:
            self.text.config(state="normal")
            if tag == "prompt":
                self.text.insert("end", s + "\n", ("prompt",))
            elif tag == "err":
                self.text.insert("end", s + "\n", ("err",))
            elif tag == "out":
                self.text.insert("end", s + "\n", ("out",))
            else:
                self.text.insert("end", s + "\n")
            self.text.see("end")
        except Exception:
            pass
        finally:
            try:
                self.text.config(state="disabled")
            except Exception:
                pass

    # --- history helpers ---
    def _record_history(self, cmd):
        if not cmd:
            return
        if not self._history or self._history[-1] != cmd:
            self._history.append(cmd)
        self._hist_index = None

    def _history_up(self, event):
        if not self._history:
            return "break"
        if self._hist_index is None:
            self._hist_index = len(self._history) - 1
        else:
            self._hist_index = max(0, self._hist_index - 1)
        self.entry_var.set(self._history[self._hist_index])
        self.entry.icursor("end")
        return "break"

    def _history_down(self, event):
        if not self._history or self._hist_index is None:
            self.entry_var.set("")
            return "break"
        self._hist_index = min(len(self._history) - 1, self._hist_index + 1)
        if self._hist_index >= len(self._history):
            self.entry_var.set("")
            self._hist_index = None
        else:
            self.entry_var.set(self._history[self._hist_index])
        self.entry.icursor("end")
        return "break"

    # --- Ctrl+C handler ---
    def _ctrl_c(self, event):
        with self._proc_lock:
            proc = self._current_proc
        if proc and proc.poll() is None:
            try:
                proc.send_signal(signal.SIGINT)
                self._print(f"[{self.prompt_str}] Processus interrompu.", tag="prompt")
            except Exception:
                try:
                    proc.terminate()
                    self._print(f"[{self.prompt_str}] Processus terminé.", tag="prompt")
                except Exception as e:
                    self._print(f"[{self.prompt_str}] Impossible d'interrompre: {e}", tag="err")
        else:
            self.entry_var.set("")
        return "break"

    # --- run command thread ---
    def _run_command_thread(self, cmd_args):
        try:
            proc = subprocess.Popen(cmd_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
            with self._proc_lock:
                self._current_proc = proc

            def reader(stream, is_err=False):
                try:
                    for line in iter(stream.readline, ""):
                        if not line:
                            break
                        line = line.rstrip("\n")
                        if is_err:
                            self._print(line, tag="err")
                        else:
                            self._print(line, tag="out")
                except Exception:
                    pass

            t_out = threading.Thread(target=reader, args=(proc.stdout, False))
            t_err = threading.Thread(target=reader, args=(proc.stderr, True))
            t_out.daemon = True
            t_err.daemon = True
            t_out.start()
            t_err.start()

            proc.wait()
            t_out.join(timeout=0.1)
            t_err.join(timeout=0.1)
            exit_code = proc.returncode
            self._print(f"[{self.prompt_str}] Processus terminé (code {exit_code})", tag="prompt")
        except FileNotFoundError:
            self._print(f"Commande introuvable: {cmd_args[0]}", tag="err")
        except Exception as e:
            self._print(f"Erreur exécution: {e}", tag="err")
        finally:
            with self._proc_lock:
                self._current_proc = None

    # --- helper: safe path join within HOME_ROOT ---
    def _resolve_path_within_home(self, path_fragment: str) -> str:
        """
        Resolve a path fragment relative to current cwd or HOME_ROOT.
        Ensure the resulting path is inside HOME_ROOT.
        """
        if not path_fragment:
            return self._cwd
        # If user provided an absolute-like path starting with '/', treat it relative to HOME_ROOT
        if os.path.isabs(path_fragment):
            candidate = os.path.normpath(os.path.join(HOME_ROOT, path_fragment.lstrip(os.sep)))
        else:
            candidate = os.path.normpath(os.path.join(self._cwd, path_fragment))
        try:
            # Ensure candidate is within HOME_ROOT
            common = os.path.commonpath([HOME_ROOT, candidate])
            if common != os.path.normpath(HOME_ROOT):
                return None
            return candidate
        except Exception:
            return None

    # --- cd command implementation ---
    def _cmd_cd(self, args):
        """
        cd:
          - cd                -> list contents of current directory
          - cd -help          -> show usage
          - cd <path>         -> change directory (relative to current cwd or HOME_ROOT)
        """
        if not args:
            # list current directory
            try:
                entries = sorted(os.listdir(self._cwd))
                display_dir = os.path.relpath(self._cwd, HOME_ROOT)
                display_dir = "/" if display_dir in (".", "") else "/" + display_dir.replace(os.sep, "/")
                if not entries:
                    self._print(f"Dossier {display_dir} vide", tag="out")
                    return
                for e in entries:
                    p = os.path.join(self._cwd, e)
                    if os.path.isdir(p):
                        self._print(f"[DIR]  {e}", tag="out")
                    else:
                        self._print(f"      {e}", tag="out")
            except Exception as e:
                self._print(f"Erreur lecture répertoire: {e}", tag="err")
            return

        if args[0] in ("-help", "--help", "help"):
            self._print("Usage: cd [chemin]")
            self._print("  Sans argument: liste le contenu du répertoire courant.")
            self._print("  cd <chemin>: change le répertoire courant (racine: /file.dobrian/home/).")
            self._print("  Les chemins absolus sont interprétés depuis /file.dobrian/home/.")
            return

        target_fragment = args[0]
        new_path = self._resolve_path_within_home(target_fragment)
        if new_path is None:
            self._print("Chemin invalide ou en dehors de /file.dobrian/home/ interdit.", tag="err")
            return
        if not os.path.exists(new_path):
            self._print(f"Répertoire introuvable: {target_fragment}", tag="err")
            return
        if not os.path.isdir(new_path):
            self._print(f"Ce n'est pas un répertoire: {target_fragment}", tag="err")
            return
        # success: change cwd
        self._cwd = new_path
        # update prompt to include new directory
        self._update_prompt_label()
        # show a friendly message with the new directory
        rel = os.path.relpath(self._cwd, HOME_ROOT)
        display_dir = "/" if rel in (".", "") else "/" + rel.replace(os.sep, "/")
        self._print(f"Répertoire courant: {display_dir}", tag="out")

    # --- enter handler ---
    def _on_enter(self, event):
        cmdline = self.entry_var.get().strip()
        self.entry_var.set("")
        # print prompt + command in output (prompt tag)
        self._print(f"{self.prompt_str} {cmdline}", tag="prompt")
        self._record_history(cmdline)
        if not cmdline:
            self.entry.focus_set()
            return "break"

        parts = cmdline.split()
        cmd = parts[0].lower()
        args = parts[1:]
        # first check if we're awaiting admin password
        if self._awaiting_admin is not None:
            pwd = cmdline
            # restore entry echo
            self.entry.config(show="")
            pending = self._awaiting_admin
            self._awaiting_admin = None
            # if pending cmd _become_root
            if pending.get("cmd") == "_become_root":
                accounts = {}
                try:
                    accounts = _load_accounts()
                except Exception:
                    pass
                if accounts.get("root") == _hash_password(pwd):
                    self.username = "root"
                    self._print("Connexion en root réussie.", tag="out")
                else:
                    self._print("Mot de passe root invalide.", tag="err")
                self.entry.focus_set()
                return "break"
            # verify credentials against current user
            accounts = {}
            try:
                accounts = _load_accounts()
            except Exception:
                pass
            if not (self.username in accounts and accounts.get(self.username) == _hash_password(pwd)):
                self._print("Identifiants invalides.", tag="err")
                self.entry.focus_set()
                return "break"
            # authentication succeeded, perform the pending operation now
            opt = pending.get("cmd")
            pargs = pending.get("args", [])
            if opt == "-add":
                if self.username != "root":
                    self._print("seul root peut ajouter des utilisateurs", tag="err")
                elif len(pargs) < 2:
                    self._print("Usage: user -add <username> <password>", tag="err")
                else:
                    uname = pargs[0]
                    pw = pargs[1]
                    try:
                        accs = _load_accounts()
                        if uname in accs:
                            self._print(f"Utilisateur '{uname}' existe déjà.", tag="err")
                        else:
                            accs[uname] = _hash_password(pw)
                            _save_accounts(accs)
                            self._print(f"Utilisateur '{uname}' ajouté.", tag="out")
                    except Exception as e:
                        self._print(f"Erreur ajout utilisateur: {e}", tag="err")
            elif opt == "-delete":
                if self.username != "root":
                    self._print("seul root peut supprimer des utilisateurs", tag="err")
                elif len(pargs) < 1:
                    self._print("Usage: user -delete <username>", tag="err")
                else:
                    uname = pargs[0]
                    try:
                        accs = _load_accounts()
                        if uname not in accs:
                            self._print(f"Utilisateur '{uname}' introuvable.", tag="err")
                        else:
                            del accs[uname]
                            _save_accounts(accs)
                            self._print(f"Utilisateur '{uname}' supprimé.", tag="out")
                    except Exception as e:
                        self._print(f"Erreur suppression utilisateur: {e}", tag="err")
            self.entry.focus_set()
            return "break"
        # builtins
        if cmd == "help":
            cmds = ["help","clear","echo","time","user","cd","exit","whoami",
                    "pwd","ls","root","date","env","calc"]
            if self.username == "root":
                cmds += ["shutdown","venv-create","venv-list","venv-remove"]
            self._print("Commandes disponibles: " + ", ".join(cmds))
            self.entry.focus_set()
            return "break"
        if cmd == "clear":
            try:
                self.text.config(state="normal")
                self.text.delete("1.0", "end")
            except Exception:
                pass
            finally:
                try:
                    self.text.config(state="disabled")
                except Exception:
                    pass
            self.entry.focus_set()
            return "break"
        if cmd == "exit":
            # simply close this terminal
            self.close()
            return "break"
        if cmd == "root":
            # attempt to login as root
            self._print("Mot de passe root :", tag="prompt")
            self._awaiting_admin = {"cmd":"_become_root"}
            self.entry_var.set("")
            self.entry.config(show="*")
            self.entry.focus_set()
            return "break"
        if cmd == "shutdown" and self.username == "root":
            self._print("Arrêt du système (simulé)", tag="prompt")
            self.close()
            return "break"
        if cmd == "echo":
            self._print(" ".join(args), tag="out")
            self.entry.focus_set()
            return "break"
        if cmd == "whoami":
            self._print(self.username, tag="out")
            self.entry.focus_set()
            return "break"
        if cmd == "ls":
            try:
                entries = sorted(os.listdir(self._cwd))
                for e in entries:
                    self._print(e, tag="out")
            except Exception as e:
                self._print(f"Erreur ls: {e}", tag="err")
            self.entry.focus_set()
            return "break"
        # root-specific venv commands
        if self.username == "root":
            if cmd == "venv-create":
                if not args:
                    self._print("Usage: venv-create <name>", tag="err")
                else:
                    name = args[0]
                    try:
                        path = create_isolated_env(name)
                        self._print(f"Environnement créé: {path}", tag="out")
                    except Exception as e:
                        self._print(f"Erreur création venv: {e}", tag="err")
                self.entry.focus_set()
                return "break"
            if cmd == "venv-list":
                try:
                    rootdir = ENV_ROOT
                    items = os.listdir(rootdir)
                    for i in items:
                        self._print(i, tag="out")
                except Exception as e:
                    self._print(f"Erreur list venv: {e}", tag="err")
                self.entry.focus_set()
                return "break"
            if cmd == "venv-remove":
                if not args:
                    self._print("Usage: venv-remove <name>", tag="err")
                else:
                    name = args[0]
                    try:
                        import shutil
                        shutil.rmtree(os.path.join(ENV_ROOT, name))
                        self._print(f"Environnement {name} supprimé", tag="out")
                    except Exception as e:
                        self._print(f"Erreur suppression venv: {e}", tag="err")
                self.entry.focus_set()
                return "break"
        if cmd == "time":
            # print date and time
            try:
                now = datetime.now().strftime("%c")
                self._print(now, tag="out")
            except Exception as e:
                self._print(f"Erreur time: {e}", tag="err")
            self.entry.focus_set()
            return "break"
        if cmd == "date":
            now = datetime.now().strftime("%c")
            self._print(now, tag="out")
            self.entry.focus_set()
            return "break"
        if cmd == "env":
            for k,v in sorted(os.environ.items()):
                self._print(f"{k}={v}", tag="out")
            self.entry.focus_set()
            return "break"
        if cmd == "calc":
            # simple arithmetic evaluation
            try:
                expr = " ".join(args)
                res = eval(expr, { }, { })
                self._print(str(res), tag="out")
            except Exception as e:
                self._print(f"Erreur calc: {e}", tag="err")
            self.entry.focus_set()
            return "break"
        # --- user management command ---
        if cmd == "user":
            # user -help
            if not args or args[0] in ("-help", "--help", "help"):
                self._print("Usage: user [option] [arguments]")
                self._print("Options:")
                self._print("  user -help                     Affiche cette aide")
                self._print("  user -add <username> <password>  Ajoute un utilisateur (mot de passe stocké en hash)")
                self._print("  user -show                     Affiche la liste des utilisateurs")
                self._print("  user -delete <username>        Supprime l'utilisateur")
                self.entry.focus_set()
                return "break"

            opt = args[0].lower()

                # for add/delete require admin password, handle inline
            if opt in ("-add", "-delete"):
                # ask for password in the terminal itself
                self._print("Commande administrateur, veuillez entrez-vôtre mot-de-passe:", tag="prompt")
                # store pending operation and switch entry to password mode
                self._awaiting_admin = {"cmd": opt, "args": args[1:]}
                self.entry_var.set("")
                self.entry.config(show="*")
                self.entry.focus_set()
                return "break"

            if opt == "-add":
                if len(args) < 3:
                    self._print("Usage: user -add <username> <password>", tag="err")
                    self.entry.focus_set()
                    return "break"
                uname = args[1]
                pw = args[2]
                try:
                    accounts = _load_accounts()
                    if uname in accounts:
                        self._print(f"Utilisateur '{uname}' existe déjà.", tag="err")
                        self.entry.focus_set()
                        return "break"
                    accounts[uname] = _hash_password(pw)
                    _save_accounts(accounts)
                    self._print(f"Utilisateur '{uname}' ajouté.", tag="out")
                except Exception as e:
                    self._print(f"Erreur ajout utilisateur: {e}", tag="err")
                self.entry.focus_set()
                return "break"

            if opt == "-show":
                try:
                    accounts = _load_accounts()
                    if not accounts:
                        self._print("Aucun utilisateur trouvé.", tag="out")
                    else:
                        self._print("Utilisateurs :", tag="out")
                        for u in sorted(accounts.keys()):
                            self._print(f"  - {u}", tag="out")
                except Exception as e:
                    self._print(f"Erreur lecture utilisateurs: {e}", tag="err")
                self.entry.focus_set()
                return "break"

            if opt == "-delete":
                if len(args) < 2:
                    self._print("Usage: user -delete <username>", tag="err")
                    self.entry.focus_set()
                    return "break"
                uname = args[1]
                try:
                    accounts = _load_accounts()
                    if uname not in accounts:
                        self._print(f"Utilisateur '{uname}' introuvable.", tag="err")
                        self.entry.focus_set()
                        return "break"
                    del accounts[uname]
                    _save_accounts(accounts)
                    self._print(f"Utilisateur '{uname}' supprimé.", tag="out")
                except Exception as e:
                    self._print(f"Erreur suppression utilisateur: {e}", tag="err")
                self.entry.focus_set()
                return "break"

            # unknown option
            self._print(f"Option inconnue pour 'user': {' '.join(args)}", tag="err")
            self._print("Tapez 'user -help' pour l'aide.", tag="err")
            self.entry.focus_set()
            return "break"

        # --- cd command ---
        if cmd == "cd":
            try:
                self._cmd_cd(args)
            except Exception as e:
                self._print(f"Erreur cd: {e}", tag="err")
            self.entry.focus_set()
            return "break"

        # execute real command (spawned in current working directory)
        try:
            cmd_args = shlex.split(cmdline)
        except Exception:
            cmd_args = cmdline.split()

        def run_in_cwd(args_list):
            try:
                proc = subprocess.Popen(args_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, cwd=self._cwd)
                with self._proc_lock:
                    self._current_proc = proc

                def reader(stream, is_err=False):
                    try:
                        for line in iter(stream.readline, ""):
                            if not line:
                                break
                            line = line.rstrip("\n")
                            if is_err:
                                self._print(line, tag="err")
                            else:
                                self._print(line, tag="out")
                    except Exception:
                        pass

                t_out = threading.Thread(target=reader, args=(proc.stdout, False))
                t_err = threading.Thread(target=reader, args=(proc.stderr, True))
                t_out.daemon = True
                t_err.daemon = True
                t_out.start()
                t_err.start()

                proc.wait()
                t_out.join(timeout=0.1)
                t_err.join(timeout=0.1)
                exit_code = proc.returncode
                self._print(f"[{self.prompt_str}] Processus terminé (code {exit_code})", tag="prompt")
            except FileNotFoundError:
                self._print(f"Commande introuvable: {args_list[0]}", tag="err")
            except Exception as e:
                self._print(f"Erreur exécution: {e}", tag="err")
            finally:
                with self._proc_lock:
                    self._current_proc = None

        th = threading.Thread(target=run_in_cwd, args=(cmd_args,))
        th.daemon = True
        th.start()
        self.entry.focus_set()
        return "break"

    # --- ensure focus ---
    def _ensure_focus(self):
        try:
            self.entry.focus_set()
            self.entry.focus_force()
        except Exception:
            pass

    # --- close ---
    def close(self):
        with self._proc_lock:
            proc = self._current_proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            if self.internal:
                self.canvas.delete(self.window_id)
            else:
                self.win.destroy()
        except Exception:
            pass
