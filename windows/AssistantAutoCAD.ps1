# Assistant de dessin AutoCAD — version sans installation (Windows PowerShell 5.1+)
#
# Double-cliquez sur « Lancer-Assistant.bat » (même dossier) avec AutoCAD ouvert.
# Seule une clé API Anthropic est nécessaire ; elle est demandée au premier lancement.
#
# Fonctions : dessin (calques, lignes, polylignes, rectangles, cercles, arcs, textes,
# cotes), suppression, cadrage, enregistrement, cartouche de l'entreprise
# (entreprise.json) et bibliothèque de profils DWG (dossier « Profils » ou ALPES_PROFILS).

$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 : évite que les tableaux soient mal convertis en JSON.
try { Remove-TypeData System.Array -ErrorAction SilentlyContinue } catch { }

$script:Model = 'claude-opus-5-5'
$script:ApiUrl = 'https://api.anthropic.com/v1/messages'
$script:Here = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }

$script:SystemPrompt = @'
Tu es un assistant de dessin technique connecté à AutoCAD. L'utilisateur te décrit en langage naturel ce qu'il veut dessiner et tu le dessines avec les outils fournis.

Conventions :
- Unités : millimètres, sauf si l'utilisateur précise autre chose (convertis alors en mm).
- Repère : X vers la droite, Y vers le haut, angles en degrés dans le sens trigonométrique.
- Si l'utilisateur ne donne pas de position, place le dessin près de l'origine (0,0) et à côté des objets existants plutôt que par-dessus.
- Organise le dessin en calques parlants (ex. MURS, COTES, TEXTES, AXES) lorsque c'est utile.
- Pour modifier ou supprimer un objet existant, consulte d'abord list_entities.
- Si une demande est ambiguë au point de changer le résultat (dimension manquante indispensable, par exemple), pose une question courte. Sinon choisis des valeurs raisonnables et indique-les.
- À la fin, cadre la vue (zoom_extents) et résume en une ou deux phrases ce qui a été dessiné, avec les dimensions principales. Réponds en français.
- Cartouche : quand l'utilisateur demande un cartouche, un cadre, une mise en page ou un plan à imprimer, termine le dessin puis appelle draw_title_block en dernier (l'échelle se calcule sur le dessin existant). Déduis le titre du contexte si l'utilisateur ne le donne pas. Signale tout avertissement renvoyé (dessin qui dépasse du cadre).
'@

$script:ProfilesPrompt = @'

Bibliothèque de profils :
- Une bibliothèque de profils (menuiserie métallique Forster, etc.) est disponible. Quand l'utilisateur cite un profil, une série ou une référence, trouve la référence exacte avec search_profiles puis insère-la avec insert_profile. Ne redessine jamais à la main un profil qui existe dans la bibliothèque.
- Si plusieurs profils correspondent, propose les candidats à l'utilisateur plutôt que d'en choisir un au hasard.
- Sers-toi de l'encombrement renvoyé par insert_profile pour positionner les éléments suivants (assemblages, vitrages, cotes) au bon endroit.
'@

# ---------------------------------------------------------------------------
# Définition des outils proposés à Claude
# ---------------------------------------------------------------------------

function New-Tool($name, $description, $properties, $required) {
    [ordered]@{
        name         = $name
        description  = $description
        input_schema = [ordered]@{
            type                 = 'object'
            properties           = $properties
            required             = @($required)
            additionalProperties = $false
        }
    }
}

$Point = [ordered]@{ type = 'array'; items = @{ type = 'number' }; minItems = 2; maxItems = 3
                     description = 'Point [x, y] en unités du dessin (mm).' }
$Layer = [ordered]@{ type = 'string'; description = 'Calque (créé s''il n''existe pas). Facultatif.' }
$Num = @{ type = 'number' }
$Pos = [ordered]@{ type = 'number'; exclusiveMinimum = 0 }
$Str = @{ type = 'string' }

$script:Anchors = @('base', 'centre', 'bas_gauche', 'bas_droite', 'haut_gauche', 'haut_droite')
$script:Formats = [ordered]@{ A4 = @(297, 210); A3 = @(420, 297); A2 = @(594, 420); A1 = @(841, 594); A0 = @(1189, 841) }

