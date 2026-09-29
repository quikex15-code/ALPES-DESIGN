"""Bibliothèque de profils (Forster ou autre) : un dossier de fichiers DWG/DXF.

Organisation attendue (les sous-dossiers servent de série / gamme) :

    Profils/
      catalogue.csv            (facultatif : reference;description;...)
      Forster Unico/
        U1234.dwg
        U1235.dwg
      Forster Fuego Light/
        F5678.dwg

Chaque fichier est un profil ; sa référence est le nom du fichier sans extension.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

PROFILE_EXTENSIONS = {".dwg", ".dxf"}
CATALOG_NAMES = ("catalogue.csv", "profils.csv", "catalog.csv")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


@dataclass
class Profile:
    key: str                  # « série/référence », unique dans la bibliothèque
    reference: str            # nom du fichier sans extension
    series: str               # sous-dossier (vide à la racine)
    path: Path
    info: dict = field(default_factory=dict)   # colonnes du catalogue CSV

    def summary(self) -> dict:
        data = {"reference": self.reference, "key": self.key, "serie": self.series,
                "format": self.path.suffix.lower().lstrip(".")}
        data.update({k: v for k, v in self.info.items() if v and k != "reference"})
        return data

    @property
    def block_name(self) -> str:
        """Nom de bloc valide pour AutoCAD."""
        return "PROFIL_" + re.sub(r'[<>/\\":;?*|,=`\s]+', "_", self.key)


class ProfileLibrary:
    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder).expanduser().resolve()
        if not self.folder.is_dir():
            raise FileNotFoundError(f"Dossier de profils introuvable : {self.folder}")
        catalog = self._read_catalog()
        self.profiles: list[Profile] = []
        for path in sorted(self.folder.rglob("*")):
            if path.suffix.lower() not in PROFILE_EXTENSIONS or not path.is_file():
                continue
            rel = path.relative_to(self.folder)
            series = "/".join(rel.parent.parts)
            key = "/".join(rel.with_suffix("").parts)
            info = catalog.get(_normalize(path.stem), {})
            self.profiles.append(Profile(key, path.stem, series, path, info))

    def __len__(self) -> int:
        return len(self.profiles)

    def _read_catalog(self) -> dict[str, dict]:
        for name in CATALOG_NAMES:
            path = self.folder / name
            if not path.exists():
                continue
            for encoding in ("utf-8-sig", "cp1252"):  # Excel FR enregistre souvent en cp1252
                try:
                    raw = path.read_text(encoding=encoding)
                    break
                except UnicodeDecodeError:
                    continue
            delimiter = ";" if raw.count(";") >= raw.count(",") else ","
            rows = csv.DictReader(raw.splitlines(), delimiter=delimiter)
            catalog = {}
            for row in rows:
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                ref = row.get("reference") or row.get("référence") or row.get("ref")
                if ref:
                    catalog[_normalize(ref)] = row
            return catalog
        return {}

    def series(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self.profiles:
            counts[p.series or "(racine)"] = counts.get(p.series or "(racine)", 0) + 1
        return counts

    def search(self, query: str, limit: int = 40) -> dict:
        words = _normalize(query).split()
        matches = []
        for p in self.profiles:
            haystack = _normalize(" ".join([p.key, *map(str, p.info.values())]))
            if all(w in haystack for w in words):
                matches.append(p)
        return {
            "total": len(matches),
            "profils": [p.summary() for p in matches[:limit]],
            "tronque": len(matches) > limit,
            "series_disponibles": self.series(),
        }

    def get(self, reference: str) -> Profile:
        wanted = _normalize(reference.strip().replace("\\", "/"))
        by_key = [p for p in self.profiles if _normalize(p.key) == wanted]
        if by_key:
            return by_key[0]
        by_ref = [p for p in self.profiles if _normalize(p.reference) == wanted]
        if len(by_ref) == 1:
            return by_ref[0]
        if len(by_ref) > 1:
            keys = ", ".join(p.key for p in by_ref)
            raise KeyError(f"Référence ambiguë « {reference} », précisez la série : {keys}")
        raise KeyError(f"Profil « {reference} » introuvable. Utilisez search_profiles.")
