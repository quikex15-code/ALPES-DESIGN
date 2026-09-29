"""Conversation avec Claude : chaque message de l'utilisateur devient des dessins."""

from __future__ import annotations

from typing import Callable

import anthropic

from .backends import DrawingBackend
from .profiles import ProfileLibrary
from .tools import ToolExecutor

DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """\
Tu es un assistant de dessin technique connecté à AutoCAD. L'utilisateur te décrit \
en langage naturel ce qu'il veut dessiner et tu le dessines avec les outils fournis.

Conventions :
- Unités : millimètres, sauf si l'utilisateur précise autre chose (convertis alors en mm).
- Repère : X vers la droite, Y vers le haut, angles en degrés dans le sens trigonométrique.
- Si l'utilisateur ne donne pas de position, place le dessin près de l'origine (0,0) \
et à côté des objets existants plutôt que par-dessus.
- Organise le dessin en calques parlants (ex. MURS, COTES, TEXTES, AXES) lorsque c'est utile.
- Pour modifier ou supprimer un objet existant, consulte d'abord list_entities.
- Si une demande est ambiguë au point de changer le résultat (dimension manquante \
indispensable, par exemple), pose une question courte. Sinon choisis des valeurs \
raisonnables et indique-les.
- À la fin, cadre la vue (zoom_extents) et résume en une ou deux phrases ce qui a été \
dessiné, avec les dimensions principales. Réponds en français.
- Cartouche : quand l'utilisateur demande un cartouche, un cadre, une mise en page ou \
un plan à imprimer, termine le dessin puis appelle draw_title_block en dernier (l'échelle \
se calcule sur le dessin existant). Déduis le titre du contexte si l'utilisateur ne le \
donne pas. Signale tout avertissement renvoyé (dessin qui dépasse du cadre).
"""

PROFILES_PROMPT = """
Bibliothèque de profils :
- Une bibliothèque de profils (menuiserie métallique Forster, etc.) est disponible. \
Quand l'utilisateur cite un profil, une série ou une référence, trouve la référence \
exacte avec search_profiles puis insère-la avec insert_profile. Ne redessine jamais \
à la main un profil qui existe dans la bibliothèque.
- Si plusieurs profils correspondent, propose les candidats à l'utilisateur plutôt que \
d'en choisir un au hasard.
- Sers-toi de l'encombrement renvoyé par insert_profile pour positionner les éléments \
suivants (assemblages, vitrages, cotes) au bon endroit.
"""

# Retente automatiquement la requête sur un autre modèle en cas de refus.
_BETAS = ["server-side-fallback-2026-07-01"]


class DrawingAssistant:
    """Garde l'historique de la conversation et exécute les dessins demandés."""

    def __init__(self, backend: DrawingBackend, model: str = DEFAULT_MODEL,
                 client: anthropic.Anthropic | None = None, max_steps: int = 40,
                 library: ProfileLibrary | None = None, company: dict | None = None) -> None:
        self.backend = backend
        self.executor = ToolExecutor(backend, library, company)
        self.system = SYSTEM_PROMPT + (PROFILES_PROMPT if library else "")
        self.model = model
        self.client = client or anthropic.Anthropic()
        self.max_steps = max_steps
        self.messages: list[dict] = []

    def ask(self, user_text: str,
            on_action: Callable[[str, dict, str, bool], None] | None = None) -> str:
        """Envoie un message, laisse Claude dessiner, retourne sa réponse finale.

        on_action(nom_outil, arguments, résultat, erreur) est appelé après chaque
        action de dessin, pour afficher la progression.
        """
        try:
            return self._ask(user_text, on_action)
        finally:
            self.backend.flush()

    def _ask(self, user_text: str,
             on_action: Callable[[str, dict, str, bool], None] | None) -> str:
        turn_start = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})

        for _ in range(self.max_steps):
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=self.system,
                tools=self.executor.tools,
                messages=self.messages,
                output_config={"effort": "medium"},
                betas=_BETAS,
                fallbacks="default",
            )

            if response.stop_reason == "refusal":
                # On retire toute la demande refusée pour garder un historique cohérent.
                del self.messages[turn_start:]
                return "Désolé, je ne peux pas traiter cette demande. Reformulez-la."

            # On renvoie toujours le contenu complet (réflexion + appels d'outils).
            self.messages.append({"role": "assistant", "content": response.content})

            tool_calls = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_calls:
                text = "\n".join(b.text for b in response.content if b.type == "text").strip()
                if response.stop_reason == "max_tokens":
                    text += "\n(Réponse tronquée : la limite de longueur a été atteinte.)"
                return text or "C'est fait."

            results = []
            for call in tool_calls:
                output, is_error = self.executor.run(call.name, call.input)
                if on_action:
                    on_action(call.name, call.input, output, is_error)
                results.append({"type": "tool_result", "tool_use_id": call.id,
                                "content": output, "is_error": is_error})
            self.messages.append({"role": "user", "content": results})

        return "J'ai atteint le nombre maximal d'étapes pour cette demande. Précisez la suite."