$script:BaseTools = @(
    (New-Tool 'create_layer' 'Crée un calque (ou change sa couleur s''il existe déjà).' ([ordered]@{
        name = $Str
        color = [ordered]@{ type = 'integer'; minimum = 1; maximum = 255
                            description = 'Couleur AutoCAD (ACI) : 1 rouge, 2 jaune, 3 vert, 4 cyan, 5 bleu, 6 magenta, 7 blanc/noir, 8 gris.' }
    }) @('name', 'color')),
    (New-Tool 'draw_line' 'Dessine une ligne entre deux points.' ([ordered]@{ start = $Point; end = $Point; layer = $Layer }) @('start', 'end')),
    (New-Tool 'draw_polyline' 'Dessine une polyligne passant par une liste de points.' ([ordered]@{
        points = [ordered]@{ type = 'array'; items = $Point; minItems = 2 }
        closed = @{ type = 'boolean'; description = 'Ferme la polyligne.' }
        layer = $Layer
    }) @('points')),
    (New-Tool 'draw_rectangle' 'Dessine un rectangle à partir de son coin inférieur gauche.' ([ordered]@{
        corner = $Point; width = $Num; height = $Num; layer = $Layer }) @('corner', 'width', 'height')),
    (New-Tool 'draw_circle' 'Dessine un cercle.' ([ordered]@{ center = $Point; radius = $Pos; layer = $Layer }) @('center', 'radius')),
    (New-Tool 'draw_arc' 'Dessine un arc (sens trigonométrique, angles en degrés, 0° = axe X).' ([ordered]@{
        center = $Point; radius = $Pos; start_angle = $Num; end_angle = $Num; layer = $Layer
    }) @('center', 'radius', 'start_angle', 'end_angle')),
    (New-Tool 'draw_text' 'Écrit un texte sur une ligne.' ([ordered]@{
        position = $Point; text = $Str; height = $Pos
        rotation = @{ type = 'number'; description = 'Rotation en degrés.' }; layer = $Layer
    }) @('position', 'text', 'height')),
    (New-Tool 'draw_dimension' 'Ajoute une cote alignée entre deux points. offset > 0 place la cote à gauche du segment start→end (au-dessus pour un segment horizontal orienté vers la droite).' ([ordered]@{
        start = $Point; end = $Point; offset = $Num; layer = $Layer }) @('start', 'end', 'offset')),
    (New-Tool 'list_entities' 'Liste les objets du dessin (identifiant, type, calque). À utiliser avant de supprimer ou pour connaître le contenu existant.' ([ordered]@{}) @()),
    (New-Tool 'delete_entities' 'Supprime des objets par leurs identifiants (handles).' ([ordered]@{
        handles = [ordered]@{ type = 'array'; items = $Str; minItems = 1 } }) @('handles')),
    (New-Tool 'zoom_extents' 'Cadre la vue sur tout le dessin.' ([ordered]@{}) @()),
    (New-Tool 'save_drawing' 'Enregistre le dessin (chemin .dwg facultatif).' ([ordered]@{ path = $Str }) @()),
    (New-Tool 'draw_title_block' 'Dessine le cadre de la feuille et le cartouche de l''entreprise autour du dessin existant (à faire en dernier). L''ancien cartouche est remplacé. Si ''echelle'' est omise, l''échelle normalisée la plus grande qui fait tenir le dessin est choisie. Les textes du cartouche (nom, adresse, logo de l''entreprise) sont remplis automatiquement.' ([ordered]@{
        titre = @{ type = 'string'; description = 'Titre du plan.' }
        projet = @{ type = 'string'; description = 'Projet ou chantier.' }
        client = $Str; numero_plan = $Str
        indice = @{ type = 'string'; description = 'Indice de révision (A, B…).' }
        format = @{ type = 'string'; enum = @($script:Formats.Keys) }
        orientation = @{ type = 'string'; enum = @('paysage', 'portrait') }
        echelle = [ordered]@{ type = 'integer'; minimum = 1; description = 'Dénominateur de l''échelle : 20 pour 1:20.' }
        dessine_par = $Str
        date = @{ type = 'string'; description = 'Par défaut : aujourd''hui.' }
    }) @('titre'))
)

$script:ProfileTools = @(
    (New-Tool 'search_profiles' 'Cherche dans la bibliothèque de profils (Forster, etc.) par référence, série ou mots de la description. Requête vide = aperçu des séries disponibles.' ([ordered]@{ query = $Str }) @('query')),
    (New-Tool 'insert_profile' 'Insère un profil de la bibliothèque comme bloc. ''anchor'' indique quel point du profil est placé sur ''position'' (après rotation/symétrie). Retourne l''encombrement réel (min, max, largeur, hauteur) pour aligner ou coter la suite.' ([ordered]@{
        reference = @{ type = 'string'; description = 'Référence ou clé « série/référence » trouvée par search_profiles.' }
        position = $Point
        anchor = [ordered]@{ type = 'string'; enum = $script:Anchors
                             description = 'Point du profil placé sur ''position''. ''base'' = point de base du fichier DWG (par défaut). Utilise un coin ou ''centre'' si le point de base du fichier est éloigné du profil.' }
        rotation = @{ type = 'number'; description = 'Rotation en degrés.' }
        scale = [ordered]@{ type = 'number'; exclusiveMinimum = 0; description = 'Échelle (1 par défaut).' }
        mirror = @{ type = 'boolean'; description = 'Symétrie gauche/droite.' }
        layer = $Layer
    }) @('reference', 'position'))
)

# ---------------------------------------------------------------------------
# Configuration : entreprise et profils
# ---------------------------------------------------------------------------

function Read-TextFile($path) {
    # UTF-8 (avec ou sans BOM) ou ANSI (Excel en français).
    $bytes = [IO.File]::ReadAllBytes($path)
    try { return (New-Object Text.UTF8Encoding($false, $true)).GetString($bytes).TrimStart([char]0xFEFF) }
    catch { return [Text.Encoding]::GetEncoding(1252).GetString($bytes) }
}

