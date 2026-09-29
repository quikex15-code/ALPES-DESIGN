# Test de windows/AssistantAutoCAD.ps1 avec un faux AutoCAD et un faux Claude.
# Lancement : pwsh -NoProfile -File tests/test_windows_script.ps1   (code retour 0 = OK)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..' 'windows' 'AssistantAutoCAD.ps1')

$script:failures = 0
function Check($cond, $msg) { if (-not $cond) { Write-Host "ÉCHEC : $msg"; $script:failures++ } }

# --- Faux AutoCAD -----------------------------------------------------------
$script:NextHandle = 100
$script:Entities = New-Object Collections.ArrayList
$script:LayerTable = @{}

function New-FakeEntity($type, [double[]]$mn, [double[]]$mx) {
    $e = [pscustomobject]@{ ObjectName = $type; Handle = ('{0:X}' -f $script:NextHandle++); Layer = '0'
                            Closed = $false; Rotation = 0.0; mn = $mn; mx = $mx; Name = '' }
    $e | Add-Member ScriptMethod Update { }
    $e | Add-Member ScriptMethod Delete { $script:Entities.Remove($this) }
    $e | Add-Member ScriptMethod Move { param($a, $b)
        $dx = $b[0] - $a[0]; $dy = $b[1] - $a[1]
        $this.mn = [double[]]@(($this.mn[0] + $dx), ($this.mn[1] + $dy), 0)
        $this.mx = [double[]]@(($this.mx[0] + $dx), ($this.mx[1] + $dy), 0) }
    $e | Add-Member ScriptMethod GetBoundingBox { param($rmn, $rmx) $rmn.Value = $this.mn; $rmx.Value = $this.mx }
    [void]$script:Entities.Add($e)
    return $e
}
function MinMax($pts) {
    $xs = $pts | ForEach-Object { $_[0] }; $ys = $pts | ForEach-Object { $_[1] }
    return @([double[]]@(($xs | Measure-Object -Minimum).Minimum, ($ys | Measure-Object -Minimum).Minimum, 0),
             [double[]]@(($xs | Measure-Object -Maximum).Maximum, ($ys | Measure-Object -Maximum).Maximum, 0))
}

$msp = [pscustomobject]@{}
$msp | Add-Member ScriptProperty Count { $script:Entities.Count }
$msp | Add-Member ScriptMethod Item { param($i) $script:Entities[$i] }
$msp | Add-Member ScriptMethod AddLine { param($a, $b)
    Check ($a -is [double[]]) 'AddLine attend des double[]'
    $m = MinMax @($a, $b); New-FakeEntity 'AcDbLine' $m[0] $m[1] }
$msp | Add-Member ScriptMethod AddCircle { param($c, $r) New-FakeEntity 'AcDbCircle' @(($c[0] - $r), ($c[1] - $r), 0) @(($c[0] + $r), ($c[1] + $r), 0) }
$msp | Add-Member ScriptMethod AddArc { param($c, $r, $s, $e) New-FakeEntity 'AcDbArc' @(($c[0] - $r), ($c[1] - $r), 0) @(($c[0] + $r), ($c[1] + $r), 0) }
$msp | Add-Member ScriptMethod AddText { param($t, $p, $h)
    $e = New-FakeEntity 'AcDbText' @($p[0], $p[1], 0) @(($p[0] + $h * $t.Length * 0.7), ($p[1] + $h), 0)
    $e | Add-Member NoteProperty TextString $t; $e }
$msp | Add-Member ScriptMethod AddLightWeightPolyline { param($flat)
    Check ($flat -is [double[]]) 'polyligne : double[] attendu'
    $pts = for ($i = 0; $i -lt $flat.Length; $i += 2) { , @($flat[$i], $flat[$i + 1]) }
    $m = MinMax $pts; New-FakeEntity 'AcDbPolyline' $m[0] $m[1] }
$msp | Add-Member ScriptMethod AddDimAligned { param($a, $b, $t) $m = MinMax @($a, $b, $t); New-FakeEntity 'AcDbAlignedDimension' $m[0] $m[1] }
$msp | Add-Member ScriptMethod InsertBlock { param($p, $src, $xs, $ys, $zs, $rot)
    # Bloc de 60 × 70 dont le dessin est décalé de (500, 300) par rapport au point de base.
    $sx = [math]::Abs($xs)
    $e = New-FakeEntity 'AcDbBlockReference' @(($p[0] + 500 * $sx), ($p[1] + 300 * $sx), 0) @(($p[0] + 560 * $sx), ($p[1] + 370 * $sx), 0)
    $e.Name = $src; $e }

