"""Moteurs de dessin : AutoCAD en direct (COM, Windows) ou fichier DXF (ezdxf).

Les deux moteurs exposent exactement les mêmes méthodes, ce qui permet à
l'assistant de dessiner sans savoir où il dessine. Les coordonnées sont
en unités du dessin (mm par défaut) et les angles en degrés.
"""

from __future__ import annotations

import math
import os
from abc import ABC, abstractmethod
from typing import Sequence

Point = Sequence[float]


class DrawingBackend(ABC):
    """Interface commune à tous les moteurs de dessin."""

    name = "abstrait"

    @abstractmethod
    def create_layer(self, name: str, color: int = 7) -> str: ...

    @abstractmethod
    def line(self, start: Point, end: Point, layer: str | None = None) -> str: ...

    @abstractmethod
    def polyline(self, points: Sequence[Point], closed: bool = False,
                 layer: str | None = None) -> str: ...

    @abstractmethod
    def circle(self, center: Point, radius: float, layer: str | None = None) -> str: ...

    @abstractmethod
    def arc(self, center: Point, radius: float, start_angle: float, end_angle: float,
            layer: str | None = None) -> str: ...

    @abstractmethod
    def text(self, position: Point, content: str, height: float, rotation: float = 0.0,
             layer: str | None = None) -> str: ...

    @abstractmethod
    def aligned_dimension(self, start: Point, end: Point, offset: float,
                          layer: str | None = None) -> str: ...

    @abstractmethod
    def insert_block_file(self, path: str, block_name: str, position: Point,
                          rotation: float = 0.0, scale: float = 1.0, mirror: bool = False,
                          layer: str | None = None) -> tuple[str, dict]:
        """Insère le contenu d'un fichier DWG/DXF comme bloc.

        Retourne (handle, encombrement {min, max, largeur, hauteur}).
        """

    @abstractmethod
    def list_entities(self) -> list[dict]: ...

    @abstractmethod
    def delete(self, handles: Sequence[str]) -> list[str]: ...

    @abstractmethod
    def zoom_extents(self) -> None: ...

    @abstractmethod
    def save(self, path: str | None = None) -> str: ...

    def flush(self) -> None:
        """Rend les modifications persistantes (utile pour les fichiers)."""

    def rectangle(self, corner: Point, width: float, height: float,
                  layer: str | None = None) -> str:
        x, y = corner[0], corner[1]
        pts = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
        return self.polyline(pts, closed=True, layer=layer)


# --------------------------------------------------------------------------
# AutoCAD en direct via COM (Windows + AutoCAD + pywin32)
# --------------------------------------------------------------------------

