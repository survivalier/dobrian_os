#!/usr/bin/env python3
# data/notpad.py
# Simple notepad window for editing files outside the file manager

import os
import tkinter as tk
from tkinter import messagebox, filedialog

class NotepadWindow:
    """Standalone editor window. Supports internal or toplevel mode."""

    def __init__(self,
                 parent_canvas=None,
                 parent_toplevel=None,
                 x=100, y=100,
                 width=600, height=400,
                 internal=True,
                 path=None):
        self.internal = internal
        self.path = path
        self._text_ref = None

        if internal:
            if parent_canvas is None:
                raise ValueError("parent_canvas required for internal=True")
            self.canvas = parent_canvas
            self.frame = tk.Frame(self.canvas, bd=2, relief="raised")
            self.frame.pack_propagate(False)
            self.window_id = self.canvas.create_window(x, y, window=self.frame,
                                                       anchor="nw", width=width, height=height)
            # titlebar with close
            self.titlebar = tk.Frame(self.frame, bg="#cccccc", height=24)
            self.titlebar.pack(fill="x", side="top")
            tk.Label(self.titlebar, text=f"Notepad - {os.path.basename(path) if path else ''}",
                     bg="#cccccc").pack(side="left", padx=4)
            tk.Button(self.titlebar, text="✕", bg="#cccccc", bd=0,
                      command=self.close).pack(side="right", padx=4)
            self.content = tk.Frame(self.frame)
            self.content.pack(fill="both", expand=True)
        else:
            self.win = tk.Toplevel(parent_toplevel)
            self.win.title(f"Notepad - {os.path.basename(path) if path else ''}")
            self.content = tk.Frame(self.win)
            self.content.pack(fill="both", expand=True)

        self._build_ui()
        if path:
            self._load_file(path)

    def _build_ui(self):
        self.text = tk.Text(self.content, wrap="none")
        self.text.pack(fill="both", expand=True)
        btns = tk.Frame(self.content)
        btns.pack(fill="x")
        tk.Button(btns, text="Save", command=self.save).pack(side="left", padx=4, pady=4)
        tk.Button(btns, text="Close", command=self.close).pack(side="left", padx=4, pady=4)

    def _load_file(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = f.read()
            self.text.delete("1.0", "end")
            self.text.insert("1.0", data)
        except Exception as e:
            messagebox.showerror("Error", f"Cannot load file: {e}")

    def save(self):
        if not self.path:
            path = filedialog.asksaveasfilename()
            if not path:
                return
            self.path = path
        try:
            data = self.text.get("1.0", "end")
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(data)
            messagebox.showinfo("Saved", "File saved.")
        except Exception as e:
            messagebox.showerror("Error", f"Cannot save file: {e}")

    def close(self):
        try:
            if self.internal:
                self.canvas.delete(self.window_id)
            else:
                self.win.destroy()
        except Exception:
            pass
