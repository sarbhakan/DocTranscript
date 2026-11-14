# P0 · Banc de reconnaissance vocale hors ligne

Ce lot compare le délai de réponse des **moteurs**, leur consommation et leur fidélité sur les mêmes WAV. Les configurations sont des comparateurs de développement pour choisir le moteur de l’unique application, pas des éditions livrées. Le banc fonctionne sans cloud ni téléchargement à l’exécution. L’éditeur WPF, la latence réelle à l’écran, la capture WASAPI, les interactions et le stockage des notes auront leurs tests propres en P1. Les résultats de P0 sont des mesures techniques sur cas fictifs.

- [Procédure sur deux PC Windows](../docs/p0-windows.md) : inventaire, conditions de mesure, essais, traces réseau et recette indépendante.
- [Contrat et métriques du banc](bench/README.md) : protocole du worker, options, fichiers et règles de calcul.
- [Essai du micro sur Mac](bench/macos-smoke.md) : affichage en direct, fidélité médicale et sauvegarde après relance. Voir aussi [les résultats Mac et le comparatif local](../docs/p0-macos-dictee.md).
- [Banc moteur enrichi et choix du candidat Windows](asr_benchmark.md) : mêmes fichiers, doses et fractions séparées, comparaison du découpage, résultats Mac et procédure exacte Windows.
- [Comparatif historique Whisper–UltiMed pour le pilote Mac](../docs/p0-choix-moteur.md) : lot PxCorpus, résultats et préparation du rejeu.
- [Corpus fictif](corpus/README.md) : scripts, attributs à relire, génération des contrôles, constitution du jeu inédit.
- [Portes de validation des lots suivants](../docs/recette-iterative.md) : interface, interaction, intégrité de la base et transfert.

## 1. Préparer une seule distribution de test