class AutoCADBackend(DrawingBackend):
    """Pilote l'instance d'AutoCAD ouverte (document actif)."""

    name = "AutoCAD (en direct)"

    def __init__(self) -> None:
        import pythoncom  # type: ignore[import-not-found]
        import win32com.client  # type: ignore[import-not-found]

        self._pythoncom = pythoncom
        self._win32 = win32com.client
        try:
            self.app = win32com.client.GetActiveObject("AutoCAD.Application")
        except Exception:
            self.app = win32com.client.Dispatch("AutoCAD.Application")
        self.app.Visible = True
        if self.app.Documents.Count == 0:
            self.app.Documents.Add()
        self.doc = self.app.ActiveDocument
        self.msp = self.doc.ModelSpace

    # AutoCAD attend des tableaux VARIANT de doubles pour les points.
    def _pt(self, p: Point):
        z = p[2] if len(p) > 2 else 0.0
        return self._win32.VARIANT(self._pythoncom.VT_ARRAY | self._pythoncom.VT_R8,
                                   (float(p[0]), float(p[1]), float(z)))

    def _finish(self, ent, layer: str | None) -> str:
        if layer:
            self.create_layer(layer)
            ent.Layer = layer
        ent.Update()
        return ent.Handle

    def create_layer(self, name: str, color: int = 7) -> str:
        try:
            layer = self.doc.Layers.Item(name)
        except Exception:
            layer = self.doc.Layers.Add(name)
            layer.color = int(color)
        return name

    def set_layer_color(self, name: str, color: int) -> None:
        self.doc.Layers.Item(name).color = int(color)

    def line(self, start, end, layer=None):
        return self._finish(self.msp.AddLine(self._pt(start), self._pt(end)), layer)

    def polyline(self, points, closed=False, layer=None):
        flat = [float(c) for p in points for c in (p[0], p[1])]
        arr = self._win32.VARIANT(self._pythoncom.VT_ARRAY | self._pythoncom.VT_R8, flat)
        ent = self.msp.AddLightWeightPolyline(arr)
        ent.Closed = bool(closed)
        return self._finish(ent, layer)

    def circle(self, center, radius, layer=None):
        return self._finish(self.msp.AddCircle(self._pt(center), float(radius)), layer)

    def arc(self, center, radius, start_angle, end_angle, layer=None):
        ent = self.msp.AddArc(self._pt(center), float(radius),
                              math.radians(start_angle), math.radians(end_angle))
        return self._finish(ent, layer)

    def text(self, position, content, height, rotation=0.0, layer=None):
        ent = self.msp.AddText(content, self._pt(position), float(height))
        ent.Rotation = math.radians(rotation)
        return self._finish(ent, layer)

    def aligned_dimension(self, start, end, offset, layer=None):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        mid = ((start[0] + end[0]) / 2 + nx * offset, (start[1] + end[1]) / 2 + ny * offset)
        ent = self.msp.AddDimAligned(self._pt(start), self._pt(end), self._pt(mid))
        return self._finish(ent, layer)

    def insert_block_file(self, path, block_name, position, rotation=0.0, scale=1.0,
                          mirror=False, layer=None):
        try:
            block = self.doc.Blocks.Item(block_name)  # déjà chargé : on le réutilise
            source = block.Name
        except Exception:
            source = os.path.abspath(path)
            if not source.lower().endswith(".dwg"):
                raise ValueError("En mode AutoCAD, les profils doivent être des fichiers .dwg "
                                 f"(reçu : {os.path.basename(path)}).")
        xs = -scale if mirror else scale
        ent = self.msp.InsertBlock(self._pt(position), source, float(xs), float(scale),
                                   float(scale), math.radians(rotation))
        if source != block_name:
            # AutoCAD nomme le bloc d'après le fichier : on le renomme pour le retrouver.
            try:
                self.doc.Blocks.Item(ent.Name).Name = block_name
            except Exception:
                pass
        handle = self._finish(ent, layer)
        mn, mx = ent.GetBoundingBox()
        return handle, _bbox(mn, mx)

    def list_entities(self):
        result = []
        for i in range(self.msp.Count):
            ent = self.msp.Item(i)
            result.append({"handle": ent.Handle, "type": ent.ObjectName, "layer": ent.Layer})
        return result

    def delete(self, handles):
        deleted = []
        for h in handles:
            try:
                self.doc.HandleToObject(h).Delete()
                deleted.append(h)
            except Exception:
                pass
        self.doc.Regen(1)  # acAllViewports
        return deleted

    def zoom_extents(self):
        self.app.ZoomExtents()

    def save(self, path=None):
        if path:
            self.doc.SaveAs(os.path.abspath(path))
        else:
            self.doc.Save()
        return self.doc.FullName


# --------------------------------------------------------------------------
# Fichier DXF (fonctionne partout, sans AutoCAD)
# --------------------------------------------------------------------------