function Get-Company {
    $company = [ordered]@{ nom = 'ALPES DESIGN'; adresse = @(); telephone = ''; email = ''; site = ''
                           logo = ''; dessinateur = ''; format_par_defaut = 'A3' }
    $candidates = @($env:ALPES_ENTREPRISE, (Join-Path $script:Here 'entreprise.json'),
                    (Join-Path (Split-Path $script:Here -Parent) 'entreprise.json'))
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c -PathType Leaf)) {
            $data = Read-TextFile $c | ConvertFrom-Json
            foreach ($p in $data.PSObject.Properties) { $company[$p.Name] = $p.Value }
            $company.adresse = @($company.adresse | Where-Object { $_ })
            if ($company.logo -and -not [IO.Path]::IsPathRooted($company.logo)) {
                $company.logo = Join-Path (Split-Path (Resolve-Path -LiteralPath $c) -Parent) $company.logo
            }
            break
        }
    }
    return $company
}

function ConvertTo-SearchText([string]$s) {
    $d = $s.Normalize([Text.NormalizationForm]::FormD)
    (-join ($d.ToCharArray() | Where-Object {
        [Globalization.CharUnicodeInfo]::GetUnicodeCategory($_) -ne 'NonSpacingMark' })).ToLower()
}

function Get-ProfileLibrary {
    $folder = @($env:ALPES_PROFILS, (Join-Path $script:Here 'Profils'),
                (Join-Path (Split-Path $script:Here -Parent) 'Profils')) |
        Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) } | Select-Object -First 1
    if (-not $folder) { return $null }
    $folder = (Resolve-Path -LiteralPath $folder).Path.TrimEnd('\', '/')

    $catalog = @{}
    foreach ($name in 'catalogue.csv', 'profils.csv', 'catalog.csv') {
        $path = Join-Path $folder $name
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $raw = Read-TextFile $path
        $delim = if (($raw.Split(';').Count) -ge ($raw.Split(',').Count)) { ';' } else { ',' }
        foreach ($row in ($raw | ConvertFrom-Csv -Delimiter $delim)) {
            $info = [ordered]@{}
            foreach ($p in $row.PSObject.Properties) { $info[$p.Name.Trim().ToLower()] = "$($p.Value)".Trim() }
            $ref = @($info['reference'], $info['référence'], $info['ref']) | Where-Object { $_ } | Select-Object -First 1
            if ($ref) { $catalog[(ConvertTo-SearchText $ref)] = $info }
        }
        break
    }

    $profiles = @(Get-ChildItem -LiteralPath $folder -Recurse -File |
        Where-Object { $_.Extension -eq '.dwg' } | Sort-Object FullName | ForEach-Object {
            $rel = $_.FullName.Substring($folder.Length + 1) -replace '\\', '/'
            $key = $rel.Substring(0, $rel.Length - $_.Extension.Length)
            $series = if ($key.Contains('/')) { $key.Substring(0, $key.LastIndexOf('/')) } else { '' }
            $info = $catalog[(ConvertTo-SearchText $_.BaseName)]
            [pscustomobject]@{ key = $key; reference = $_.BaseName; serie = $series; path = $_.FullName
                               info = $(if ($info) { $info } else { [ordered]@{} }) }
        })
    return [pscustomobject]@{ folder = $folder; profiles = $profiles }
}

function Get-ProfileSeries($lib) {
    $counts = [ordered]@{}
    foreach ($p in $lib.profiles) {
        $s = if ($p.serie) { $p.serie } else { '(racine)' }
        $counts[$s] = 1 + [int]$counts[$s]
    }
    return $counts
}

function Search-Profiles($lib, [string]$query) {
    $words = @((ConvertTo-SearchText $query) -split '\s+' | Where-Object { $_ })
    $found = @($lib.profiles | Where-Object {
        $hay = ConvertTo-SearchText ((@($_.key) + @($_.info.Values)) -join ' ')
        -not ($words | Where-Object { -not $hay.Contains($_) })
    })
    $list = @($found | Select-Object -First 40 | ForEach-Object {
        $s = [ordered]@{ reference = $_.reference; key = $_.key; serie = $_.serie }
        foreach ($k in $_.info.Keys) { if ($_.info[$k] -and $k -ne 'reference') { $s[$k] = $_.info[$k] } }
        $s
    })
    [ordered]@{ total = $found.Count; profils = $list; tronque = ($found.Count -gt 40)
                series_disponibles = (Get-ProfileSeries $lib) }
}

function Get-ProfileByRef($lib, [string]$reference) {
    $wanted = ConvertTo-SearchText ($reference.Trim() -replace '\\', '/')
    $byKey = @($lib.profiles | Where-Object { (ConvertTo-SearchText $_.key) -eq $wanted })
    if ($byKey.Count) { return $byKey[0] }
    $byRef = @($lib.profiles | Where-Object { (ConvertTo-SearchText $_.reference) -eq $wanted })
    if ($byRef.Count -eq 1) { return $byRef[0] }
    if ($byRef.Count -gt 1) {
        throw "Référence ambiguë « $reference », précisez la série : $(($byRef | ForEach-Object { $_.key }) -join ', ')"
    }
    throw "Profil « $reference » introuvable. Utilisez search_profiles."
}

# ---------------------------------------------------------------------------
# Dessin dans AutoCAD (COM)
# ---------------------------------------------------------------------------

function Connect-AutoCAD {
    $script:Acad = [Runtime.InteropServices.Marshal]::GetActiveObject('AutoCAD.Application')
    Update-ActiveDocument
}

