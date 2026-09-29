"""Bibliothèque de profils : recherche et insertion (moteur DXF)."""

import json

import ezdxf
import pytest

from autocad_assistant.backends import DXFBackend
from autocad_assistant.profiles import ProfileLibrary
from autocad_assistant.tools import ToolExecutor


def make_profile(path, width, height):
    """Fichier DXF contenant un profil rectangulaire creux (point de base à l'origine)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (width, 0), (width, height), (0, height)], close=True)
    msp.add_lwpolyline([(2, 2), (width - 2, 2), (width - 2, height - 2), (2, height - 2)],
                       close=True)
    doc.saveas(path)


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "Profils"
    make_profile(root / "Forster Unico" / "U1001.dxf", 50, 70)
    make_profile(root / "Forster Unico" / "U1002.dxf", 60, 70)
    make_profile(root / "Forster Fuego" / "F2001.dxf", 55, 80)
    make_profile(root / "Divers" / "U1001.dxf", 10, 10)  # même référence, autre série
    (root / "catalogue.csv").write_bytes(
        "Référence;Description;Poids kg/m\n"
        "U1002;Dormant ouvrant intérieur;2,1\n"
        "F2001;Profilé coupe-feu EI30;3,4\n".encode("cp1252"))
    return ProfileLibrary(root)


def test_scan_and_search(library):
    assert len(library) == 4
    assert library.series() == {"Divers": 1, "Forster Fuego": 1, "Forster Unico": 2}

    res = library.search("coupe feu")
    assert [p["reference"] for p in res["profils"]] == ["F2001"]
    assert res["profils"][0]["description"] == "Profilé coupe-feu EI30"

    assert library.search("dormant")["profils"][0]["key"] == "Forster Unico/U1002"
    assert library.search("unico")["total"] == 2
    assert library.search("")["total"] == 4


def test_get_resolves_ambiguity(library):
    assert library.get("u1002").key == "Forster Unico/U1002"
    with pytest.raises(KeyError, match="ambiguë"):
        library.get("U1001")
    assert library.get("Forster Unico/U1001").series == "Forster Unico"
    with pytest.raises(KeyError, match="introuvable"):
        library.get("X999")


def test_insert_profile_into_dxf(tmp_path, library):
    out = tmp_path / "plan.dxf"
    ex = ToolExecutor(DXFBackend(str(out)), library)
    assert {"search_profiles", "insert_profile"} <= {t["name"] for t in ex.tools}

    result, err = ex.run("insert_profile", {"reference": "U1002", "position": [1000, 500],
                                            "layer": "PROFILS"})
    assert not err, result
    box = json.loads(result)["encombrement"]
    assert box["min"] == [1000, 500] and box["largeur"] == 60 and box["hauteur"] == 70

    # Rotation 90° + deuxième insertion : le bloc est réutilisé, pas réimporté.
    result, err = ex.run("insert_profile", {"reference": "U1002", "position": [0, 0],
                                            "rotation": 90})
    assert not err, result
    box = json.loads(result)["encombrement"]
    assert box["largeur"] == pytest.approx(70) and box["hauteur"] == pytest.approx(60)

    ex.backend.flush()
    doc = ezdxf.readfile(out)
    refs = doc.modelspace().query("INSERT")
    assert len(refs) == 2 and refs[0].dxf.layer == "PROFILS"
    assert len(doc.blocks.get("PROFIL_Forster_Unico_U1002")) == 2


def test_insert_unknown_profile_is_reported(tmp_path, library):
    ex = ToolExecutor(DXFBackend(str(tmp_path / "x.dxf")), library)
    result, err = ex.run("insert_profile", {"reference": "U1001", "position": [0, 0]})
    assert err and "Forster Unico/U1001" in result


def test_profile_tools_absent_without_library(tmp_path):
    ex = ToolExecutor(DXFBackend(str(tmp_path / "x.dxf")))
    assert "insert_profile" not in {t["name"] for t in ex.tools}


def test_anchor_places_corner_on_position(tmp_path, library):
    # Profil dessiné loin de son point de base, comme dans certains DWG fournisseurs.
    make_profile_far = tmp_path / "Loin" / "L1.dxf"
    make_profile(make_profile_far, 40, 30)
    doc = ezdxf.readfile(make_profile_far)
    for e in doc.modelspace():
        e.translate(5000, 2000, 0)
    doc.saveas(make_profile_far)
    lib = ProfileLibrary(tmp_path / "Loin")
    ex = ToolExecutor(DXFBackend(str(tmp_path / "x.dxf")), lib)

    result, err = ex.run("insert_profile", {"reference": "L1", "position": [100, 100],
                                            "anchor": "bas_gauche"})
    assert not err, result
    assert json.loads(result)["encombrement"]["min"] == [100, 100]

    result, err = ex.run("insert_profile", {"reference": "L1", "position": [0, 0],
                                            "anchor": "centre"})
    box = json.loads(result)["encombrement"]
    assert box["min"] == [-20, -15] and box["max"] == [20, 15]

    ex.backend.flush()
    from ezdxf import bbox
    ext = bbox.extents([ezdxf.readfile(tmp_path / "x.dxf").modelspace().query("INSERT")[0]])
    assert tuple(ext.extmin)[:2] == pytest.approx((100, 100))


def test_check_library_writes_catalog_template(library):
    from autocad_assistant.profiles import check_library

    report = check_library(library.folder)
    assert "Profils trouvés : 4" in report
    assert "Divers/U1001, Forster Unico/U1001" in report
    template = (library.folder / "catalogue_a_completer.csv").read_text("utf-8-sig")
    assert template.splitlines()[0] == "Reference;Serie;Description"
    assert "U1001;Forster Unico;" in template and "U1002" not in template