class DXFBackend(DrawingBackend):
    """Écrit dans un fichier DXF que l'on ouvre ensuite dans AutoCAD."""

    name = "Fichier DXF"

    def __init__(self, path: str = "dessin.dxf") -> None:
        import ezdxf
        from ezdxf import units

        self.path = path
        if os.path.exists(path):
            self.doc = ezdxf.readfile(path)
        else:
            self.doc = ezdxf.new("R2018", setup=True)
            self.doc.units = units.MM
        self.msp = self.doc.modelspace()

    def _attribs(self, layer: str | None) -> dict:
        if layer:
            self.create_layer(layer)
            return {"layer": layer}
        return {}

    def create_layer(self, name, color=7):
        if name not in self.doc.layers:
            self.doc.layers.add(name, color=int(color))
        return name

    def set_layer_color(self, name: str, color: int) -> None:
        self.doc.layers.get(name).color = int(color)

    def line(self, start, end, layer=None):
        return self.msp.add_line(tuple(start), tuple(end), dxfattribs=self._attribs(layer)).dxf.handle

    def polyline(self, points, closed=False, layer=None):
        pts = [(p[0], p[1]) for p in points]
        return self.msp.add_lwpolyline(pts, close=closed, dxfattribs=self._attribs(layer)).dxf.handle

    def circle(self, center, radius, layer=None):
        return self.msp.add_circle(tuple(center), radius, dxfattribs=self._attribs(layer)).dxf.handle

    def arc(self, center, radius, start_angle, end_angle, layer=None):
        return self.msp.add_arc(tuple(center), radius, start_angle, end_angle,
                                dxfattribs=self._attribs(layer)).dxf.handle

    def text(self, position, content, height, rotation=0.0, layer=None):
        attribs = self._attribs(layer)
        attribs.update(height=height, rotation=rotation)
        ent = self.msp.add_text(content, dxfattribs=attribs)
        ent.set_placement((position[0], position[1]))
        return ent.dxf.handle

    def aligned_dimension(self, start, end, offset, layer=None):
        dim = self.msp.add_aligned_dim(p1=tuple(start), p2=tuple(end), distance=offset,
                                       dxfattribs=self._attribs(layer))
        dim.render()
        return dim.dimension.dxf.handle

    def _load_block(self, path: str, block_name: str) -> None:
        if block_name in self.doc.blocks:
            return
        import ezdxf
        from ezdxf.addons import Importer, odafc

        if path.lower().endswith(".dwg"):
            if not odafc.is_installed():
                raise ValueError(
                    "Lire un profil .dwg sans AutoCAD nécessite « ODA File Converter » "
                    "(gratuit). Sinon, lancez l'assistant avec AutoCAD ouvert, ou "
                    "convertissez la bibliothèque en .dxf.")
            source = odafc.readfile(path)
        else:
            source = ezdxf.readfile(path)
        base = source.header.get("$INSBASE", (0, 0, 0))
        block = self.doc.blocks.new(block_name, base_point=base)
        importer = Importer(source, self.doc)
        importer.import_entities(source.modelspace(), target_layout=block)
        importer.finalize()

    def insert_block_file(self, path, block_name, position, rotation=0.0, scale=1.0,
                          mirror=False, layer=None):
        from ezdxf import bbox

        self._load_block(path, block_name)
        attribs = self._attribs(layer)
        attribs.update(xscale=-scale if mirror else scale, yscale=scale, zscale=scale,
                       rotation=rotation)
        ref = self.msp.add_blockref(block_name, (position[0], position[1]), dxfattribs=attribs)
        ext = bbox.extents([ref])
        box = _bbox(ext.extmin, ext.extmax) if ext.has_data else {}
        return ref.dxf.handle, box

    def list_entities(self):
        return [{"handle": e.dxf.handle, "type": e.dxftype(), "layer": e.dxf.layer}
                for e in self.msp]

    def delete(self, handles):
        deleted = []
        for h in handles:
            ent = self.doc.entitydb.get(h)
            if ent is not None and ent.is_alive:
                self.msp.delete_entity(ent)
                deleted.append(h)
        return deleted

    def zoom_extents(self):
        from ezdxf import zoom
        zoom.extents(self.msp)

    def flush(self):
        self.save()

    def save(self, path=None):
        if path:
            self.path = path
        self.doc.saveas(self.path)
        return os.path.abspath(self.path)


def _bbox(mn: Point, mx: Point) -> dict:
    return {"min": [round(mn[0], 3), round(mn[1], 3)], "max": [round(mx[0], 3), round(mx[1], 3)],
            "largeur": round(mx[0] - mn[0], 3), "hauteur": round(mx[1] - mn[1], 3)}


def open_backend(kind: str = "auto", dxf_path: str = "dessin.dxf") -> DrawingBackend:
    """Ouvre le moteur demandé. En mode 'auto', essaie AutoCAD puis le DXF."""
    if kind in ("auto", "autocad"):
        try:
            return AutoCADBackend()
        except Exception as exc:
            if kind == "autocad":
                raise RuntimeError(
                    "Impossible de se connecter à AutoCAD. Vérifiez qu'AutoCAD est "
                    "ouvert et que pywin32 est installé (pip install pywin32)."
                ) from exc
    return DXFBackend(dxf_path)