function Update-ActiveDocument {
    if ($script:Acad.Documents.Count -eq 0) { [void]$script:Acad.Documents.Add() }
    $script:Doc = $script:Acad.ActiveDocument
    $script:Msp = $script:Doc.ModelSpace
}

function P($p) { , ([double[]]@([double]$p[0], [double]$p[1], 0.0)) }

function Round3($v) { [math]::Round([double]$v, 3) }

function New-BBox($mn, $mx) {
    [ordered]@{ min = @((Round3 $mn[0]), (Round3 $mn[1])); max = @((Round3 $mx[0]), (Round3 $mx[1]))
                largeur = (Round3 ($mx[0] - $mn[0])); hauteur = (Round3 ($mx[1] - $mn[1])) }
}

function Get-EntityBBox($ent) {
    $mn = $null; $mx = $null
    $ent.GetBoundingBox([ref]$mn, [ref]$mx)
    return (New-BBox $mn $mx)
}

function Set-Layer([string]$name, [int]$color = 0) {
    try { $layer = $script:Doc.Layers.Item($name) }
    catch { $layer = $script:Doc.Layers.Add($name); if (-not $color) { $color = 7 } }
    if ($color) { $layer.color = $color }
}

function Complete-Entity($ent, $layer) {
    if ($layer) { Set-Layer $layer; $ent.Layer = $layer }
    $ent.Update()
    return $ent.Handle
}

function Add-Polyline($points, [bool]$closed, $layer) {
    $flat = [double[]]@($points | ForEach-Object { [double]$_[0]; [double]$_[1] })
    $ent = $script:Msp.AddLightWeightPolyline($flat)
    $ent.Closed = $closed
    Complete-Entity $ent $layer
}

function Add-Text($pos, [string]$text, [double]$height, [double]$rotation, $layer) {
    $ent = $script:Msp.AddText($text, (P $pos), $height)
    $ent.Rotation = $rotation * [math]::PI / 180
    Complete-Entity $ent $layer
}

function Get-Entities {
    for ($i = 0; $i -lt $script:Msp.Count; $i++) {
        $e = $script:Msp.Item($i)
        [ordered]@{ handle = $e.Handle; type = $e.ObjectName; layer = $e.Layer }
    }
}

function Remove-Entities($handles) {
    $deleted = @()
    foreach ($h in $handles) {
        try { $script:Doc.HandleToObject($h).Delete(); $deleted += $h } catch { }
    }
    return $deleted
}

function Move-Entity($handle, [double]$dx, [double]$dy) {
    $ent = $script:Doc.HandleToObject($handle)
    $ent.Move((P @(0, 0)), (P @($dx, $dy)))
    $ent.Update()
}

function Insert-DwgBlock([string]$path, $position, [double]$rotation = 0, [double]$scale = 1,
                         [bool]$mirror = $false, $layer = $null) {
    $name = [IO.Path]::GetFileNameWithoutExtension($path)
    $source = $path
    try { [void]$script:Doc.Blocks.Item($name); $source = $name } catch { }  # déjà chargé
    $xs = if ($mirror) { -$scale } else { $scale }
    $ent = $script:Msp.InsertBlock((P $position), $source, $xs, $scale, $scale, $rotation * [math]::PI / 180)
    $handle = Complete-Entity $ent $layer
    return @{ handle = $handle; bbox = (Get-EntityBBox $ent) }
}

function Get-DrawingExtents([string[]]$excludeLayers) {
    $x0 = $y0 = [double]::MaxValue; $x1 = $y1 = [double]::MinValue; $any = $false
    for ($i = 0; $i -lt $script:Msp.Count; $i++) {
        $e = $script:Msp.Item($i)
        if ($excludeLayers -contains $e.Layer) { continue }
        try { $b = Get-EntityBBox $e } catch { continue }
        $any = $true
        $x0 = [math]::Min($x0, $b.min[0]); $y0 = [math]::Min($y0, $b.min[1])
        $x1 = [math]::Max($x1, $b.max[0]); $y1 = [math]::Max($y1, $b.max[1])
    }
    if (-not $any) { return $null }
    return (New-BBox @($x0, $y0) @($x1, $y1))
}

function Get-AnchorPoint($box, [string]$anchor) {
    $parts = $anchor.Split('_')
    $x = switch ($parts[-1]) { 'gauche' { $box.min[0] } 'droite' { $box.max[0] } default { ($box.min[0] + $box.max[0]) / 2 } }
    $y = switch ($parts[0]) { 'bas' { $box.min[1] } 'haut' { $box.max[1] } default { ($box.min[1] + $box.max[1]) / 2 } }
    return @($x, $y)
}

# ---------------------------------------------------------------------------
# Cartouche (même mise en page que la version Python)
# ---------------------------------------------------------------------------

$script:TbLayer = 'CARTOUCHE'
$script:Scales = @(1, 2, 5, 10, 20, 25, 50, 75, 100, 200, 250, 500, 1000, 2000, 5000)

