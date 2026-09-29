"""Outils de dessin proposés à Claude et leur exécution sur un moteur."""

from __future__ import annotations

import json
from typing import Any, Callable

from .backends import DrawingBackend, _bbox
from .profiles import ProfileLibrary

_POINT = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 2,
    "maxItems": 3,
    "description": "Point [x, y] en unités du dessin (mm).",
}
_LAYER = {"type": "string", "description": "Calque (créé s'il n'existe pas). Facultatif."}


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


TOOLS: list[dict] = [
    _tool("create_layer", "Crée un calque (ou change sa couleur s'il existe déjà).",
          {"name": {"type": "string"},
           "color": {"type": "integer", "minimum": 1, "maximum": 255,
                     "description": "Couleur AutoCAD (ACI) : 1 rouge, 2 jaune, 3 vert, "
                                    "4 cyan, 5 bleu, 6 magenta, 7 blanc/noir, 8 gris."}},
          ["name", "color"]),
    _tool("draw_line", "Dessine une ligne entre deux points.",
          {"start": _POINT, "end": _POINT, "layer": _LAYER}, ["start", "end"]),
    _tool("draw_polyline", "Dessine une polyligne passant par une liste de points.",
          {"points": {"type": "array", "items": _POINT, "minItems": 2},
           "closed": {"type": "boolean", "description": "Ferme la polyligne."},
           "layer": _LAYER},
          ["points"]),
    _tool("draw_rectangle", "Dessine un rectangle à partir de son coin inférieur gauche.",
          {"corner": _POINT, "width": {"type": "number"}, "height": {"type": "number"},
           "layer": _LAYER},
          ["corner", "width", "height"]),
    _tool("draw_circle", "Dessine un cercle.",
          {"center": _POINT, "radius": {"type": "number", "exclusiveMinimum": 0},
           "layer": _LAYER},
          ["center", "radius"]),
    _tool("draw_arc", "Dessine un arc (sens trigonométrique, angles en degrés, 0° = axe X).",
          {"center": _POINT, "radius": {"type": "number", "exclusiveMinimum": 0},
           "start_angle": {"type": "number"}, "end_angle": {"type": "number"},
           "layer": _LAYER},
          ["center", "radius", "start_angle", "end_angle"]),
    _tool("draw_text", "Écrit un texte sur une ligne.",
          {"position": _POINT, "text": {"type": "string"},
           "height": {"type": "number", "exclusiveMinimum": 0},
           "rotation": {"type": "number", "description": "Rotation en degrés."},
           "layer": _LAYER},
          ["position", "text", "height"]),
    _tool("draw_dimension",
          "Ajoute une cote alignée entre deux points. offset > 0 place la cote à gauche "
          "du segment start→end (au-dessus pour un segment horizontal orienté vers la droite).",
          {"start": _POINT, "end": _POINT, "offset": {"type": "number"}, "layer": _LAYER},
          ["start", "end", "offset"]),
    _tool("list_entities",
          "Liste les objets du dessin (identifiant, type, calque). À utiliser avant de "
          "supprimer ou pour connaître le contenu existant.",
          {}, []),
    _tool("delete_entities", "Supprime des objets par leurs identifiants (handles).",
          {"handles": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
          ["handles"]),
    _tool("zoom_extents", "Cadre la vue sur tout le dessin.", {}, []),
    _tool("save_drawing", "Enregistre le dessin (chemin facultatif, .dwg ou .dxf selon le moteur).",
          {"path": {"type": "string"}}, []),
]

ANCHORS = ["base", "centre", "bas_gauche", "bas_droite", "haut_gauche", "haut_droite"]

PROFILE_TOOLS: list[dict] = [
    _tool("search_profiles",
          "Cherche dans la bibliothèque de profils (Forster, etc.) par référence, série ou "
          "mots de la description. Requête vide = aperçu des séries disponibles.",
          {"query": {"type": "string"}}, ["query"]),
    _tool("insert_profile",
          "Insère un profil de la bibliothèque comme bloc. 'anchor' indique quel point du "
          "profil est placé sur 'position' (après rotation/symétrie). Retourne l'encombrement "
          "réel (min, max, largeur, hauteur) pour aligner ou coter la suite.",
          {"reference": {"type": "string",
                         "description": "Référence ou clé « série/référence » trouvée par "
                                        "search_profiles."},
           "position": _POINT,
           "anchor": {"type": "string", "enum": ANCHORS,
                      "description": "Point du profil placé sur 'position'. "
                                     "'base' = point de base du fichier DWG (par défaut). "
                                     "Utilise un coin ou 'centre' si le point de base du "
                                     "fichier est éloigné du profil."},
           "rotation": {"type": "number", "description": "Rotation en degrés."},
           "scale": {"type": "number", "exclusiveMinimum": 0,
                     "description": "Échelle (1 par défaut)."},
           "mirror": {"type": "boolean", "description": "Symétrie gauche/droite."},
           "layer": _LAYER},
          ["reference", "position"]),
]


def _anchor_point(box: dict, anchor: str) -> tuple[float, float]:
    (x0, y0), (x1, y1) = box["min"], box["max"]
    x = {"gauche": x0, "droite": x1}.get(anchor.split("_")[-1], (x0 + x1) / 2)
    y = {"bas": y0, "haut": y1}.get(anchor.split("_")[0], (y0 + y1) / 2)
    return x, y


def tools_for(library: ProfileLibrary | None) -> list[dict]:
    return TOOLS + PROFILE_TOOLS if library else TOOLS


def _profile_handlers(b: DrawingBackend, lib: ProfileLibrary) -> dict[str, Callable[[dict], Any]]:
    def insert_profile(a):
        profile = lib.get(a["reference"])
        anchor = a.get("anchor", "base")
        if anchor not in ANCHORS:
            raise ValueError(f"anchor doit être l'une de ces valeurs : {', '.join(ANCHORS)}")
        handle, box = b.insert_block_file(str(profile.path), profile.block_name, a["position"],
                                          a.get("rotation", 0.0), a.get("scale", 1.0),
                                          a.get("mirror", False), a.get("layer"))
        if anchor != "base" and box:
            ax, ay = _anchor_point(box, anchor)
            dx, dy = a["position"][0] - ax, a["position"][1] - ay
            b.move(handle, dx, dy)
            box = _bbox((box["min"][0] + dx, box["min"][1] + dy),
                        (box["max"][0] + dx, box["max"][1] + dy))
        return {"handle": handle, "profil": profile.key, "encombrement": box}

    return {"search_profiles": lambda a: lib.search(a["query"]),
            "insert_profile": insert_profile}


def _handlers(b: DrawingBackend) -> dict[str, Callable[[dict], Any]]:
    def create_layer(a):
        b.create_layer(a["name"], a["color"])
        b.set_layer_color(a["name"], a["color"])  # type: ignore[attr-defined]
        return {"layer": a["name"]}

    return {
        "create_layer": create_layer,
        "draw_line": lambda a: {"handle": b.line(a["start"], a["end"], a.get("layer"))},
        "draw_polyline": lambda a: {"handle": b.polyline(a["points"], a.get("closed", False),
                                                         a.get("layer"))},
        "draw_rectangle": lambda a: {"handle": b.rectangle(a["corner"], a["width"], a["height"],
                                                           a.get("layer"))},
        "draw_circle": lambda a: {"handle": b.circle(a["center"], a["radius"], a.get("layer"))},
        "draw_arc": lambda a: {"handle": b.arc(a["center"], a["radius"], a["start_angle"],
                                               a["end_angle"], a.get("layer"))},
        "draw_text": lambda a: {"handle": b.text(a["position"], a["text"], a["height"],
                                                 a.get("rotation", 0.0), a.get("layer"))},
        "draw_dimension": lambda a: {"handle": b.aligned_dimension(a["start"], a["end"],
                                                                   a["offset"], a.get("layer"))},
        "list_entities": lambda a: {"entities": b.list_entities()},
        "delete_entities": lambda a: {"deleted": b.delete(a["handles"])},
        "zoom_extents": lambda a: (b.zoom_extents(), {"ok": True})[1],
        "save_drawing": lambda a: {"saved_to": b.save(a.get("path"))},
    }


class ToolExecutor:
    """Exécute les appels d'outils de Claude sur un moteur de dessin."""

    def __init__(self, backend: DrawingBackend, library: ProfileLibrary | None = None) -> None:
        self.backend = backend
        self.tools = tools_for(library)
        self._handlers = _handlers(backend)
        if library:
            self._handlers.update(_profile_handlers(backend, library))
        self._required = {t["name"]: t["input_schema"]["required"] for t in self.tools}

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """Retourne (résultat JSON, est_une_erreur)."""
        handler = self._handlers.get(name)
        if handler is None:
            return f"Outil inconnu : {name}", True
        if not isinstance(args, dict):
            return "Arguments invalides : un objet JSON est attendu.", True
        missing = [k for k in self._required[name] if k not in args]
        if missing:
            return f"Arguments manquants : {', '.join(missing)}", True
        try:
            return json.dumps(handler(args), ensure_ascii=False), False
        except Exception as exc:  # l'erreur est renvoyée à Claude pour qu'il corrige
            return f"Erreur pendant '{name}' : {exc}", True
