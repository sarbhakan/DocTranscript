# Préparer et ajuster un modèle local

Le module `prepare_px` prépare **des données de développement**, sans entraîner ni modifier le moteur de NoteVive. Les nouveaux modules `train_lora` et `export_lora` réalisent un ajustement expérimental et son export, explicitement séparés de l’application distribuée. Il utilise uniquement l’archive **PxCorpus v4** déjà employée par le banc. Il fonctionne hors ligne avec Python 3.11 ou 3.12 et sa bibliothèque standard ; aucune bibliothèque de calcul, compte ou carte graphique n’est nécessaire.

Le corpus contient des prescriptions simulées, enregistrées par des volontaires. Les transcriptions de référence sont celles du fichier source `seq.in`, dont les auteurs déclarent la vérification humaine. L’export ne les réécrit pas à partir des sorties d’un moteur. Une relecture à l’écoute reste nécessaire avant de les considérer comme des références validées pour un entraînement médical.

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

Pour entraîner ensuite, il faut un modèle au format entraînable, une méthode existante telle que PEFT/LoRA ou NeMo, des ressources adaptées et une évaluation du modèle exporté dans son format final. Le fichier GGML quantifié de l’application ne s’entraîne pas par ajout de ce dossier. **La préparation des données seule n’entraîne aucun poids.** Voir ci-dessous pour lancer explicitement un entraînement.

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

```bash
/chemin/local/notevive-entrainement/venv/bin/python -m p0.training.train_lora evaluate \
  --model /chemin/local/notevive-entrainement/base \
  --corpus /chemin/local/adaptation-px-v1 \
  --px-archive /chemin/local/PxCorpus.zip \
  --adapter /chemin/local/notevive-entrainement/epoch-01/checkpoints/update-000271 \
  --output /chemin/local/notevive-entrainement/evaluation-01 --count 32
```

Les 32 clips sont choisis par une règle fixe sur leurs identifiants, répartis sur les huit voix. La base et l’adaptateur transcrivent les mêmes WAV sans recevoir les références. Les prédictions restent dans `predictions.local.jsonl`, hors Git. Le WER agrégé ne remplace pas la vérification des médicaments, valeurs, fractions, unités, négations et associations.

`export_lora --help` documente la fusion FP32 → HF FP16 puis la conversion officielle whisper.cpp 1.8.5 → Q5_0. Le convertisseur, les filtres mel, le tokenizer, l’architecture et le quantizer sont vérifiés. Reconvertir aussi la base témoin et comparer les fichiers Q5 dans la chaîne finale Windows avant toute adoption. L’export seul ne remplace jamais le modèle de NoteVive.

Tests contractuels (sans GPU ni dépendances ML, sauf une petite régression PEFT facultative dans l’environnement d’entraînement) :

```bash
python3 -m unittest p0.bench.test_training p0.bench.test_lora_contract
```
