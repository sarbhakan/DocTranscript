# P0 : recette Windows reproductible

Cette procédure compare des moteurs CPU à partir de fichiers WAV injectés à cadence réelle, puis sans cadence imposée. Elle vise deux postes Windows ; aucun résultat Windows n’est présumé acquis. Les événements mesurés proviennent du banc et du moteur, pas de l’affichage d’une fenêtre WPF. La capture continue WASAPI et la latence à l’écran doivent être mesurées avec le prototype Windows en P1.

## 1. Préparer le lot sur un poste connecté distinct

1. Prendre le même instantané du dépôt et les mêmes configurations sur tous les postes. Préparer CPython 3.12 x64 complet et le lot Windows décrit dans [le guide du banc](../p0/README.md) : wheels et leurs dépendances binaires, fichiers de modèle, configurations, licences et versions. Les données sont des dictées fictives autorisées. Aucun compte connecté ni dossier synchronisé n’est nécessaire sur les postes d’essai.
2. Pour chaque archive téléchargée, consigner source directe, version/révision, licence, nom, taille et SHA-256. Comparer aux empreintes publiées lorsqu’elles existent ; autrement, une empreinte relevée localement garantit seulement l’identité du fichier transféré. Vérifier les signatures disponibles. Exporter une copie du manifeste par un canal indépendant ou un manifeste signé si disponible. Pour une release, examiner séparément le droit de redistribuer chaque poids ; la présence de ce poids dans le lot interne ne vaut pas autorisation de publication.
3. Transférer par un support ou un partage local approuvé. Sur Windows, avant toute utilisation, comparer les SHA-256 de tous les fichiers transférés au manifeste, puis vérifier les empreintes et chemins attendus par chaque pack. Exemple pour un fichier, depuis PowerShell :

```powershell
$item = 'D:\NoteVive-P0\artefact.zip'
$expected = 'EMPREINTE_SHA256_VERIFIEE_SUR_LE_POSTE_DE_PREPARATION'
$actual = (Get-FileHash -LiteralPath $item -Algorithm SHA256).Hash
if ($actual -ne $expected) { throw "SHA-256 inattendu : $item" }
```

