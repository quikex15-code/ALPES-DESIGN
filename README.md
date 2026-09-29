# ALPES-DESIGN — Assistant de dessin AutoCAD

Décrivez un dessin en français dans une fenêtre de dialogue : l'assistant (Claude)
le trace directement dans AutoCAD.

> « Dessine une pièce de 4 m sur 3 m avec des murs de 20 cm, et cote-la »
> « Ajoute une porte de 90 cm au milieu du mur du bas »
> « Supprime le cercle que tu viens de faire »

## Comment ça marche

```
Vous (fenêtre de dialogue) ──► Claude ──► outils de dessin ──► AutoCAD (en direct)
                                                           └─► ou fichier .dxf
```

1. Vous écrivez votre demande dans la fenêtre.
2. Claude la traduit en actions : calques, lignes, polylignes, rectangles, cercles,
   arcs, textes, cotes, suppression, zoom, enregistrement.
3. Les actions sont exécutées dans le document AutoCAD ouvert (via l'interface COM
   de Windows). Si AutoCAD n'est pas disponible, elles sont écrites dans un fichier
   DXF que vous ouvrirez ensuite dans AutoCAD.
4. La conversation garde le contexte : vous pouvez corriger, compléter, déplacer…

## Installation (Windows, avec AutoCAD)

1. Installez [Python 3.10+](https://www.python.org/downloads/) (cochez « Add to PATH »).
2. Dans un terminal, depuis ce dossier :
   ```bat
   pip install -r requirements.txt
   ```
3. Créez une clé API sur <https://console.anthropic.com> puis déclarez-la :
   ```bat
   setx ANTHROPIC_API_KEY "sk-ant-..."
   ```
   (fermez et rouvrez le terminal ensuite).

## Utilisation

Ouvrez AutoCAD avec un dessin, puis :

```bat
python -m autocad_assistant
```

La fenêtre de dialogue s'ouvre au-dessus d'AutoCAD. **Entrée** envoie le message,
**Maj+Entrée** passe à la ligne.

Options :

| Option | Effet |
|---|---|
| `--mode autocad` | Exige AutoCAD (erreur s'il n'est pas ouvert) |
| `--mode dxf --dxf plan.dxf` | Dessine dans un fichier DXF (sans AutoCAD, aussi sur Mac/Linux) |
| `--console` | Dialogue dans le terminal au lieu de la fenêtre |
| `--model <id>` | Autre modèle Claude (par défaut `claude-opus-5-5`) |

Par défaut (`--mode auto`), AutoCAD est utilisé s'il est accessible, sinon le fichier
`dessin.dxf`, enregistré après chaque demande.

## Conventions

- Unités : millimètres (dites « en mètres » ou « en cm » si besoin, l'assistant convertit).
- Repère : X vers la droite, Y vers le haut, angles en degrés.
- Couleurs de calque : numéros AutoCAD (1 rouge, 2 jaune, 3 vert, 4 cyan, 5 bleu…).

## Structure du code

| Fichier | Rôle |
|---|---|
| `autocad_assistant/backends.py` | Moteurs de dessin : AutoCAD (COM) et DXF (ezdxf) |
| `autocad_assistant/tools.py` | Outils proposés à Claude et leur exécution |
| `autocad_assistant/agent.py` | Boucle de conversation avec Claude |
| `autocad_assistant/gui.py` | Fenêtre de dialogue (tkinter) |
| `autocad_assistant/__main__.py` | Point d'entrée et options |

**Ajouter un outil** (ex. hachures, blocs) : ajoutez la méthode dans les deux moteurs
de `backends.py`, déclarez l'outil dans `TOOLS` et son exécution dans `_handlers`
(`tools.py`).

## Tests

```bash
pip install pytest
python -m pytest
```

Les tests simulent Claude et vérifient le fichier DXF produit ; ils ne consomment
pas de crédits API.
