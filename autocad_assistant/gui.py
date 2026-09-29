"""Fenêtre de dialogue (tkinter) : on écrit, l'assistant dessine."""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from tkinter import scrolledtext
from typing import Callable

from .agent import DrawingAssistant
from .backends import DrawingBackend
from .profiles import ProfileLibrary

WELCOME = (
    "Bonjour ! Décrivez ce que vous voulez dessiner, par exemple :\n"
    "  • « Dessine une pièce de 4 m sur 3 m avec des murs de 20 cm et cote-la »\n"
    "  • « Ajoute une porte de 90 cm au milieu du mur du bas »\n"
    "  • « Une platine 200×150 avec 4 trous Ø12 à 20 mm des bords »\n"
    "  • « Ajoute le cartouche en A3, plan n° 12, client Dupont »\n"
)


class ChatWindow:
    def __init__(self, make_backend: Callable[[], DrawingBackend], model: str,
                 library: ProfileLibrary | None = None, company: dict | None = None) -> None:
        self.library = library
        self.company = company
        self.root = tk.Tk()
        self.root.title("Assistant de dessin AutoCAD")
        self.root.geometry("620x680")
        self.root.attributes("-topmost", True)  # reste visible au-dessus d'AutoCAD

        self.log = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, state=tk.DISABLED,
                                             font=("Segoe UI", 10))
        self.log.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))
        self.log.tag_config("user", foreground="#1f5fbf", font=("Segoe UI", 10, "bold"))
        self.log.tag_config("bot", foreground="#222222")
        self.log.tag_config("action", foreground="#6b6b6b", font=("Consolas", 9))
        self.log.tag_config("error", foreground="#b00020")

        bottom = tk.Frame(self.root)
        bottom.pack(fill=tk.X, padx=8, pady=(0, 8))
        self.entry = tk.Text(bottom, height=3, wrap=tk.WORD, font=("Segoe UI", 10))
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", self._on_enter)
        self.send_btn = tk.Button(bottom, text="Envoyer", width=10, command=self._send)
        self.send_btn.pack(side=tk.RIGHT, padx=(6, 0), fill=tk.Y)

        self.ui_queue: queue.Queue = queue.Queue()
        self.requests: queue.Queue = queue.Queue()
        # Un seul thread de travail : les objets COM d'AutoCAD doivent rester
        # dans le thread qui les a créés.
        threading.Thread(target=self._worker, args=(make_backend, model), daemon=True).start()
        self.root.after(100, self._drain_ui_queue)
        self._set_busy(True)

    # ---- thread de travail --------------------------------------------------
    def _worker(self, make_backend, model):
        com_initialized = False
        try:
            try:
                import pythoncom  # type: ignore[import-not-found]
                pythoncom.CoInitialize()
                com_initialized = True
            except ImportError:
                pass
            backend = make_backend()
            assistant = DrawingAssistant(backend, model=model, library=self.library,
                                         company=self.company)
        except Exception as exc:
            self.ui_queue.put(("error", f"Démarrage impossible : {exc}\n"))
            return
        profils = (f"Bibliothèque de profils : {len(self.library)} profils "
                   f"({', '.join(self.library.series())})\n" if self.library else "")
        self.ui_queue.put(("bot", f"Connecté à : {backend.name}\n{profils}\n{WELCOME}\n"))
        self.ui_queue.put(("ready", None))

        while True:
            text = self.requests.get()
            if text is None:
                break
            try:
                reply = assistant.ask(text, on_action=self._report_action)
                self.ui_queue.put(("bot", reply + "\n\n"))
            except Exception as exc:
                self.ui_queue.put(("error", f"Erreur : {exc}\n\n"))
            self.ui_queue.put(("ready", None))

        if com_initialized:
            pythoncom.CoUninitialize()

    def _report_action(self, name, args, result, is_error):
        tag = "error" if is_error else "action"
        self.ui_queue.put((tag, f"  ▸ {name} {json.dumps(args, ensure_ascii=False)}"
                                f"{'  → ' + result if is_error else ''}\n"))

    # ---- interface ----------------------------------------------------------
    def _on_enter(self, event):
        if event.state & 0x0001:  # Maj+Entrée = nouvelle ligne
            return None
        self._send()
        return "break"

    def _send(self):
        text = self.entry.get("1.0", tk.END).strip()
        if not text or str(self.send_btn["state"]) == tk.DISABLED:
            return
        self.entry.delete("1.0", tk.END)
        self._append("user", f"Vous : {text}\n")
        self._set_busy(True)
        self.requests.put(text)

    def _set_busy(self, busy: bool):
        self.send_btn.config(state=tk.DISABLED if busy else tk.NORMAL,
                             text="…" if busy else "Envoyer")

    def _append(self, tag, text):
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, text, tag)
        self.log.config(state=tk.DISABLED)
        self.log.see(tk.END)

    def _drain_ui_queue(self):
        while not self.ui_queue.empty():
            kind, payload = self.ui_queue.get_nowait()
            if kind == "ready":
                self._set_busy(False)
                self.entry.focus_set()
            else:
                self._append(kind, payload)
        self.root.after(100, self._drain_ui_queue)

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.requests.put(None)
