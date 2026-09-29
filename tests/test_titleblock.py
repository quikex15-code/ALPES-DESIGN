"""Cadre et cartouche automatiques (moteur DXF)."""

import json

import ezdxf
import pytest

from autocad_assistant.backends import DXFBackend
from autocad_assistant.titleblock import LAYER, draw_title_block, load_company
from autocad_assistant.tools import ToolExecutor

COMPANY = {"nom": "ALPES DESIGN", "adresse": ["12 rue des Alpes", "74000 Annecy"],
           "telephone": "04 00 00 00 00", "email": "", "site": "", "logo": "",
           "dessinateur": "J. Martin", "format_par_defaut": "A3"}


def texts(backend):
    return [e.dxf.text for e in backend.msp.query(f'TEXT[layer=="{LAYER}"]')]


def test_auto_scale_and_content(tmp_path):
    b = DXFBackend(str(tmp_path / "plan.dxf"))
    b.rectangle((0, 0), 4000, 3000)          # pièce de 4 × 3 m
    result = draw_title_block(b, COMPANY, {"titre": "Plan de la pièce", "client": "Dupont",
                                           "numero_plan": "12", "indice": "A",
                                           "date": "01/10/2026"})
    # A3 paysage : zone utile 400 × 232 mm → 1:20 (200 × 150 mm) est la plus grande échelle.
    assert result["echelle"] == "1:20" and result["format"] == "A3 paysage"
    assert "avertissement" not in result
    feuille = result["feuille"]
    assert feuille["max"][0] - feuille["min"][0] == pytest.approx(420 * 20)

    t = texts(b)
    for expected in ["ALPES DESIGN", "12 rue des Alpes", "74000 Annecy", "Plan de la pièce",
                     "CLIENT : Dupont", "12", "A", "1:20", "A3", "J. Martin", "01/10/2026"]:
        assert expected in t

    # Le dessin est entièrement dans le cadre, au-dessus du cartouche.
    fmin, fmax = feuille["min"], feuille["max"]
    assert fmin[0] < 0 and fmin[1] + (10 + 45) * 20 < 0
    assert fmax[0] > 4000 and fmax[1] > 3000


def test_replaces_previous_title_block(tmp_path):
    b = DXFBackend(str(tmp_path / "plan.dxf"))
    b.circle((0, 0), 100)
    draw_title_block(b, COMPANY, {"titre": "V1"})
    n = len(b.msp.query(f'*[layer=="{LAYER}"]'))
    draw_title_block(b, COMPANY, {"titre": "V2", "format": "A4", "orientation": "portrait"})
    assert len(b.msp.query(f'*[layer=="{LAYER}"]')) == n
    assert "V2" in texts(b) and "V1" not in texts(b)
    assert len(b.msp.query("CIRCLE")) == 1


def test_forced_scale_too_small_warns(tmp_path):
    b = DXFBackend(str(tmp_path / "plan.dxf"))
    b.rectangle((0, 0), 10000, 5000)
    result = draw_title_block(b, COMPANY, {"titre": "T", "echelle": 5})
    assert result["echelle"] == "1:5" and "dépasse" in result["avertissement"]


def test_logo_fits_its_box(tmp_path):
    logo = tmp_path / "logo.dxf"
    doc = ezdxf.new()
    doc.modelspace().add_circle((500, 500), 300)   # logo loin de l'origine
    doc.saveas(logo)
    b = DXFBackend(str(tmp_path / "plan.dxf"))
    b.rectangle((0, 0), 400, 300)
    result = draw_title_block(b, {**COMPANY, "logo": str(logo)}, {"titre": "T"})
    k = int(result["echelle"].split(":")[1])
    from ezdxf import bbox
    ext = bbox.extents(b.msp.query("INSERT"))
    assert len(b.msp.query("INSERT")) == 1
    assert ext.size.y == pytest.approx(16 * k)   # boîte logo : 54 × 16 mm papier


def test_tool_and_company_file(tmp_path, monkeypatch):
    cfg = tmp_path / "entreprise.json"
    cfg.write_text(json.dumps({"nom": "MA SOCIETE", "adresse": "1 place du Marché",
                               "logo": "logo.dwg"}), encoding="utf-8")
    company = load_company(cfg)
    assert company["nom"] == "MA SOCIETE" and company["adresse"] == ["1 place du Marché"]
    assert company["logo"] == str(tmp_path / "logo.dwg") and company["format_par_defaut"] == "A3"

    monkeypatch.setenv("ALPES_ENTREPRISE", str(cfg))
    ex = ToolExecutor(DXFBackend(str(tmp_path / "plan.dxf")))
    out, err = ex.run("draw_title_block", {"titre": "Essai"})
    assert not err, out    # logo absent : ignoré, pas d'erreur
    assert "MA SOCIETE" in texts(ex.backend)