4. Prévoir une sortie locale distincte du code, par exemple `%LOCALAPPDATA%\NoteVive-P0`. Installer ou copier une distribution CPython complète déjà approuvée, sans associer le runtime au compte ni télécharger sur le poste. Une distribution CPython embarquable minimale n’est pas un substitut à un environnement avec `venv` et `pip`. Créer l’environnement du banc et installer exclusivement les wheels vérifiées selon [le guide du banc](../p0/README.md) (`--no-index`, aucun build à la volée). N’activer ni télémétrie de diagnostic, ni export de traces sur ce poste. [Python sous Windows](https://docs.python.org/3.12/using/windows.html), [Get-FileHash](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/get-filehash?view=powershell-5.1).

## 2. Constituer l’entrée audio

- Utiliser l’index `p0/corpus/cas.csv` et les règles de [constitution du corpus](../p0/corpus/README.md). Si aucun WAV n’est livré, faire lire les textes de développement à des volontaires et prendre un enregistrement distinct pour la confirmation. Aucun patient ni fait clinique réel. Le fichier de calibration éventuellement généré ne remplace pas des voix humaines. Conserver les autorisations et sources audio localement et en dehors du dépôt ; ne publier que les données explicitement redistribuables.
- Sur un poste isolé, enregistrer avec un outil local déjà approuvé, une seule prise par identifiant. Renseigner le type de micro, la distance approximative, le niveau sonore et la consigne donnée au lecteur. Conserver un peu de silence avant et après. Aucun traitement d’amélioration ni coupe silencieuse au hasard. Annoter les débuts et fins de parole sur le **fichier converti** selon la convention du corpus ; ne pas donner de fausse annotation de parole aux cas silence/bruit. Utiliser exactement le même fichier et les mêmes annotations pour tous les moteurs.
- Format attendu : WAV PCM signé 16 bits little-endian, mono, 16 000 Hz. Si l’outil ne sait pas l’exporter directement, exemple de conversion facultative avec un FFmpeg local vérifié et déjà approuvé. L’option `-n` évite de remplacer un fichier existant. [Référence FFmpeg](https://www.ffmpeg.org/ffmpeg.html).

```powershell
& 'D:\Outils-approuves\ffmpeg.exe' -n -hide_banner -i 'D:\Audio-fictif\prise.wav' -vn -ac 1 -ar 16000 -c:a pcm_s16le 'D:\NoteVive-P0\wav\IDENTIFIANT.wav'
if ($LASTEXITCODE -ne 0) { throw 'Conversion WAV interrompue' }
```

## 3. Inventorier et tester deux postes

| Profil | Minimum pour cette campagne |
| --- | --- |
| **W1 : plancher** | Machine physique Windows 11 25H2 x64, 8 Go, CPU de classe i5-8250U ou équivalent documenté, sans GPU dédié. |
| **W2 : représentatif** | Autre poste x64 représentatif du parc, idéalement physique. Si seule une VM est disponible, la déclarer et limiter l’interprétation à l’installation et au contrôle fonctionnel ; elle ne valide pas le débit ou l’usage du micro. |

Depuis la racine du dépôt, ouvrir PowerShell en session utilisateur standard. Utiliser des codes anonymes `W1` et `W2`. L’inventaire ne stocke pas les noms d’hôte, de compte, les adresses réseau ou les numéros de série ; inspecter le JSON avant partage. Si une politique d’entreprise empêche l’exécution de scripts, demander le mode autorisé ou relever manuellement les mêmes champs ; ne pas contourner cette politique. [Inventaire Windows CIM](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-processor), [jeu d’instructions détectable par Windows](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-isprocessorfeaturepresent).

```powershell
$RunRoot = Join-Path $env:LOCALAPPDATA 'NoteVive-P0\W1'
New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null
& .\p0\windows\inventory.ps1 | Set-Content -LiteralPath (Join-Path $RunRoot 'inventory.json') -Encoding UTF8
# Adapter ces chemins au lot verifie sur le poste.
$Lot = 'D:\NoteVive-P0'
$Python = Join-Path $Lot 'venv\Scripts\python.exe'
$Packs = Join-Path $Lot 'packs'
$Wav = Join-Path $Lot 'wav'
$Cases = Join-Path $Lot 'cas-dev-enregistre.csv'
$Attributes = Join-Path $Lot 'attributs-dev-enregistre.csv'
& $Python -c "import platform,struct,sys; print(platform.machine(), struct.calcsize('P') * 8, sys.version.split()[0])"
```

Confirmer `AMD64 64` et `3.12.x` ainsi que le choix CPU seul du pack. Noter manuellement le type de machine (physique/VM), présence/absence de GPU dédié, micro, alimentation secteur/batterie, mode d’alimentation si connu et charge concurrente. Au premier passage, utiliser une machine au repos avec secteur, puis répéter sur le poste plancher avec la même charge locale de référence (par exemple document fictif et navigateur avec quelques pages locales fixes). Pour un portable susceptible d’être utilisé sur batterie, répéter sans changer le mode système et étiqueter l’essai. Ne pas désactiver antivirus ou fonctions d’entreprise. L’observation CPU doit confirmer l’absence d’accélération GPU dans le moteur, pas seulement l’absence de GPU dédié.

Vérifier le contenu de chaque pack sur chaque poste **avant** la campagne ; contrôler aussi que l’empreinte de son manifeste est bien celle du lot préparé. Le rehachage intégral est volontairement hors chronomètre de chargement. Garder ensuite les packs inchangés ; relancer la vérification si un fichier change ou si un incident le justifie.

```powershell
foreach ($name in 'sherpa-nemotron', 'sherpa-zipformer', 'whisper-small-q5', 'sherpa-parakeet') {
    & $Python -m p0.packs verify (Join-Path $Packs $name)
    if ($LASTEXITCODE -ne 0) { throw "Pack invalide : $name" }
}
```

## 4. Exécuter le même protocole

1. Rejouer d’abord le [contrôle sans moteur réel](../p0/README.md#4-vérifier-le-banc-sans-charger-de-modèle) pour valider Python, les chemins et les artefacts de sortie. Il valide le banc, pas la transcription. S’assurer que les cas de développement enregistrés sont acceptés par le vérificateur (`& $Python p0\corpus\verifier.py --cases $Cases --attributes $Attributes --wav-dir $Wav`) et que des fichiers manquants déclenchent une erreur explicite.
2. Faire les mesures à froid de processus (`--warmup 0`) dans un nouveau processus pour chaque moteur, puis les mesures chaudes (`--warmup 1`). Le processus neuf teste le chargement moteur, mais ne garantit pas un cache disque froid. Étiqueter le premier lancement après démarrage comme tel et noter les conditions de cache connues. La chauffe ne doit pas utiliser la partition de confirmation. Employer `--mode realtime` pour la latence du worker avec cadence audio et `--mode accelerated` pour le débit/RTF. Sur chaque poste, au moins trois répétitions par configuration principale, en alternant l’ordre des moteurs. Réutiliser strictement le même index annoté et le même dossier WAV ; attribuer un dossier de sortie inédit par exécution. Indiquer toutes les exceptions au nombre de fils de calcul, à la configuration et aux échecs d’exécution.
3. Exemple avec Sherpa/Nemotron. Remplacer l’adaptateur et le nom du pack pour les autres configurations livrées ; le protocole d’entrée ne change pas. La configuration `sherpa-final` sert de référence après fin de phrase, sans revendication de premier mot en direct. Pour chaque répétition, modifier le suffixe du dossier (`r1`, `r2`, etc.).

```powershell
$Pack = Join-Path $Packs 'sherpa-nemotron'
$Worker = @($Python, '-m', 'p0.adapters', 'sherpa', '--pack', $Pack, '--threads', '4')
$Common = @('--cases', $Cases, '--wav-dir', $Wav, '--partition', 'dev', '--chunk-ms', '20', '--startup-timeout-s', '90', '--timeout-s', '240')
& $Python -m p0.bench @Common --output (Join-Path $RunRoot 'nemotron-cold-r1') --mode realtime --warmup 0 -- @Worker
if ($LASTEXITCODE -ne 0) { throw 'Echec du run a froid' }
& $Python -m p0.bench @Common --output (Join-Path $RunRoot 'nemotron-warm-r1') --mode realtime --warmup 1 --include-text -- @Worker
if ($LASTEXITCODE -ne 0) { throw 'Echec du run chaud' }
& $Python -m p0.bench @Common --output (Join-Path $RunRoot 'nemotron-rtf-r1') --mode accelerated --warmup 1 -- @Worker
if ($LASTEXITCODE -ne 0) { throw 'Echec du run de debit' }
```

`--include-text` sert à [préparer la relecture](../p0/README.md#5-lire-les-résultats-sans-confondre-les-mesures) ; garder ce passage en stockage local. Pour la confirmation, fixer les paramètres et les candidats avant d’ouvrir le corpus privé, choisir `--partition confirm`, et fournir avec `--warmup 1 --warmup-wav CHEMIN` un WAV du lot de développement qui ne figure pas dans la confirmation. Conserver le même WAV d’échauffement sur les deux postes. Les délais de sécurité de 90 et 240 s sont des limites techniques ; ils ne changent pas les objectifs de latence. Si le corpus contient une dictée plus longue, dimensionner le délai accéléré avant de geler la campagne. Pour Parakeet, interpréter le run à cadence réelle uniquement sur la finalisation ; le premier mot du texte final ne compte pas comme un résultat en direct.

4. Mesurer les ressources lors d’une passe séparée, sur le même lot. Le sampler Windows utilise [Tool Help](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-createtoolhelp32snapshot) et [PSAPI](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex) pour échantillonner la somme instantanée des mémoires privées (engagement privé, pas *Working Set*) du banc et de ses descendants. Il estime aussi le temps CPU vu au dernier échantillon de chaque processus, rapporté à la durée réelle en équivalent de cœurs occupés ([GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes)). Il ne stocke ni noms de processus, ni PID. L’intervalle demandé est de 200 ms ; des processus ou pointes plus courts peuvent être manqués. Si des lectures sont incomplètes ou le résultat proche du seuil, refaire à intervalle plus court et confirmer avec un outil de performance Windows autorisé. Ce n’est ni une preuve d’absence de pointe, ni une mesure de la mémoire future de WPF.

```powershell
$Out = Join-Path $RunRoot 'nemotron-resource-r1'
$Memory = Join-Path $RunRoot 'nemotron-resource-r1.memory.json'
& $Python -m p0.windows.measure --output $Memory -- $Python -m p0.bench @Common --output $Out --mode realtime --warmup 0 -- @Worker
if ($LASTEXITCODE -ne 0) { throw 'Echec de la mesure de ressources' }
```

### Facultatif : démarrer les vrais moteurs sans attendre les enregistrements

Sur Windows PowerShell 5.1, si une voix Microsoft SAPI `fr-FR` est **déjà installée**, un [synthétiseur System.Speech](https://learn.microsoft.com/en-us/dotnet/api/system.speech.synthesis.speechsynthesizer.getinstalledvoices?view=netframework-4.8.1) génère un WAV et un manifeste séparés. Lancer sans connexion, sans ajouter de voix ni changer de réglage. Le script échoue proprement si aucune voix compatible n’est disponible ou si la sortie existe. Il ne teste ni le microphone, ni la qualité médicale, ni les objectifs de latence ; le CSV omet les bornes de parole, et tout score de ce passage est exclu de la campagne et de la confirmation. Vérifier qu’une sortie finale plausible apparaît et que le moteur répond sans modèle téléchargé ; inspecter le texte fictif localement avec `--include-text` uniquement pour ce contrôle.

```powershell
$Smoke = Join-Path $RunRoot 'tts-smoke'
& .\p0\windows\smoke-tts.ps1 -Output $Smoke
& $Python -m p0.bench --cases (Join-Path $Smoke 'smoke.csv') --wav-dir $Smoke --output (Join-Path $RunRoot 'nemotron-tts-smoke-r1') --mode realtime --warmup 0 --include-text -- @Worker
if ($LASTEXITCODE -ne 0) { throw 'Echec du controle vocal synthetique' }
```

## 5. Vérifier le hors ligne et contre-vérifier

1. **Fonctionnement sans réseau.** Sur poste de test isolé, débrancher l’Ethernet ou couper la connexion via les moyens habituels autorisés. Sans modifier la politique de sécurité, démarrer un processus neuf et transcrire au moins un cas par configuration. Un paquet qui exige un téléchargement, un service, une authentification ou un modèle récupéré à l’exécution échoue. Si la déconnexion physique est impraticable, utiliser une VM sans réseau uniquement pour cette preuve d’installation/fonctionnement.
2. **Tentatives réseau.** La coupure montre que le traitement fonctionne sans réseau ; elle ne prouve pas l’absence de tentatives. Réaliser un second passage sur un réseau de test sans accès Internet, avec les outils autorisés par le parc : observation des ouvertures TCP/UDP par processus et descendants ([TCPView](https://learn.microsoft.com/en-us/sysinternals/downloads/tcpview) en contrôle ponctuel, [Process Monitor](https://learn.microsoft.com/en-us/sysinternals/downloads/procmon) pour une trace si autorisé). Un test plus fort ajoute une capture par [Pktmon](https://learn.microsoft.com/en-us/windows-server/networking/technologies/pktmon/pktmon) ou sur le réseau de test et compare à une période témoin, en vérifiant DNS, TCP, UDP et boucle locale selon les capacités de l’outil. Le trafic de l’OS ne doit pas être attribué à tort au produit. Documenter périmètre, durée et limites ; une lecture ponctuelle seule ne démontre pas zéro tentative. Si aucun moyen autorisé n’est disponible, indiquer « fonctionnement hors connexion vérifié, absence de tentatives non vérifiée ». Garder les traces brutes de capture localement.
3. **Contrôle indépendant.** Un second opérateur repart du manifeste et d’un dossier de sortie vide. Il refait un run froid, un run chaud et un run accéléré sur W1, puis un smoke test sur W2. Il rejoue un WAV illisible, un modèle absent/corrompu et un arrêt volontaire du worker. Il vérifie que les erreurs restent visibles, que les résultats partiels ne sont pas présentés comme succès, que des échantillons fictifs de silence/bruit n’inventent aucun contenu clinique, et que le fichier de traces ne contient pas de verbatim par défaut. N’inclure dans Git que les éléments publiables. Reporter les mesures et décisions dans [le registre](suivi.md) avec les versions et l’identifiant du lot ; aucune mesure sans référence à son jeu, son moteur et son poste.

Pour décider du P0, renseigner une ligne par moteur, poste et condition dans la [fiche de résultats](p0-resultats.md). Lire ensemble les délais du worker, les cas sans résultat conforme, le RTF, la mémoire et la fidélité. Le banc permet d’écarter un candidat manifestement trop lent ou trop fragile ; il ne peut pas déclarer satisfaits les critères écran, micro et endurance clinique de [la feuille de route](feuille-de-route.md). Si Windows réel ou les dictées de test manquent, consigner le jalon comme non qualifié.
