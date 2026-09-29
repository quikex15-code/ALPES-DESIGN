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
| `--profils <dossier>` | Bibliothèque de profils (voir ci-dessous) |
| `--model <id>` | Autre modèle Claude (par défaut `claude-opus-5-5`) |

Par défaut (`--mode auto`), AutoCAD est utilisé s'il est accessible, sinon le fichier
`dessin.dxf`, enregistré après chaque demande.

## Bibliothèque de profils (Forster, etc.)

L'assistant peut chercher et insérer vos profils au lieu de les redessiner.

**1. Rangez les profils dans un dossier**, un fichier DWG (ou DXF) par profil.
Les sous-dossiers servent de série ; le nom du fichier est la référence :

```
C:\Profils\
  catalogue.csv              ← facultatif, mais recommandé
  Forster Unico\
    U1002.dwg
    U1003.dwg
  Forster Fuego Light\
    F2001.dwg
```

**2. (Facultatif) Ajoutez un `catalogue.csv`** à la racine, exporté depuis Excel
(séparateur `;` accepté). Seule la colonne `Reference` est obligatoire ; toutes
les autres colonnes (description, poids, inertie, usage…) sont transmises à
l'assistant pour qu'il choisisse le bon profil :

```
Reference;Description;Poids kg/m
U1002;Dormant ouvrant intérieur;2,1
F2001;Profilé coupe-feu EI30;3,4
```

**3. Lancez l'assistant en indiquant le dossier :**

```bat
python -m autocad_assistant --profils "C:\Profils"
```

ou une fois pour toutes : `setx ALPES_PROFILS "C:\Profils"`.

Vous pouvez alors demander : « Insère un dormant Forster Unico à l'origine et un
ouvrant à côté », « Quels profils coupe-feu EI30 as-tu ? », « Coupe verticale d'un
châssis de 1200 mm avec le profil U1002 en haut et en bas »…

Les profils sont insérés comme **blocs** (placés sur leur point de base, avec
rotation, symétrie et échelle possibles). L'assistant reçoit leur encombrement réel
pour aligner et coter la suite.

Formats : en mode AutoCAD, les profils doivent être en `.dwg`. En mode fichier DXF,
les `.dxf` sont lus directement ; les `.dwg` nécessitent l'outil gratuit
[ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter).

> Les fichiers de la bibliothèque restent sur votre ordinateur : inutile (et
> déconseillé, pour des questions de droits) de les ajouter à ce dépôt.

## Conventions

- Unités : millimètres (dites « en mètres » ou « en cm » si besoin, l'assistant convertit).
- Repère : X vers la droite, Y vers le haut, angles en degrés.
- Couleurs de calque : numéros AutoCAD (1 rouge, 2 jaune, 3 vert, 4 cyan, 5 bleu…).

## Structure du code

| Fichier | Rôle |
|---|---|
| `autocad_assistant/backends.py` | Moteurs de dessin : AutoCAD (COM) et DXF (ezdxf) |
| `autocad_assistant/tools.py` | Outils proposés à Claude et leur exécution |
| `autocad_assistant/profiles.py` | Bibliothèque de profils : lecture du dossier, catalogue, recherche |
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
