# Préparer des données d’adaptation locales

Cet outil prépare **des données de développement**, sans entraîner ni modifier le moteur de NoteVive. Il utilise uniquement l’archive **PxCorpus v4** déjà employée par le banc. Il fonctionne hors ligne avec Python 3.11 ou 3.12 et sa bibliothèque standard ; aucune bibliothèque de calcul, compte ou carte graphique n’est nécessaire.

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

Le champ `audio_filepath` est relatif à la racine de cet export ; le futur chargeur d’entraînement doit le résoudre par rapport à cette racine. Les champs `text` et `duration` suivent la convention courante des manifestes ASR. Ce fichier n’est pas une configuration d’entraînement NeMo ou Transformers prête à exécuter.

## Séparation et contrôles

Les partitions officielles train/dev de PxSLU partagent des locuteurs. L’export refait une séparation déterministe **par locuteur** : environ 20 % des locuteurs admissibles vont dans `validation`, selon un classement SHA-256 fixe. Il ne propose pas de recherche de graines permettant de sélectionner une partition plus facile après observation des résultats.

Tous les locuteurs du test officiel composé de médecins sont réservés : cela protège les 51 prescriptions du benchmark NoteVive ainsi que leurs voix. Les voix des dix essais historiques `PRIOR_ROWS` sont également réservées. Une référence ou un signal PCM identique à cette réserve est exclu des deux partitions d’adaptation.

Les références ou PCM identiques entre train et validation sont retirés **des deux côtés** ; on ne déplace jamais une phrase en séparant sa voix du reste de ses enregistrements. Les PCM dupliqués dans une partition sont dédupliqués. Une phrase dépassant 30 secondes est exclue entière : aucun tronquage audio laissant une référence trop longue n’est autorisé.

La clé de comparaison des références réduit la casse et les espaces et normalise Unicode NFC. Elle conserve les valeurs, unités et négations. Elle ne prouve pas l’absence de paraphrases ou de quasi-doublons sémantiques. Les catégories, durées, nombres de voix et motifs d’exclusion sont comptés dans le rapport.

Après l’export, et avec `verify`, le contrôleur relit les WAV, compare leurs empreintes et les durées et vérifie l’absence d’intersection de locuteurs, références et PCM entre partitions et avec la réserve. **L’archive source est obligatoire pour cette vérification** : son empreinte est contrôlée sur le même fichier ouvert que celui lu ensuite, puis le plan est reconstruit. Chaque identifiant, index source, voix, référence et PCM est comparé à cette source ; la réserve et l’attribution doivent aussi correspondre. Recalculer les empreintes d’un manifeste modifié ne suffit donc pas à le faire accepter. Les liens symboliques de la racine, des fichiers de métadonnées, des WAV et de leurs dossiers sont refusés ; les jonctions Windows sont également contrôlées avec Python 3.12.

Le rapport conserve l’empreinte de l’archive et celles des manifestes. Ce rapport seul est une déclaration non signée : une personne qui le reçoit sans l’archive et sans effectuer la vérification ne peut pas en déduire l’authenticité des données. Le contrôle de correspondance à l’archive ne remplace pas une relecture médicale à l’écoute.

## Portée et suite

Ce sous-ensemble est limité aux prescriptions. Il ne couvre pas à lui seul les maladies, examens et spécialités. Les voix de médecins du test sont exclues de l’adaptation : les catégories restantes sont `expert` et `non-expert`, telles que fournies par les auteurs.

Le jeu de validation exporté sert au développement. Les 51 cas déjà vus ne deviennent pas un test indépendant après cette préparation. Le recouvrement éventuel avec le préentraînement de Whisper ou d’un autre modèle est inconnu. Un futur entraînement doit conserver un nouveau jeu de confirmation, avec d’autres voix et textes, et comparer aussi les doses, fractions, négations, médicaments et temps de calcul.

L’export réel du **14 novembre 2026** a été exécuté puis revérifié : **1 081 audios / 32 voix / 2 h 14 min 37 s** pour train et **282 audios / 8 voix / 27 min 14 s** pour validation. Il réserve 570 audios de 14 voix de médecins. Il retire aussi 29 enregistrements dont la référence apparaît dans cette réserve, 16 dont la référence traverse train/validation et trois doublons PCM internes. Le [rapport agrégé](pxcorpus_v4_report.json) fournit les durées exactes et les empreintes. Aucun de ces audios ni de leurs références n’est ajouté au dépôt.

Pour entraîner ensuite, il faut un modèle au format entraînable, une méthode existante telle que PEFT/LoRA ou NeMo, des ressources adaptées et une évaluation du modèle exporté dans son format final. Le fichier GGML quantifié de l’application ne s’entraîne pas par ajout de ce dossier. **Aucun poids n’est entraîné par cet outil.**

Source : [PxCorpus v4, Kocabiyikoglu et al.](https://zenodo.org/records/10080490), licence [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Attribution : Ali Can Kocabiyikoglu, François Portet, Prudence Gibert, Hervé Blanchon, Jean-Marc Babouchkine et Gaëtan Gavazzi. Publication : *A Spoken Drug Prescription Dataset in French for Spoken Language Understanding*, LREC 2022. L’archive est vérifiée directement ; les comptages exportés décrivent son contenu effectif et peuvent différer des arrondis de la notice.

Tests du préparateur :

```powershell
python -m unittest p0.bench.test_training -v
```