function Draw-TitleBlock($company, $a) {
    $old = @(Get-Entities | Where-Object { $_.layer -eq $script:TbLayer } | ForEach-Object { $_.handle })
    if ($old.Count) { [void](Remove-Entities $old) }
    Set-Layer $script:TbLayer

    $fmt = @((Get-Arg $a 'format'), $company.format_par_defaut, 'A3') | Where-Object { $_ } | Select-Object -First 1
    if (-not $script:Formats.Contains($fmt)) { throw "Format inconnu : $fmt" }
    $w, $h = $script:Formats[$fmt]
    $orientation = Get-Arg $a 'orientation' 'paysage'
    if ($orientation -eq 'portrait') { $w, $h = $h, $w }
    $areaW = $w - 20; $areaH = $h - 20 - 45

    $drawing = Get-DrawingExtents @($script:TbLayer)
    $scale = Get-Arg $a 'echelle'
    $warning = $null
    if ($drawing) {
        if (-not $scale) {
            $scale = $script:Scales | Where-Object {
                $drawing.largeur / $_ -le $areaW * 0.9 -and $drawing.hauteur / $_ -le $areaH * 0.9 } |
                Select-Object -First 1
            if (-not $scale) { $scale = $script:Scales[-1]; $warning = "Dessin trop grand : il dépasse du cadre même au 1:$scale." }
        } elseif ($drawing.largeur / $scale -gt $areaW -or $drawing.hauteur / $scale -gt $areaH) {
            $warning = "Au 1:$scale, le dessin dépasse du cadre $fmt. Choisissez une échelle plus petite ou un format plus grand."
        }
        $cx = ($drawing.min[0] + $drawing.max[0]) / 2; $cy = ($drawing.min[1] + $drawing.max[1]) / 2
        $ox = $cx - (10 + $areaW / 2) * $scale; $oy = $cy - (55 + $areaH / 2) * $scale
    } else {
        if (-not $scale) { $scale = 1 }
        $ox = 0; $oy = 0
    }
    $k = [double]$scale
    $tbl = $script:TbLayer

    $rect = { param($bx, $by, $x0, $y0, $x1, $y1)
        [void](Add-Polyline @(@(($bx + $x0 * $k), ($by + $y0 * $k)), @(($bx + $x1 * $k), ($by + $y0 * $k)),
                              @(($bx + $x1 * $k), ($by + $y1 * $k)), @(($bx + $x0 * $k), ($by + $y1 * $k))) $true $tbl) }
    & $rect $ox $oy 0 0 $w $h
    & $rect $ox $oy 10 10 ($w - 10) ($h - 10)

    $tx = $ox + ($w - 10 - 180) * $k; $ty = $oy + 10 * $k
    $line = { param($x0, $y0, $x1, $y1)
        $e = $script:Msp.AddLine((P @(($tx + $x0 * $k), ($ty + $y0 * $k))), (P @(($tx + $x1 * $k), ($ty + $y1 * $k))))
        [void](Complete-Entity $e $tbl) }
    $text = { param($x, $y, $content, [double]$height, $maxWidth)
        if (-not $content) { return }
        if ($maxWidth) { $height = [math]::Min($height, $maxWidth / (0.75 * "$content".Length)) }
        [void](Add-Text @(($tx + $x * $k), ($ty + $y * $k)) "$content" ($height * $k) 0 $tbl) }

    & $rect $tx $ty 0 0 180 45
    & $line 60 0 60 45; & $line 135 0 135 45; & $line 60 15 180 15; & $line 60 30 180 30
    & $line 98 0 98 15; & $line 158 30 158 45

    # Colonne entreprise : logo, nom, coordonnées.
    $nameY = 35.0; $nameH = 6.0
    if ($company.logo -and (Test-Path -LiteralPath $company.logo)) {
        $first = Insert-DwgBlock $company.logo @(0, 0) 0 1 $false $tbl
        [void](Remove-Entities @($first.handle))
        $b = $first.bbox
        if ($b.largeur -gt 0 -and $b.hauteur -gt 0) {
            $f = [math]::Min(54 * $k / $b.largeur, 16 * $k / $b.hauteur)
            $logo = Insert-DwgBlock $company.logo @(0, 0) 0 $f $false $tbl
            $cxl = $tx + 30 * $k; $cyl = $ty + 35 * $k
            Move-Entity $logo.handle ($cxl - ($logo.bbox.min[0] + $logo.bbox.max[0]) / 2) ($cyl - ($logo.bbox.min[1] + $logo.bbox.max[1]) / 2)
            $nameY = 21.0; $nameH = 4.5
        }
    }
    & $text 3 $nameY $company.nom $nameH 54
    $y = $nameY - 5
    foreach ($infoLine in (@($company.adresse) + @($company.telephone, $company.email, $company.site) | Where-Object { $_ })) {
        if ($y -lt 2) { break }
        & $text 3 $y $infoLine 2.2 54; $y -= 3.5
    }

    $date = Get-Arg $a 'date' ((Get-Date).ToString('dd/MM/yyyy'))
    & $text 62 39 "PROJET : $(Get-Arg $a 'projet' '')" 2.5 71
    & $text 62 33 "CLIENT : $(Get-Arg $a 'client' '')" 2.5 71
    & $text 62 26.5 'TITRE' 1.8
    & $text 62 18.5 $a.titre 4.5 71
    & $text 62 11.5 'DESSINÉ PAR' 1.8
    & $text 62 4 (@((Get-Arg $a 'dessine_par'), $company.dessinateur) | Where-Object { $_ } | Select-Object -First 1) 2.5 34
    & $text 100 11.5 'DATE' 1.8
    & $text 100 4 $date 2.5 33
    & $text 137 41.5 'ÉCHELLE' 1.8
    & $text 137 33.5 "1:$scale" 3.5 19
    & $text 160 41.5 'FORMAT' 1.8
    & $text 160 33.5 $fmt 3.5 18
    & $text 137 26.5 'N° PLAN' 1.8
    & $text 137 18.5 (Get-Arg $a 'numero_plan' '') 4.5 41
    & $text 137 11.5 'INDICE' 1.8
    & $text 137 4 (Get-Arg $a 'indice' '') 3.5 41

    $result = [ordered]@{ format = "$fmt $orientation"; echelle = "1:$scale"
                          feuille = (New-BBox @($ox, $oy) @(($ox + $w * $k), ($oy + $h * $k)))
                          entreprise = $company.nom }
    if ($warning) { $result.avertissement = $warning }
    return $result
}

