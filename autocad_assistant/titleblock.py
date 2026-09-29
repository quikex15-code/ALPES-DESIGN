"""Cadre et cartouche automatiques aux couleurs de l'entreprise.

Le cadre est dessiné dans l'espace objet, à l'échelle du dessin : une feuille A3
au 1:20 mesure donc 8400 × 5940 unités. L'échelle est choisie automatiquement
pour que le dessin tienne dans la feuille, sauf si elle est imposée.

Les coordonnées de l'entreprise sont lues dans entreprise.json (voir README).
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from .backends import DrawingBackend

LAYER = "CARTOUCHE"

# Formats en mm, orientation paysage (largeur, hauteur).
FORMATS = {"A4": (297, 210), "A3": (420, 297), "A2": (594, 420), "A1": (841, 594),
           "A0": (1189, 841)}
SCALES = [1, 2, 5, 10, 20, 25, 50, 75, 100, 200, 250, 500, 1000, 2000, 5000]

MARGIN = 10               # marge de la feuille au cadre (mm papier)
TB_W, TB_H = 180, 45      # taille du cartouche (mm papier)
FILL = 0.9                # le dessin occupe au plus 90 % de la zone disponible

DEFAULT_COMPANY = {"nom": "ALPES DESIGN", "adresse": [], "telephone": "", "email": "",
                   "site": "", "logo": "", "dessinateur": "", "format_par_defaut": "A3"}

TOOL = {
    "name": "draw_title_block",
    "description": (
        "Dessine le cadre de la feuille et le cartouche de l'entreprise autour du dessin "
        "existant (à faire en dernier). L'ancien cartouche est remplacé. Si 'echelle' est "
        "omise, l'échelle normalisée la plus grande qui fait tenir le dessin est choisie. "
        "Les textes du cartouche (nom, adresse, logo de l'entreprise) sont remplis "
        "automatiquement."),
    "input_schema": {
        "type": "object",
        "properties": {
            "titre": {"type": "string", "description": "Titre du plan."},
            "projet": {"type": "string", "description": "Projet ou chantier."},
            "client": {"type": "string"},
            "numero_plan": {"type": "string"},
            "indice": {"type": "string", "description": "Indice de révision (A, B…)."},
            "format": {"type": "string", "enum": list(FORMATS)},
            "orientation": {"type": "string", "enum": ["paysage", "portrait"]},
            "echelle": {"type": "integer", "minimum": 1,
                        "description": "Dénominateur de l'échelle : 20 pour 1:20."},
            "dessine_par": {"type": "string"},
            "date": {"type": "string", "description": "Par défaut : aujourd'hui."},
        },
        "required": ["titre"],
        "additionalProperties": False,
    },
}


def load_company(path: str | os.PathLike | None = None) -> dict:
    """Charge entreprise.json : chemin donné, sinon $ALPES_ENTREPRISE, sinon dossier courant
    puis dossier du projet. Les champs absents prennent une valeur par défaut."""
    candidates = [path, os.environ.get("ALPES_ENTREPRISE"), "entreprise.json",
                  Path(__file__).resolve().parent.parent / "entreprise.json"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            data = json.loads(Path(candidate).read_text(encoding="utf-8"))
            company = {**DEFAULT_COMPANY, **data}
            if isinstance(company["adresse"], str):
                company["adresse"] = [company["adresse"]]
            logo = company.get("logo")
            if logo and not Path(logo).is_absolute():  # relatif au fichier de config
                company["logo"] = str(Path(candidate).resolve().parent / logo)
            return company
    if path:
        raise FileNotFoundError(f"Fichier entreprise introuvable : {path}")
    return dict(DEFAULT_COMPANY)


def _choose_scale(size: tuple[float, float], area: tuple[float, float]) -> int | None:
    for s in SCALES:
        if size[0] / s <= area[0] * FILL and size[1] / s <= area[1] * FILL:
            return s
    return None


class _Sheet:
    """Dessine en coordonnées « papier » (mm) converties en coordonnées du dessin."""

    def __init__(self, backend: DrawingBackend, origin: tuple[float, float], scale: int):
        self.b, self.ox, self.oy, self.k = backend, origin[0], origin[1], scale

    def pt(self, x: float, y: float) -> tuple[float, float]:
        return (self.ox + x * self.k, self.oy + y * self.k)

    def rect(self, x0, y0, x1, y1):
        self.b.polyline([self.pt(x0, y0), self.pt(x1, y0), self.pt(x1, y1), self.pt(x0, y1)],
                        closed=True, layer=LAYER)

    def line(self, x0, y0, x1, y1):
        self.b.line(self.pt(x0, y0), self.pt(x1, y1), layer=LAYER)

    def text(self, x, y, content, height, max_width=None):
        if not content:
            return
        if max_width:  # réduit la hauteur si le texte est trop long pour la case
            height = min(height, max_width / (0.75 * len(content)))
        self.b.text(self.pt(x, y), content, height * self.k, layer=LAYER)


def draw_title_block(backend: DrawingBackend, company: dict, args: dict) -> dict:
    # 1. Remplacer l'ancien cartouche.
    old = [e["handle"] for e in backend.list_entities() if e["layer"].upper() == LAYER]
    if old:
        backend.delete(old)
    backend.create_layer(LAYER, 7)

    # 2. Format, zone utile et échelle.
    fmt = args.get("format") or company.get("format_par_defaut") or "A3"
    if fmt not in FORMATS:
        raise ValueError(f"Format inconnu : {fmt} (formats : {', '.join(FORMATS)})")
    width, height = FORMATS[fmt]
    orientation = args.get("orientation", "paysage")
    if orientation == "portrait":
        width, height = height, width
    area_w = width - 2 * MARGIN
    area_h = height - 2 * MARGIN - TB_H     # zone au-dessus du cartouche

    drawing = backend.extents(exclude_layers=[LAYER])
    warning = None
    scale = args.get("echelle")
    if drawing:
        size = (drawing["largeur"], drawing["hauteur"])
        if scale is None:
            scale = _choose_scale(size, (area_w, area_h))
            if scale is None:
                scale = SCALES[-1]
                warning = "Dessin trop grand : il dépasse du cadre même au 1:%d." % scale
        elif size[0] / scale > area_w or size[1] / scale > area_h:
            warning = (f"Au 1:{scale}, le dessin dépasse du cadre {fmt}. Choisissez une "
                       "échelle plus petite ou un format plus grand.")
        cx = (drawing["min"][0] + drawing["max"][0]) / 2
        cy = (drawing["min"][1] + drawing["max"][1]) / 2
        origin = (cx - (MARGIN + area_w / 2) * scale,
                  cy - (MARGIN + TB_H + area_h / 2) * scale)
    else:
        scale = scale or 1
        origin = (0.0, 0.0)

    sheet = _Sheet(backend, origin, scale)

    # 3. Feuille et cadre.
    sheet.rect(0, 0, width, height)
    sheet.rect(MARGIN, MARGIN, width - MARGIN, height - MARGIN)

    # 4. Cartouche en bas à droite, dans le cadre.
    tb = _Sheet(backend, sheet.pt(width - MARGIN - TB_W, MARGIN), scale)
    tb.rect(0, 0, TB_W, TB_H)
    tb.line(60, 0, 60, TB_H)
    tb.line(135, 0, 135, TB_H)
    tb.line(60, 15, TB_W, 15)
    tb.line(60, 30, TB_W, 30)
    tb.line(98, 0, 98, 15)
    tb.line(158, 30, 158, TB_H)

    _company_block(backend, tb, company)

    label = 1.8
    tb.text(62, 39, f"PROJET : {args.get('projet', '')}", 2.5, 71)
    tb.text(62, 33, f"CLIENT : {args.get('client', '')}", 2.5, 71)
    tb.text(62, 26.5, "TITRE", label)
    tb.text(62, 18.5, args["titre"], 4.5, 71)
    tb.text(62, 11.5, "DESSINÉ PAR", label)
    tb.text(62, 4, args.get("dessine_par") or company.get("dessinateur", ""), 2.5, 34)
    tb.text(100, 11.5, "DATE", label)
    tb.text(100, 4, args.get("date") or dt.date.today().strftime("%d/%m/%Y"), 2.5, 33)
    tb.text(137, 41.5, "ÉCHELLE", label)
    tb.text(137, 33.5, f"1:{scale}", 3.5, 19)
    tb.text(160, 41.5, "FORMAT", label)
    tb.text(160, 33.5, fmt, 3.5, 18)
    tb.text(137, 26.5, "N° PLAN", label)
    tb.text(137, 18.5, args.get("numero_plan", ""), 4.5, 41)
    tb.text(137, 11.5, "INDICE", label)
    tb.text(137, 4, args.get("indice", ""), 3.5, 41)

    x1, y1 = sheet.pt(width, height)
    result = {"format": f"{fmt} {orientation}", "echelle": f"1:{scale}",
              "feuille": {"min": [round(origin[0], 3), round(origin[1], 3)],
                          "max": [round(x1, 3), round(y1, 3)]},
              "entreprise": company.get("nom", "")}
    if warning:
        result["avertissement"] = warning
    return result


def _company_block(backend: DrawingBackend, tb: _Sheet, company: dict) -> None:
    """Colonne de gauche du cartouche : logo, nom et coordonnées."""
    name_y, name_h = 35.0, 6.0
    logo = company.get("logo")
    if logo:
        if _insert_logo(backend, tb, logo, box=(3, 27, 57, 43)):
            name_y, name_h = 21.0, 4.5

    tb.text(3, name_y, company.get("nom", ""), name_h, 54)
    lines = list(company.get("adresse") or [])
    lines += [v for v in (company.get("telephone"), company.get("email"), company.get("site"))
              if v]
    y = name_y - 5
    for line in lines:
        if y < 2:
            break
        tb.text(3, y, line, 2.2, 54)
        y -= 3.5


def _insert_logo(backend: DrawingBackend, tb: _Sheet, path: str, box) -> bool:
    """Insère le logo (DWG/DXF) mis à l'échelle et centré dans 'box' (mm papier)."""
    if not Path(path).is_file():
        return False
    block = "LOGO_ENTREPRISE"
    handle, bbox = backend.insert_block_file(path, block, (0, 0), layer=LAYER)
    backend.delete([handle])
    if not bbox or not bbox["largeur"] or not bbox["hauteur"]:
        return False
    bw, bh = (box[2] - box[0]) * tb.k, (box[3] - box[1]) * tb.k
    factor = min(bw / bbox["largeur"], bh / bbox["hauteur"])
    handle, bbox = backend.insert_block_file(path, block, (0, 0), scale=factor, layer=LAYER)
    tx, ty = tb.pt((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    backend.move(handle, tx - (bbox["min"][0] + bbox["max"][0]) / 2,
                 ty - (bbox["min"][1] + bbox["max"][1]) / 2)
    return True