$layers = [pscustomobject]@{}
$layers | Add-Member ScriptMethod Item { param($n) if ($script:LayerTable.ContainsKey($n)) { $script:LayerTable[$n] } else { throw 'absent' } }
$layers | Add-Member ScriptMethod Add { param($n) $script:LayerTable[$n] = [pscustomobject]@{ Name = $n; color = 7 }; $script:LayerTable[$n] }
$blocks = [pscustomobject]@{}
$blocks | Add-Member ScriptMethod Item { param($n) throw 'absent' }

$script:Doc = [pscustomobject]@{ Layers = $layers; Blocks = $blocks; Name = 'Dessin1.dwg'; FullName = 'C:\Dessin1.dwg' }
$script:Doc | Add-Member ScriptMethod HandleToObject { param($h) $script:Entities | Where-Object { $_.Handle -eq $h } | Select-Object -First 1 }
$script:Doc | Add-Member ScriptMethod Regen { param($x) }
$script:Msp = $msp
$script:Zoomed = $false

# --- Faux Claude ------------------------------------------------------------
$script:Requests = New-Object Collections.ArrayList
$script:Replies = New-Object Collections.Queue
function Invoke-Claude($body) {
    $json = ConvertTo-Json -InputObject $body -Depth 40 -Compress
    [void]$script:Requests.Add(($json | ConvertFrom-Json))
    return ($script:Replies.Dequeue() | ConvertFrom-Json)
}