Sur une **machine de préparation Windows x64 connectée**, utiliser CPython **3.12 x64** complet déjà approuvé, avec `pip`. Les versions directes sont épinglées. Les [wheels Sherpa](https://pypi.org/project/sherpa-onnx/2.0.1/#files) et [pywhispercpp](https://pypi.org/project/pywhispercpp/1.5.1/#files) sont publiées pour cette cible. Le banc lui-même n’a pas de dépendance tierce ; les deux liaisons natives sont nécessaires uniquement pour les moteurs réels. Aucun des modules du plugin Dev Toolkit Orchestrator n’est une dépendance du banc.

Depuis la racine du projet, sur la machine de préparation :

```powershell
$Python = 'C:\Chemin\Vers\Python312\python.exe'
$Lot = 'D:\NoteVive-P0'
$Wheelhouse = Join-Path $Lot 'wheelhouse'
$Lock = Join-Path $Lot 'requirements-win.lock'
New-Item -ItemType Directory -Path $Wheelhouse -Force | Out-Null
# Partir d'un wheelhouse vide. Telecharge des wheels, ne les installe pas.
& $Python -m pip download --disable-pip-version-check --only-binary=:all: --dest $Wheelhouse -r p0\requirements-win.txt
if ($LASTEXITCODE -ne 0) { throw 'Preparation des wheels incomplete' }
& $Python -m p0.packs.lock_wheels $Wheelhouse $Lock
if ($LASTEXITCODE -ne 0) { throw 'Verrouillage des wheels incomplet' }
```

Vérifier les fichiers récupérés, leur provenance, leurs licences et les empreintes publiées avant de sceller le lot. Le verrou généré enregistre les fichiers reçus ; il ne certifie pas leur provenance. Garder la **même** arborescence, le même verrou, les mêmes wheels, le même code et le même corpus pour W1/W2. Ne pas mettre les dépendances, les packs, les voix et les résultats individuels dans Git. La [recette Windows](../docs/p0-windows.md#1-préparer-le-lot-sur-un-poste-connecté-distinct) détaille la preuve de transfert.

## 2. Préparer quatre packs locaux

Télécharger les modèles sur la machine de préparation. Dans `$Lot\packs`, créer un dossier par ligne. Extraire les archives sur la machine de préparation, puis copier les fichiers nommés par le gabarit à la racine du dossier du pack (pas de dossier d’archive intercalé). Les notices amont doivent accompagner le lot. Garder la révision ou la date de chaque source et les empreintes des archives d’origine. Pour Whisper, choisir le modèle multilingue **`q5_1`** publié, sans suffixe `.en`.

| Dossier du pack | Adaptateur | Artefact de départ | Comparaison |
| --- | --- | --- | --- |
| `sherpa-nemotron` | `sherpa` | [Nemotron 3.5 multilingue INT8 560 ms](https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11.tar.bz2) · [poids OpenMDW 1.1](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b) | Flux natif, `fr-FR`. |
| `sherpa-zipformer` | `sherpa` | [Zipformer français](https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-fr-2023-04-14.tar.bz2) · [checkpoint Apache-2.0](https://huggingface.co/shaojieli/icefall-asr-commonvoice-fr-pruned-transducer-stateless7-streaming-2023-04-02) | Flux natif, encodeur et jointure INT8, décodeur FP32 comme dans l’exemple amont. |
| `whisper-small-q5` | `whisper` | [`ggml-small-q5_1.bin`, sélectionner et consigner la révision](https://huggingface.co/ggerganov/whisper.cpp/tree/main) · [Whisper MIT](https://github.com/openai/whisper#license) | Référence par fenêtres, redécodage chaque seconde, fenêtre de 10 s non chevauchante, contexte réinitialisé. Le modèle reste chargé. Les erreurs de jonction font partie de ce résultat. |
| `sherpa-parakeet` | `sherpa-final` | [Parakeet TDT v3 INT8](https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2) · [poids CC BY 4.0](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | Référence finale uniquement ; ne classer ni son premier mot ni son délai comme moteur en direct. |

```powershell
$Names = 'sherpa-nemotron', 'sherpa-zipformer', 'whisper-small-q5', 'sherpa-parakeet'
foreach ($Name in $Names) {
    $Pack = Join-Path (Join-Path $Lot 'packs') $Name
    Copy-Item -LiteralPath "p0\packs\$Name.json" -Destination (Join-Path $Pack 'pack.json')
    & $Python -m p0.packs seal $Pack
    if ($LASTEXITCODE -ne 0) { throw "Pack incomplet ou deja scelle : $Name" }
}
```

`seal` crée `pack.sha256.json` et refuse de le remplacer ; une variante de test doit partir d’un nouveau dossier de pack. Chaque PC rejoue `verify` **avant** la campagne et conserve le SHA-256 du manifeste. Le worker vérifie la configuration et la taille des poids au lancement, puis reporte l’empreinte du manifeste sans rehacher les modèles dans le chronomètre. Ne plus modifier le dossier après `verify` ; après tout changement, invalider les résultats concernés. Ces contrôles servent à la reproductibilité du banc ; la signature et la protection du pack en production sont à qualifier séparément.

UltiMed utilise un [adaptateur dédié](adapters/ultimed.md) : son export ONNX n’est pas interchangeable avec celui de sherpa-onnx. Les quatre packs historiques restent disponibles pour le banc ; le [comparatif direct](../docs/p0-choix-moteur.md) documente les configurations Whisper Turbo et UltiMed et le choix du candidat d’intégration.

## 3. Préparer et exécuter sur chaque PC hors ligne

Utiliser un compte Windows standard. Avec le lot vérifié et CPython 3.12 x64 déjà disponible, depuis la racine du dépôt :

```powershell
$Lot = 'D:\NoteVive-P0'
$BasePython = 'C:\Chemin\Vers\Python312\python.exe'
& $BasePython -m venv (Join-Path $Lot 'venv')
if ($LASTEXITCODE -ne 0) { throw 'Creation du venv impossible' }
$Python = Join-Path $Lot 'venv\Scripts\python.exe'
$Wheelhouse = Join-Path $Lot 'wheelhouse'
& $Python -m pip --isolated install --disable-pip-version-check --no-index --only-binary=:all: --find-links $Wheelhouse --require-hashes -r (Join-Path $Lot 'requirements-win.lock')
if ($LASTEXITCODE -ne 0) { throw 'Installation hors ligne incomplete' }
& $Python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependances incoherentes' }
foreach ($Name in 'sherpa-nemotron', 'sherpa-zipformer', 'whisper-small-q5', 'sherpa-parakeet') {
    & $Python -m p0.packs verify (Join-Path (Join-Path $Lot 'packs') $Name)
    if ($LASTEXITCODE -ne 0) { throw "Pack refuse : $Name" }
}
```

En cas de DLL manquante, relever la wheel, l’architecture et l’erreur et la faire résoudre avec le parc (par exemple le runtime [Visual C++](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) s’il est effectivement requis). Ne pas tenter de remplacer une DLL individuellement ni contourner une politique d’entreprise. La machine de préparation n’est pas la machine de preuve. Passer ensuite à la [séquence Windows](../docs/p0-windows.md#4-exécuter-le-même-protocole), avec le CSV révisé d’après les WAV réels fictifs, et vérifier le fonctionnement en l’absence de réseau.

## 4. Vérifier le banc sans charger de modèle

Cette vérification utilise les quatre WAV synthétiques **sans parole**. Le worker est simulé et les résultats sont marqués comme tels. Aucun score n’est une mesure ASR.

```powershell
$Scratch = Join-Path $env:LOCALAPPDATA 'NoteVive-P0\smoke-r1'
$Audio = Join-Path $Scratch 'audio'
New-Item -ItemType Directory -Path $Audio -Force | Out-Null
& $Python p0\corpus\generer_controles.py --wav-dir $Audio
if ($LASTEXITCODE -ne 0) { throw 'Controles non generes' }
& $Python p0\corpus\verifier.py --cases (Join-Path $Audio 'cas-controles.csv') --wav-dir $Audio
if ($LASTEXITCODE -ne 0) { throw 'Controles invalides' }
& $Python -m p0.bench --cases (Join-Path $Audio 'cas-controles.csv') --wav-dir $Audio --output (Join-Path $Scratch 'resultats') --partition dev --mode accelerated --warmup 0 -- $Python -m p0.bench.fake_worker --behavior silent
if ($LASTEXITCODE -ne 0) { throw 'Echec du test du banc' }
```

Changer le suffixe `r1` pour rejouer sans écraser. Dans `resultats` : `manifest.json` (configuration et empreintes), `results.json` (mesures agrégées et échecs), `cases.csv` (détail par cas), `trace.ndjson` (événements sans verbatim). Pour un premier chargement réel sans attendre les voix humaines, voir [l’essai vocal de synthèse facultatif](../docs/p0-windows.md) ; il ne sert pas au classement des moteurs.

## 5. Lire les résultats sans confondre les mesures

- **Mode `realtime`** : cadence des WAV, horodatage de la réception des événements du worker, délai du premier mot correct et de la finalisation après `end`. Un résultat `final` n’est ni une note relue ni une preuve d’endpointing automatique. Le délai à l’écran sera mesuré en P1.
- **Mode `accelerated`** : vitesse de décodage hors cadence et facteur temps réel ; ne pas comparer cette latence au ressenti à l’écran. Un modèle hors flux peut être performant sur le texte final sans fournir de brouillon.
- **Relecture des erreurs critiques** : ajouter `--include-text` avant `--` pour produire `transcripts.ndjson`. Générer la grille, puis résumer en passant les mêmes sources :

```powershell
$ReviewInput = @('--transcripts', 'CHEMIN/transcripts.ndjson', '--attributes', 'CHEMIN/attributs.csv', '--cases', 'CHEMIN/cas.csv', '--partition', 'dev')
& $Python -m p0.review prepare @ReviewInput --output 'CHEMIN/grille.csv'
# Remplir la grille avant le resume ; conserver le point-virgule et l'UTF-8.
& $Python -m p0.review summarize @ReviewInput --review 'CHEMIN/grille.csv'
```

Importer les colonnes comme texte si un tableur est utilisé, pour éviter les conversions de nombres et de dates. Le relecteur ne modifie que `rating` et `comment` : `exact`, `substitution`, `omission` pour les attributs ; `insertion` ou `none` sur la ligne des ajouts par cas. Un passage déjà inaudible sur la référence doit être isolé et documenté avant la comparaison. Un échec ASR reste un échec : si un texte final a quand même été émis, juger ses insertions. Vérifier aussi les **hypothèses transitoires non vides** sur silence/bruit dans les résultats du banc : une sortie finale vide ne les efface pas. Si la trace ne permet pas de qualifier leur contenu, refaire un essai fictif supervisé avant de conclure « aucune insertion clinique ». Garder références, grilles, audio et verbatim dans la zone locale. Une personne indépendante réécoute et juge les erreurs en contexte.
