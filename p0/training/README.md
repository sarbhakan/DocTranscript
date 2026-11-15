# Préparer et ajuster un modèle local

Le module `prepare_px` prépare **des données de développement** à partir de l’archive **PxCorpus v4** déjà employée par le banc. La préparation et le contrôle des erreurs critiques utilisent Python 3.11 ou 3.12 et sa bibliothèque standard. Ils fonctionnent hors ligne, sans compte ni carte graphique. Le module `train_lora` nécessite les bibliothèques de calcul décrites plus bas et lance explicitement un ajustement expérimental ; `export_lora` prépare sa fusion et sa conversion. Ces opérations sont séparées de l’application distribuée.

Le corpus contient des prescriptions simulées, enregistrées par des volontaires. Les transcriptions de référence sont celles du fichier source `seq.in`, dont les auteurs déclarent la vérification humaine. L’export ne les réécrit pas à partir des sorties d’un moteur. Une relecture à l’écoute reste nécessaire avant de les considérer comme des références validées pour un entraînement médical.

## Résultat de l’expérience terminée le 14 novembre 2026

**Une époque a été exécutée : 1 081 clips, 32 voix, 271 mises à jour et 327 680 paramètres LoRA ajustés.** Sur le Mac M1 Pro à 16 Gio, le temps mesuré est de 1 395,14 secondes, validation finale de la perte comprise. Les gradients sont finis, les poids de base sont inchangés et la recharge des adaptateurs est exacte. La perte pondérée par les 5 660 jetons des 282 clips de validation est de 0,26592. Elle ne mesure pas, à elle seule, la qualité de transcription. Le [rapport d’exécution](lora_epoch_report.json) conserve les mesures et les empreintes du code effectivement utilisé.

Les 32 clips de génération libre représentent huit voix, 196,88 secondes et 371 mots de référence. La grille critique a été figée avant toute prédiction. La sauvegarde finale à 271 mises à jour a été examinée en premier ; un plan borné, écrit ensuite et avant leurs résultats, a fixé la comparaison des sauvegardes 50 puis 150, sans nouvel entraînement.

| Sauvegarde | Erreurs de mots / 371 | WER | Noms reconnus / 24 | Doses reconnues / 46 | Associations médicament–dosage / 16 | Adoption |
|---|---:|---:|---:|---:|---:|---|
| Base sans adaptation | 80 | 21,56 % | 8 | 42 | 5 | Base conservée |
| 50 mises à jour | 55 | 14,82 % | 10 | 41 | 7 | Refusée |
| 150 mises à jour | 32 | 8,63 % | 10 | 45 | 7 | Refusée |
| 271 mises à jour | 30 | 8,09 % | 11 | 45 | 7 | Refusée |

Ces nombres décrivent des correspondances avec les références source dans Transformers sur MPS, base FP16 et adaptateurs FP32. **Ils ne mesurent pas directement le modèle Q5_0 distribué.** Les trois sauvegardes introduisent chacune deux erreurs de nom et une erreur d’association que la base ne faisait pas selon la grille. La sauvegarde 50 ajoute également deux régressions de dose ; la sauvegarde 150 ajoute un échec du contrôle de la séquence de nombres. Les catégories peuvent se recouvrir. Le critère d’absence de nouvelle erreur critique n’est donc atteint par aucun candidat, même si les totaux de mots s’améliorent.

Les temps de génération totaux et médians passent le seuil exploratoire de +10 % sur ce Mac. Ils ne mesurent ni le délai du micro à l’écran ni les performances sur Windows à 8 Go. Le [rapport agrégé de sélection](lora_validation_report.json) contient les numérateurs exacts, gains et pertes appariés, temps, empreintes du plan, de la grille et du code. Il contient aussi la correction du diagnostic de fin de génération : les séquences brutes comportent bien le jeton de fin dans 32/32 sorties de chaque variante. Entre les deux évaluations de la sauvegarde 271, les textes sont identiques pour la base dans 32/32 cas et pour l’adaptateur dans **31/32 cas**, avec des scores inchangés ; l’origine de la variation d’un mot déjà incorrect n’est pas établie.

**La sélection est terminée : aucun adaptateur n’est adopté, exporté en HF/Q5_0 ou ajouté à NoteVive. Les 85 audios du banc de régression n’ont pas été utilisés dans cette expérience.** Ces 32 clips sont un lot de développement, limité aux prescriptions simulées. Les fractions ne concernent qu’un clip, la négation annotée une consigne dans un seul clip, sans négation de symptôme. Les références n’ont pas été réauditées médicalement par le projet. Les résultats ne permettent aucune conclusion de fiabilité clinique ni de couverture de toutes les spécialités.