# ---------------------------------------------------------------------------
# Exécution des outils
# ---------------------------------------------------------------------------

function Get-Arg($a, [string]$name, $default = $null) {
    $p = $a.PSObject.Properties[$name]
    if ($p -and $null -ne $p.Value) { return $p.Value }
    return $default
}

function Invoke-DrawingTool([string]$name, $a) {
    $layer = Get-Arg $a 'layer'
    switch ($name) {
        'create_layer' { Set-Layer $a.name ([int]$a.color); return @{ layer = $a.name } }
        'draw_line' {
            $e = $script:Msp.AddLine((P $a.start), (P $a.end)); return @{ handle = (Complete-Entity $e $layer) } }
        'draw_polyline' { return @{ handle = (Add-Polyline $a.points ([bool](Get-Arg $a 'closed' $false)) $layer) } }
        'draw_rectangle' {
            $x = [double]$a.corner[0]; $y = [double]$a.corner[1]; $w = [double]$a.width; $h = [double]$a.height
            return @{ handle = (Add-Polyline @(@($x, $y), @(($x + $w), $y), @(($x + $w), ($y + $h)), @($x, ($y + $h))) $true $layer) } }
        'draw_circle' {
            $e = $script:Msp.AddCircle((P $a.center), [double]$a.radius); return @{ handle = (Complete-Entity $e $layer) } }
        'draw_arc' {
            $e = $script:Msp.AddArc((P $a.center), [double]$a.radius, ([double]$a.start_angle * [math]::PI / 180),
                                    ([double]$a.end_angle * [math]::PI / 180))
            return @{ handle = (Complete-Entity $e $layer) } }
        'draw_text' { return @{ handle = (Add-Text $a.position $a.text ([double]$a.height) ([double](Get-Arg $a 'rotation' 0)) $layer) } }
        'draw_dimension' {
            $s = $a.start; $t = $a.end
            $dx = $t[0] - $s[0]; $dy = $t[1] - $s[1]; $len = [math]::Sqrt($dx * $dx + $dy * $dy); if (-not $len) { $len = 1 }
            $o = [double]$a.offset
            $mid = @((($s[0] + $t[0]) / 2 - $dy / $len * $o), (($s[1] + $t[1]) / 2 + $dx / $len * $o))
            $e = $script:Msp.AddDimAligned((P $s), (P $t), (P $mid))
            return @{ handle = (Complete-Entity $e $layer) } }
        'list_entities' { return @{ entities = @(Get-Entities) } }
        'delete_entities' { $d = @(Remove-Entities $a.handles); $script:Doc.Regen(1); return @{ deleted = $d } }
        'zoom_extents' { $script:Acad.ZoomExtents(); return @{ ok = $true } }
        'save_drawing' {
            $path = Get-Arg $a 'path'
            if ($path) { $script:Doc.SaveAs([IO.Path]::GetFullPath($path)) } else { $script:Doc.Save() }
            return @{ saved_to = $script:Doc.FullName } }
        'draw_title_block' { return (Draw-TitleBlock $script:Company $a) }
        'search_profiles' { return (Search-Profiles $script:Library (Get-Arg $a 'query' '')) }
        'insert_profile' {
            $prof = Get-ProfileByRef $script:Library $a.reference
            $anchor = Get-Arg $a 'anchor' 'base'
            if ($script:Anchors -notcontains $anchor) { throw "anchor doit être l'une de ces valeurs : $($script:Anchors -join ', ')" }
            $r = Insert-DwgBlock $prof.path $a.position ([double](Get-Arg $a 'rotation' 0)) ([double](Get-Arg $a 'scale' 1)) ([bool](Get-Arg $a 'mirror' $false)) $layer
            $box = $r.bbox
            if ($anchor -ne 'base') {
                $ap = Get-AnchorPoint $box $anchor
                $dx = $a.position[0] - $ap[0]; $dy = $a.position[1] - $ap[1]
                Move-Entity $r.handle $dx $dy
                $box = New-BBox @(($box.min[0] + $dx), ($box.min[1] + $dy)) @(($box.max[0] + $dx), ($box.max[1] + $dy))
            }
            return [ordered]@{ handle = $r.handle; profil = $prof.key; encombrement = $box } }
        default { throw "Outil inconnu : $name" }
    }
}