# --- Profils et entreprise ---------------------------------------------------
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("alpes-test-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path (Join-Path $tmp 'Profils/Forster Unico') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $tmp 'Profils/Divers') -Force | Out-Null
'x' | Set-Content (Join-Path $tmp 'Profils/Forster Unico/U1002.dwg')
'x' | Set-Content (Join-Path $tmp 'Profils/Forster Unico/U1001.dwg')
'x' | Set-Content (Join-Path $tmp 'Profils/Divers/U1001.dwg')
[IO.File]::WriteAllBytes((Join-Path $tmp 'Profils/catalogue.csv'),
    [Text.Encoding]::GetEncoding(1252).GetBytes("Référence;Description`r`nU1002;Dormant ouvrant intérieur`r`n"))
[IO.File]::WriteAllText((Join-Path $tmp 'entreprise.json'),
    '{"nom": "ALPES DESIGN", "adresse": ["Genève, Suisse"], "telephone": "+41 78 250 58 09", "dessinateur": "J. Martin"}')
$env:ALPES_PROFILS = Join-Path $tmp 'Profils'
$env:ALPES_ENTREPRISE = Join-Path $tmp 'entreprise.json'

Initialize-Assistant
Check ($script:Tools.Count -eq 15) "15 outils attendus, obtenu $($script:Tools.Count)"
Check ($script:Company.nom -eq 'ALPES DESIGN' -and $script:Company.adresse[0] -eq 'Genève, Suisse') 'entreprise.json'
Check ($script:Library.profiles.Count -eq 3) 'profils'
$s = Search-Profiles $script:Library 'dormant interieur'
Check ($s.total -eq 1 -and $s.profils[0].key -eq 'Forster Unico/U1002' -and $s.profils[0].description -eq 'Dormant ouvrant intérieur') 'recherche + catalogue ANSI'
$err = $null; try { Get-ProfileByRef $script:Library 'U1001' } catch { $err = "$_" }
Check ($err -match 'ambiguë') 'référence ambiguë'

# --- Conversation complète ----------------------------------------------------
$script:Replies.Enqueue(@'
{"stop_reason":"tool_use","content":[
 {"type":"thinking","thinking":"","signature":"sig=="},
 {"type":"text","text":"Je dessine."},
 {"type":"tool_use","id":"t1","name":"create_layer","input":{"name":"MURS","color":1}},
 {"type":"tool_use","id":"t2","name":"draw_rectangle","input":{"corner":[0,0],"width":4000,"height":3000,"layer":"MURS"}},
 {"type":"tool_use","id":"t3","name":"draw_circle","input":{"center":[2000,1500],"radius":300}},
 {"type":"tool_use","id":"t4","name":"draw_dimension","input":{"start":[0,0],"end":[4000,0],"offset":-500,"layer":"COTES"}},
 {"type":"tool_use","id":"t5","name":"draw_text","input":{"position":[100,100],"text":"SÉJOUR","height":200}},
 {"type":"tool_use","id":"t6","name":"insert_profile","input":{"reference":"U1002","position":[5000,0],"anchor":"bas_gauche"}},
 {"type":"tool_use","id":"t7","name":"draw_circle","input":{"center":[0,0]}}
]}
'@)
$script:Replies.Enqueue(@'
{"stop_reason":"tool_use","content":[
 {"type":"tool_use","id":"t8","name":"draw_title_block","input":{"titre":"Plan du séjour","client":"Dupont","numero_plan":"12","date":"01/10/2026"}},
 {"type":"tool_use","id":"t9","name":"zoom_extents","input":{}}
]}
'@)
$script:Replies.Enqueue('{"stop_reason":"end_turn","content":[{"type":"text","text":"Pièce de 4 × 3 m dessinée."}]}')

$script:Acad = $null
function Update-ActiveDocument { }
$script:Acad = [pscustomobject]@{}
$script:Acad | Add-Member ScriptMethod ZoomExtents { $script:Zoomed = $true }

$actions = New-Object Collections.ArrayList
$reply = Invoke-Assistant 'Dessine une pièce' { param($n, $a, $r, $e) [void]$actions.Add(@($n, $r, $e)) }

Check ($reply -eq 'Pièce de 4 × 3 m dessinée.') "réponse finale : $reply"
Check ($actions.Count -eq 9) "9 actions attendues, obtenu $($actions.Count)"
$errors = @($actions | Where-Object { $_[2] })
Check ($errors.Count -eq 1 -and $errors[0][0] -eq 'draw_circle' -and $errors[0][1] -match 'radius') "seule l'erreur de rayon manquant attendue : $($errors | ForEach-Object { $_[1] })"
Check ($script:LayerTable['MURS'].color -eq 1) 'couleur du calque'
Check ($script:Zoomed) 'zoom'

$profile = ($actions | Where-Object { $_[0] -eq 'insert_profile' })[1] | ConvertFrom-Json
Check (($profile.encombrement.min -join ',') -eq '5000,0') "profil placé par son coin : $($profile.encombrement.min -join ',')"

$tb = ($actions | Where-Object { $_[0] -eq 'draw_title_block' })[1] | ConvertFrom-Json
Check ($tb.echelle -eq '1:20' -and $tb.format -eq 'A3 paysage') "cartouche : $($tb.echelle) $($tb.format)"
$texts = @($script:Entities | Where-Object { $_.Layer -eq 'CARTOUCHE' -and $_.ObjectName -eq 'AcDbText' } | ForEach-Object { $_.TextString })
foreach ($t in 'ALPES DESIGN', 'Genève, Suisse', '+41 78 250 58 09', 'Plan du séjour', 'CLIENT : Dupont', '12', '1:20', 'J. Martin', '01/10/2026') {
    Check ($texts -contains $t) "texte du cartouche manquant : $t"
}

# Requêtes envoyées : historique complet, résultats groupés, paramètres.
$second = $script:Requests[1]
Check ($second.model -eq 'claude-opus-5-5' -and $second.fallbacks -eq 'default' -and $second.output_config.effort -eq 'medium') 'paramètres de requête'
Check (($second.messages | ForEach-Object { $_.role }) -join ',' -eq 'user,assistant,user') 'rôles'
Check ($second.messages[1].content[0].type -eq 'thinking' -and $second.messages[1].content[0].signature -eq 'sig==') 'réflexion renvoyée telle quelle'
Check ($second.messages[2].content.Count -eq 7) 'les 7 résultats dans un seul message'
Check ($second.messages[2].content[6].is_error -eq $true) 'erreur signalée'
$listTool = $second.tools | Where-Object { $_.name -eq 'list_entities' }
Check ($listTool.input_schema.required -is [array] -and $listTool.input_schema.required.Count -eq 0) 'required vide = tableau'
$json = ConvertTo-Json -InputObject $script:Messages -Depth 40 -Compress
Check ($json -notmatch '"value":\[') 'pas de tableaux mal convertis'
Check ($json.Contains('SÉJOUR')) 'accents conservés'

# Refus : la demande est retirée de l'historique.
$before = $script:Messages.Count
$script:Replies.Enqueue('{"stop_reason":"tool_use","content":[{"type":"tool_use","id":"t10","name":"zoom_extents","input":{}}]}')
$script:Replies.Enqueue('{"stop_reason":"refusal","content":[]}')
$r = Invoke-Assistant '…' $null
Check ($script:Messages.Count -eq $before -and $r -match 'Désolé') 'refus'

Remove-Item -Recurse -Force $tmp
if ($script:failures) { Write-Host "$($script:failures) échec(s)"; exit 1 }
Write-Host 'Tous les tests PowerShell sont passés.'