La suite utile consiste à préparer avec un médecin des dictées fictives, leurs corrections vérifiées à l’écoute et un lot de confirmation gardé à part par voix et par texte. Le [plan accessible à Hakan et au médecin](../../docs/entrainement-local.md#prochain-travail-réalisable-avec-un-médecin-volontaire) décrit leurs actions sans installation de Python. Les commandes ci-dessous documentent la reproduction technique et les futurs essais ; elles ne constituent pas une recommandation de relancer un entraînement identique.

## Utilisation

Depuis la racine du dépôt, choisir un dossier **local hors du dépôt Git et hors synchronisation**. L’outil refuse un dossier de sortie existant et les sorties à l’intérieur de ce dépôt.

```powershell
python -m p0.training.prepare_px export --px-archive "C:\NoteVive-Banc\PxCorpus.zip" --output "C:\NoteVive-Banc\adaptation-px-v1"
python -m p0.training.prepare_px verify --px-archive "C:\NoteVive-Banc\PxCorpus.zip" --directory "C:\NoteVive-Banc\adaptation-px-v1"
```

Sur Mac, les mêmes commandes fonctionnent en remplaçant `python` par `python3` et les chemins par des chemins locaux. Il faut fournir l’archive exacte de [PxCorpus v4](https://zenodo.org/records/10080490) : SHA-256 `b901f59118f06854a4c4823611d8cadbbd2e68e48459bc514dabe0bda6f7d81c`. L’outil ne la télécharge pas. Il n’existe pas d’option pour ignorer cette empreinte ou substituer Corti, PARROT, des données de patients ou des transcriptions automatiques.

La commande crée :

- `train.jsonl` et `validation.jsonl` : chemins WAV relatifs au dossier d’export, texte source, durée, identifiant de locuteur, licence, index source et empreintes ;
- `wav/` : WAV mono, PCM signé 16 bits à 16 kHz. Ce format est vérifié, puis le conteneur est réécrit sans modifier les échantillons audio ; aucun rééchantillonnage ni nettoyage n’est appliqué ;
- `reserve.local.json` : éléments nécessaires au contrôle des exclusions. Ce fichier contient des références et reste local ;
- `ATTRIBUTION.txt` : attribution et description des transformations ;
- `report.json` : rapport agrégé, sans transcription ni liste de locuteurs. **Seul ce rapport peut être proposé pour publication**, après vérification de son contenu.

Le champ `audio_filepath` est relatif à la racine de cet export ; le chargeur d’entraînement le résout par rapport à cette racine. Les champs `text` et `duration` suivent la convention courante des manifestes ASR. Ce fichier n’est pas une configuration d’entraînement NeMo ou Transformers prête à exécuter.

## Séparation et contrôles

Les partitions officielles train/dev de PxSLU partagent des locuteurs. L’export refait une séparation déterministe **par locuteur** : environ 20 % des locuteurs admissibles vont dans `validation`, selon un classement SHA-256 fixe. Il ne propose pas de recherche de graines permettant de sélectionner une partition plus facile après observation des résultats.

Tous les locuteurs du test officiel composé de médecins sont réservés : cela protège les 51 prescriptions du benchmark NoteVive ainsi que leurs voix. Les voix des dix essais historiques `PRIOR_ROWS` sont également réservées. Une référence ou un signal PCM identique à cette réserve est exclu des deux partitions d’adaptation.

Les références ou PCM identiques entre train et validation sont retirés **des deux côtés** ; on ne déplace jamais une phrase en séparant sa voix du reste de ses enregistrements. Les PCM dupliqués dans une partition sont dédupliqués. Une phrase dépassant 30 secondes est exclue entière : aucun tronquage audio laissant une référence trop longue n’est autorisé.

La clé de comparaison des références réduit la casse et les espaces et normalise Unicode NFC. Elle conserve les valeurs, unités et négations. Elle ne prouve pas l’absence de paraphrases ou de quasi-doublons sémantiques. Les catégories, durées, nombres de voix et motifs d’exclusion sont comptés dans le rapport.

Après l’export, et avec `verify`, le contrôleur relit les WAV, compare leurs empreintes et les durées et vérifie l’absence d’intersection de locuteurs, références et PCM entre partitions et avec la réserve. **L’archive source est obligatoire pour cette vérification** : son empreinte est contrôlée sur le même fichier ouvert que celui lu ensuite, puis le plan est reconstruit. Chaque identifiant, index source, voix, référence et PCM est comparé à cette source ; la réserve et l’attribution doivent aussi correspondre. Recalculer les empreintes d’un manifeste modifié ne suffit donc pas à le faire accepter. Les liens symboliques de la racine, des fichiers de métadonnées, des WAV et de leurs dossiers sont refusés ; les jonctions Windows sont également contrôlées avec Python 3.12.

Le rapport conserve l’empreinte de l’archive et celles des manifestes. Ce rapport seul est une déclaration non signée : une personne qui le reçoit sans l’archive et sans effectuer la vérification ne peut pas en déduire l’authenticité des données. Le contrôle de correspondance à l’archive ne remplace pas une relecture médicale à l’écoute.

## Portée et suite

Ce sous-ensemble est limité aux prescriptions. Il ne couvre pas à lui seul les maladies, examens et spécialités. Les voix de médecins du test sont exclues de l’adaptation : les catégories restantes sont `expert` et `non-expert`, telles que fournies par les auteurs.

Le jeu de validation exporté sert au développement. Les 51 cas déjà vus ne deviennent pas un test indépendant après cette préparation. Le recouvrement éventuel avec le préentraînement de Whisper ou d’un autre modèle est inconnu. Une qualification ultérieure doit conserver un nouveau jeu de confirmation, avec d’autres voix et textes, et comparer aussi les doses, fractions, négations, médicaments et temps de calcul.

L’export réel du **14 novembre 2026** a été exécuté puis revérifié : **1 081 audios / 32 voix / 2 h 14 min 37 s** pour train et **282 audios / 8 voix / 27 min 14 s** pour validation. Il réserve 570 audios de 14 voix de médecins. Il retire aussi 29 enregistrements dont la référence apparaît dans cette réserve, 16 dont la référence traverse train/validation et trois doublons PCM internes. Le [rapport agrégé](pxcorpus_v4_report.json) fournit les durées exactes et les empreintes. Aucun de ces audios ni de leurs références n’est ajouté au dépôt.

L’expérience terminée utilise PEFT/LoRA et les poids d’origine au format entraînable. Le fichier GGML quantifié de l’application ne s’entraîne pas par ajout de ce dossier. **La préparation des données seule n’entraîne aucun poids.** Les commandes suivantes lancent explicitement un entraînement, avec ses propres sorties et contrôles.

Source : [PxCorpus v4, Kocabiyikoglu et al.](https://zenodo.org/records/10080490), licence [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Attribution : Ali Can Kocabiyikoglu, François Portet, Prudence Gibert, Hervé Blanchon, Jean-Marc Babouchkine et Gaëtan Gavazzi. Publication : *A Spoken Drug Prescription Dataset in French for Spoken Language Understanding*, LREC 2022. L’archive est vérifiée directement ; les comptages exportés décrivent son contenu effectif et peuvent différer des arrondis de la notice.

Tests du préparateur :

```powershell
python -m unittest p0.bench.test_training -v
```


## Entraînement expérimental sur Mac Apple Silicon

Ces commandes s’adressent au développeur du projet. Le médecin utilise le ZIP Windows et n’a rien à installer de cette chaîne.

L’environnement est isolé, **Python 3.12 ARM64**, PyTorch 2.9.1, Transformers 4.57.3 et PEFT 0.18.0. Le fichier `requirements-macos-arm64.lock.txt` fixe les wheels officielles et leurs SHA-256. La préparation télécharge les dépendances et les poids publics ; l’entraînement et l’évaluation suivants fonctionnent hors ligne. Aucun son n’est envoyé.

```bash
python3 -m venv /chemin/local/notevive-entrainement/venv
/chemin/local/notevive-entrainement/venv/bin/python -m pip --isolated install --no-cache-dir --only-binary=:all: --require-hashes --index-url https://pypi.org/simple -r p0/training/requirements-macos-arm64.lock.txt
python3 -m p0.training.fetch_model fetch --model /chemin/local/notevive-entrainement/base
```

Créer le dossier parent local auparavant, avec suffisamment d’espace libre. Les sorties doivent être neuves, hors dépôt et hors synchronisation. Le modèle OpenAI est fixé à la révision `41f01f3fe87f28c78e2fbf8b568835947dd65ed9` ; tous ses fichiers sont vérifiés, et un fichier supplémentaire susceptible de modifier le chargement fait refuser le dossier.

```bash
/chemin/local/notevive-entrainement/venv/bin/python -m p0.training.train_lora train \
  --model /chemin/local/notevive-entrainement/base \
  --corpus /chemin/local/adaptation-px-v1 \
  --px-archive /chemin/local/PxCorpus.zip \
  --output /chemin/local/notevive-entrainement/smoke-01 \
  --max-updates 8 --validation-limit 8
```

Le mini-essai vérifie huit mises à jour effectives, des gradients finis, la base inchangée, les adaptateurs modifiés et une sauvegarde/recharge exacte. Il n’établit pas de gain de reconnaissance. Pour une passe complète, choisir **une autre sortie neuve**, avec `--max-updates 271 --epochs 1`, sans `--validation-limit` : 1 081 clips d’entraînement et les 282 clips de validation. Il n’y a pas de reprise implicite du mini-essai.

L’encodeur et la base sont gelés. Seuls 327 680 paramètres LoRA FP32 sont ajustés, sur les 16 projections q/v des quatre couches du décodeur ; la base utilise FP16 sur MPS. L’accumulation utilise quatre clips et un dernier groupe d’un clip. La référence conserve le vrai jeton de fin ; le remplissage ne compte pas dans la perte. Un gradient non fini ou un pas ignoré interrompt l’essai. Aucun lexique n’est utilisé pour réécrire les références.

`contract.json`, `events.jsonl`, `report.json` et les sous-dossiers `checkpoints/` permettent de suivre ce qui a réellement eu lieu. `last.json` et `best.json` indiquent les adaptateurs terminés. Avec une seule passe, il n’existe qu’une validation finale : « best » n’est pas une recherche de plusieurs configurations. Les interruptions conservent un rapport d’échec et n’autorisent aucune adoption automatique.

## Évaluer sans choisir sur le seul WER

**Avant de générer les prédictions**, préparer la grille privée sur les références des 32 clips déterministes. Fixer aussi les candidats et les critères de décision ; ne pas retoucher cette grille ni son code en fonction des erreurs observées.

```bash
python3 -m p0.training.score_validation prepare \
  --corpus /chemin/local/adaptation-px-v1 \
  --px-archive /chemin/local/PxCorpus.zip \
  --output /chemin/local/notevive-entrainement/validation-critical.json
```

La grille contient les références et les éléments à vérifier ; elle reste hors Git, avec son empreinte. L’outil réutilise les annotations de la source et les contrôles du banc. Ses tests adversariaux vérifient notamment l’échange de doses, les fractions, les signes et le remplacement d’une coordination par une alternative. Cela n’en fait pas un validateur de prescriptions.

```bash
/chemin/local/notevive-entrainement/venv/bin/python -m p0.training.train_lora evaluate \
  --model /chemin/local/notevive-entrainement/base \
  --corpus /chemin/local/adaptation-px-v1 \
  --px-archive /chemin/local/PxCorpus.zip \
  --adapter /chemin/local/notevive-entrainement/epoch-01/checkpoints/update-000271 \
  --output /chemin/local/notevive-entrainement/evaluation-01 --count 32
```

Les 32 clips sont choisis par une règle fixe sur leurs identifiants, répartis sur les huit voix. La base et l’adaptateur transcrivent les mêmes WAV sans recevoir les références. Les prédictions restent dans `predictions.local.jsonl`, hors Git. Le WER agrégé ne remplace pas la vérification des médicaments, valeurs, fractions, unités, négations et associations.

```bash
python3 -m p0.training.score_validation score \
  --grid /chemin/local/notevive-entrainement/validation-critical.json \
  --predictions /chemin/local/notevive-entrainement/evaluation-01/predictions.local.jsonl \
  --output /chemin/local/notevive-entrainement/critical-01
```

Le rapport agrégé compte séparément les gains et les régressions pour chaque contrôle. `details.local.json` conserve les cas et les textes, hors Git. Pour cette expérience, l’admissibilité exigeait au moins un gain de nom, moins d’erreurs de mots, aucune régression critique et une dégradation de temps total et médian ne dépassant pas 10 %. Les sorties doivent aussi présenter un jeton de fin, et la base témoin répétée doit retrouver les mêmes textes. Les trois sauvegardes échouent sur les régressions critiques. Le banc de 85 audios reste réservé à une étape ultérieure de contrôle d’un candidat admissible, après conversion ; ses cas déjà vus ne constituent pas une confirmation indépendante.

## Export préparé, non exécuté pour ces candidats

`python3 -m p0.training.export_lora --help` documente la fusion FP32 → HF FP16 puis la conversion officielle whisper.cpp 1.8.5 → Q5_0. Les empreintes du convertisseur et des filtres mel, le tokenizer et l’architecture sont contrôlés. Le quantizer doit être fourni avec son SHA-256 ; cette empreinte seule ne prouve pas sa provenance, qui exige aussi le rapport de construction. Reconvertir la base témoin avec la même procédure et comparer les fichiers Q5 dans la chaîne finale Windows avant toute adoption. L’export seul ne remplace jamais le modèle de NoteVive. **Aucun export du modèle adapté n’a été lancé après le refus de cette expérience.**

Tests contractuels (sans GPU ni dépendances ML, sauf une petite régression PEFT facultative dans l’environnement d’entraînement) :

```bash
python3 -m unittest p0.bench.test_training p0.bench.test_lora_contract p0.bench.test_validation_scoring
```
