"""Lancement : python -m autocad_assistant [--mode auto|autocad|dxf] [--dxf fichier.dxf]
                                          [--profils DOSSIER] [--console]"""

from __future__ import annotations

import argparse
import json
import os

from .agent import DEFAULT_MODEL, DrawingAssistant
from .backends import open_backend
from .profiles import ProfileLibrary
from .titleblock import load_company


def run_console(backend, model: str, library=None, company=None) -> None:
    assistant = DrawingAssistant(backend, model=model, library=library, company=company)
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
    parser.add_argument("--profils", default=os.environ.get("ALPES_PROFILS"),
                        help="Dossier de la bibliothèque de profils (DWG/DXF). "
                             "Par défaut : variable d'environnement ALPES_PROFILS.")
    parser.add_argument("--entreprise", default=None,
                        help="Fichier entreprise.json pour le cartouche (par défaut : "
                             "ALPES_ENTREPRISE, puis entreprise.json du dossier courant "
                             "ou du projet).")
    parser.add_argument("--console", action="store_true",
                        help="Dialogue dans le terminal au lieu de la fenêtre.")
    args = parser.parse_args()

    library = None
    if args.profils:
        library = ProfileLibrary(args.profils)
        print(f"Bibliothèque de profils : {len(library)} profils dans {library.folder}")

    company = load_company(args.entreprise)
    print(f"Cartouche au nom de : {company['nom']}")

    if args.console:
        run_console(open_backend(args.mode, args.dxf), args.model, library, company)
    else:
        from .gui import ChatWindow
        ChatWindow(lambda: open_backend(args.mode, args.dxf), args.model, library,
                   company).run()


if __name__ == "__main__":
    main()
