"""Tests hors-ligne : un faux client Claude pilote le moteur DXF."""

from types import SimpleNamespace as NS

import ezdxf

from autocad_assistant.agent import DrawingAssistant
from autocad_assistant.backends import DXFBackend
from autocad_assistant.tools import TOOLS, ToolExecutor


class FakeClient:
    """Rejoue une suite de réponses prédéfinies et mémorise les requêtes."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def tool_use(id_, name, input_):
    return NS(type="tool_use", id=id_, name=name, input=input_)


def text(t):
    return NS(type="text", text=t)


def test_conversation_draws_into_dxf(tmp_path):
    path = tmp_path / "piece.dxf"
    backend = DXFBackend(str(path))
    client = FakeClient([
        NS(stop_reason="tool_use", content=[
            tool_use("t1", "create_layer", {"name": "MURS", "color": 1}),
            tool_use("t2", "draw_rectangle", {"corner": [0, 0], "width": 4000,
                                              "height": 3000, "layer": "MURS"}),
            tool_use("t3", "draw_circle", {"center": [2000, 1500], "radius": 300}),
            tool_use("t4", "draw_dimension", {"start": [0, 0], "end": [4000, 0],
                                              "offset": -500, "layer": "COTES"}),
            tool_use("t5", "draw_text", {"position": [100, 100], "text": "SALON",
                                         "height": 200}),
        ]),
        NS(stop_reason="end_turn", content=[text("Pièce de 4 × 3 m dessinée.")]),
    ])
    assistant = DrawingAssistant(backend, client=client)
    actions = []

    reply = assistant.ask("Dessine une pièce de 4 m sur 3 m",
                          on_action=lambda *a: actions.append(a))

    assert reply == "Pièce de 4 × 3 m dessinée."
    assert [a[0] for a in actions] == ["create_layer", "draw_rectangle", "draw_circle",
                                       "draw_dimension", "draw_text"]
    assert not any(a[3] for a in actions), actions

    # Les 5 résultats d'outils reviennent dans un seul message utilisateur.
    second = client.requests[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert len(second[2]["content"]) == 5
    assert client.requests[0]["tools"] is TOOLS

    doc = ezdxf.readfile(path)  # sauvegardé automatiquement
    types = sorted(e.dxftype() for e in doc.modelspace())
    assert types == ["CIRCLE", "DIMENSION", "LWPOLYLINE", "TEXT"]
    assert doc.layers.get("MURS").color == 1
    rect = doc.modelspace().query("LWPOLYLINE").first
    assert rect.closed and rect.dxf.layer == "MURS"


def test_tool_errors_are_reported_not_raised(tmp_path):
    ex = ToolExecutor(DXFBackend(str(tmp_path / "x.dxf")))
    out, err = ex.run("draw_circle", {"center": [0, 0]})
    assert err and "radius" in out
    out, err = ex.run("inconnu", {})
    assert err


def test_list_and_delete(tmp_path):
    ex = ToolExecutor(DXFBackend(str(tmp_path / "x.dxf")))
    ex.run("draw_line", {"start": [0, 0], "end": [10, 0]})
    ex.run("draw_arc", {"center": [0, 0], "radius": 5, "start_angle": 0, "end_angle": 90})
    ents = ex.backend.list_entities()
    assert [e["type"] for e in ents] == ["LINE", "ARC"]
    ex.run("delete_entities", {"handles": [ents[0]["handle"]]})
    assert [e["type"] for e in ex.backend.list_entities()] == ["ARC"]


def test_refusal_rolls_back_the_turn(tmp_path):
    client = FakeClient([
        NS(stop_reason="tool_use", content=[tool_use("t1", "zoom_extents", {})]),
        NS(stop_reason="refusal", content=[]),
    ])
    assistant = DrawingAssistant(DXFBackend(str(tmp_path / "x.dxf")), client=client)
    assistant.ask("…")
    assert assistant.messages == []