function Invoke-ToolSafely([string]$name, $a) {
    $required = @(($script:Tools | Where-Object { $_.name -eq $name }).input_schema.required)
    $missing = @($required | Where-Object { -not $a.PSObject.Properties[$_] })
    if ($missing.Count) { return @{ text = "Arguments manquants : $($missing -join ', ')"; error = $true } }
    for ($try = 1; ; $try++) {
        try {
            $result = Invoke-DrawingTool $name $a
            return @{ text = (ConvertTo-Json -InputObject $result -Depth 10 -Compress); error = $false }
        } catch {
            # AutoCAD occupé (commande en cours) : on réessaie quelques fois.
            if ($_.Exception.ToString() -match '0x80010001|RPC_E_CALL_REJECTED' -and $try -lt 10) {
                Start-Sleep -Milliseconds 300; continue
            }
            return @{ text = "Erreur pendant '$name' : $($_.Exception.Message)"; error = $true }
        }
    }
}

# ---------------------------------------------------------------------------
# Dialogue avec Claude
# ---------------------------------------------------------------------------

function Invoke-Claude($body) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $json = ConvertTo-Json -InputObject $body -Depth 40 -Compress
    $headers = @{ 'x-api-key' = $env:ANTHROPIC_API_KEY; 'anthropic-version' = '2023-06-01'
                  'anthropic-beta' = 'server-side-fallback-2026-07-01' }
    try {
        $r = Invoke-WebRequest -Uri $script:ApiUrl -Method Post -Headers $headers -UseBasicParsing `
            -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($json)) -TimeoutSec 600
    } catch {
        $detail = if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { $_.Exception.Message }
        if ($detail -match 'authentication_error|invalid x-api-key') { $detail = 'Clé API invalide. Supprimez la variable ANTHROPIC_API_KEY puis relancez pour la saisir à nouveau.' }
        throw "Erreur de l'API Claude : $detail"
    }
    # Décodage UTF-8 explicite (accents).
    $text = [Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())
    return ($text | ConvertFrom-Json)
}

function Invoke-Assistant([string]$userText, [scriptblock]$onAction) {
    if ($script:Acad) { Update-ActiveDocument }
    $turnStart = $script:Messages.Count
    [void]$script:Messages.Add(@{ role = 'user'; content = $userText })

    for ($step = 0; $step -lt 40; $step++) {
        $response = Invoke-Claude ([ordered]@{
            model = $script:Model; max_tokens = 16000; system = $script:System
            tools = $script:Tools; messages = $script:Messages
            output_config = @{ effort = 'medium' }; fallbacks = 'default'
        })

        if ($response.stop_reason -eq 'refusal') {
            $script:Messages.RemoveRange($turnStart, $script:Messages.Count - $turnStart)
            return 'Désolé, je ne peux pas traiter cette demande. Reformulez-la.'
        }
        # Contenu complet renvoyé tel quel (réflexion + appels d'outils).
        [void]$script:Messages.Add(@{ role = 'assistant'; content = @($response.content) })

        $calls = @($response.content | Where-Object { $_.type -eq 'tool_use' })
        if ($response.stop_reason -ne 'tool_use' -or $calls.Count -eq 0) {
            $text = (@($response.content | Where-Object { $_.type -eq 'text' } | ForEach-Object { $_.text }) -join "`n").Trim()
            if ($response.stop_reason -eq 'max_tokens') { $text += "`n(Réponse tronquée : la limite de longueur a été atteinte.)" }
            if ($text) { return $text } else { return "C'est fait." }
        }

        $results = New-Object Collections.ArrayList
        foreach ($call in $calls) {
            $toolArgs = if ($call.input) { $call.input } else { [pscustomobject]@{} }
            $out = Invoke-ToolSafely $call.name $toolArgs
            if ($onAction) { & $onAction $call.name $toolArgs $out.text $out.error }
            [void]$results.Add([ordered]@{ type = 'tool_result'; tool_use_id = $call.id
                                           content = $out.text; is_error = $out.error })
        }
        [void]$script:Messages.Add(@{ role = 'user'; content = $results })
    }
    return "J'ai atteint le nombre maximal d'étapes pour cette demande. Précisez la suite."
}

function Initialize-Assistant {
    $script:Company = Get-Company
    $script:Library = Get-ProfileLibrary
    $script:Tools = @($script:BaseTools)
    $script:System = $script:SystemPrompt
    if ($script:Library) {
        $script:Tools += $script:ProfileTools
        $script:System += $script:ProfilesPrompt
    }
    $script:Messages = New-Object Collections.ArrayList
}

# ---------------------------------------------------------------------------
# Fenêtre de dialogue
# ---------------------------------------------------------------------------

