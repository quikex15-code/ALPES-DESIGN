"""Lancement : python -m autocad_assistant [--mode auto|autocad|dxf] [--dxf fichier.dxf] [--console]"""

from __future__ import annotations

import argparse
import json

from .agent import DEFAULT_MODEL, DrawingAssistant
from .backends import open_backend


def run_console(backend, model: str) -> None:
    assistant = DrawingAssistant(backend, model=model)
    print(f"Connecté à : {backend.name}. Tapez 'quitter' pour sortir.\n")

    def show(name, args, result, is_error):
        print(f"  ▸ {name} {json.dumps(args, ensure_ascii=False)}"
              + (f"  → {result}" if is_error else ""))

    while True:
        try:
            text = input("Vous > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ("quitter", "exit", "quit"):
            break
        if text:
            print(f"\nAssistant > {assistant.ask(text, on_action=show)}\n")

    backend.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Dessiner dans AutoCAD en dialoguant.")
    parser.add_argument("--mode", choices=["auto", "autocad", "dxf"], default="auto",
                        help="auto : AutoCAD s'il est ouvert, sinon fichier DXF.")
    parser.add_argument("--dxf", default="dessin.dxf", help="Fichier DXF (mode dxf).")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Modèle Claude à utiliser.")
    parser.add_argument("--console", action="store_true",
                        help="Dialogue dans le terminal au lieu de la fenêtre.")
    args = parser.parse_args()

    if args.console:
        run_console(open_backend(args.mode, args.dxf), args.model)
    else:
        from .gui import ChatWindow
        ChatWindow(lambda: open_backend(args.mode, args.dxf), args.model).run()


if __name__ == "__main__":
    main()