function Get-ApiKey {
    if ($env:ANTHROPIC_API_KEY) { return $true }
    $saved = [Environment]::GetEnvironmentVariable('ANTHROPIC_API_KEY', 'User')
    if (-not $saved) {
        Add-Type -AssemblyName Microsoft.VisualBasic
        $saved = [Microsoft.VisualBasic.Interaction]::InputBox(
            "Collez votre clé API Anthropic (commence par sk-ant-).`nElle sera mémorisée pour les prochains lancements.",
            'Assistant AutoCAD — clé API', '').Trim()
        if (-not $saved) { return $false }
        [Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', $saved, 'User')
    }
    $env:ANTHROPIC_API_KEY = $saved
    return $true
}

function Show-Window {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    [Windows.Forms.Application]::EnableVisualStyles()

    if (-not (Get-ApiKey)) { return }
    try { Connect-AutoCAD }
    catch {
        [void][Windows.Forms.MessageBox]::Show("AutoCAD n'est pas ouvert (ou pas accessible).`nOuvrez AutoCAD avec un dessin, puis relancez l'assistant.",
                                              'Assistant AutoCAD', 'OK', 'Warning')
        return
    }
    Initialize-Assistant

    $form = New-Object Windows.Forms.Form
    $form.Text = 'Assistant de dessin AutoCAD — ' + $script:Company.nom
    $form.Size = New-Object Drawing.Size(640, 720)
    $form.TopMost = $true   # reste visible au-dessus d'AutoCAD
    $form.StartPosition = 'CenterScreen'

    $script:Log = New-Object Windows.Forms.RichTextBox
    $script:Log.Dock = 'Fill'; $script:Log.ReadOnly = $true; $script:Log.BackColor = [Drawing.Color]::White
    $script:Log.Font = New-Object Drawing.Font('Segoe UI', 10)

    $bottom = New-Object Windows.Forms.Panel
    $bottom.Dock = 'Bottom'; $bottom.Height = 70; $bottom.Padding = New-Object Windows.Forms.Padding(6)
    $script:Entry = New-Object Windows.Forms.TextBox
    $script:Entry.Multiline = $true; $script:Entry.Dock = 'Fill'
    $script:Entry.Font = New-Object Drawing.Font('Segoe UI', 10)
    $script:SendButton = New-Object Windows.Forms.Button
    $script:SendButton.Text = 'Envoyer'; $script:SendButton.Dock = 'Right'; $script:SendButton.Width = 90
    $bottom.Controls.Add($script:Entry); $bottom.Controls.Add($script:SendButton)
    $form.Controls.Add($script:Log); $form.Controls.Add($bottom)

    $profils = if ($script:Library) { "Bibliothèque de profils : $($script:Library.profiles.Count) profils`n" } else { '' }
    Write-Log ("Connecté à AutoCAD : $($script:Doc.Name)`n$profils`n" +
               "Décrivez ce que vous voulez dessiner, par exemple :`n" +
               "  • « Dessine une pièce de 4 m sur 3 m avec des murs de 20 cm et cote-la »`n" +
               "  • « Une platine 200×150 avec 4 trous Ø12 à 20 mm des bords »`n" +
               "  • « Ajoute le cartouche en A3, plan n° 12, client Dupont »`n" +
               "Entrée : envoyer — Maj+Entrée : nouvelle ligne`n`n") ([Drawing.Color]::Black)

    $script:SendButton.Add_Click({ Send-Message })
    $script:Entry.Add_KeyDown({
        param($s, $e)
        if ($e.KeyCode -eq 'Return' -and -not $e.Shift) { $e.SuppressKeyPress = $true; Send-Message }
    })
    $form.Add_Shown({ $script:Entry.Focus() })
    [void]$form.ShowDialog()
}

function Write-Log([string]$text, [Drawing.Color]$color, [bool]$bold = $false) {
    $log = $script:Log
    $log.SelectionStart = $log.TextLength; $log.SelectionLength = 0
    $log.SelectionColor = $color
    $style = if ($bold) { [Drawing.FontStyle]::Bold } else { [Drawing.FontStyle]::Regular }
    $log.SelectionFont = New-Object Drawing.Font('Segoe UI', 10, $style)
    $log.AppendText($text)
    $log.ScrollToCaret()
    [Windows.Forms.Application]::DoEvents()
}

function Send-Message {
    $text = $script:Entry.Text.Trim()
    if (-not $text -or -not $script:SendButton.Enabled) { return }
    $script:Entry.Clear(); $script:SendButton.Enabled = $false; $script:SendButton.Text = '…'
    Write-Log "Vous : $text`n" ([Drawing.Color]::RoyalBlue) $true
    Write-Log "(l'assistant réfléchit…)`n" ([Drawing.Color]::Gray)
    $onAction = {
        param($name, $toolArgs, $result, $isError)
        $argsJson = ConvertTo-Json -InputObject $toolArgs -Depth 10 -Compress
        if ($isError) { Write-Log "  ▸ $name $argsJson  → $result`n" ([Drawing.Color]::Firebrick) }
        else { Write-Log "  ▸ $name $argsJson`n" ([Drawing.Color]::Gray) }
    }
    try {
        $reply = Invoke-Assistant $text $onAction
        Write-Log "$reply`n`n" ([Drawing.Color]::Black)
    } catch {
        Write-Log "Erreur : $($_.Exception.Message)`n`n" ([Drawing.Color]::Firebrick)
    }
    $script:SendButton.Enabled = $true; $script:SendButton.Text = 'Envoyer'; [void]$script:Entry.Focus()
}

# Lancement direct (pas lors d'un chargement par « . » pour les tests).
if ($MyInvocation.InvocationName -ne '.') {
    try { Show-Window }
    catch {
        Add-Type -AssemblyName System.Windows.Forms
        [void][Windows.Forms.MessageBox]::Show("Erreur inattendue :`n$($_.Exception.Message)", 'Assistant AutoCAD', 'OK', 'Error')
    }
}
