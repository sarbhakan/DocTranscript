# P0 · Décision Windows et historique des comparaisons

**Candidat en recette Windows 0.3.0 : Whisper Large-v3 Turbo Q5_0, whisper.cpp 1.8.5 et Silero VAD GGML 6.2.0, pause de 576 ms.** Le [benchmark élargi sur Mac](../p0/asr_benchmark.md) a comparé cinq modèles sur 89 fichiers audio. Le pont natif à 576 ms y préserve les huit fractions annotées du lot difficile mais commet encore des erreurs de doses, de négations et de termes médicaux. Son P95 estimé de 4,20 s entre la fin de parole et le texte dépasse déjà le seuil de 2 s, sans mesure du micro ni de l’écran. Ce choix reste un candidat Windows, et non un classement établi sous Windows.

## Ce que montrent les premiers tests Windows

Les essais ont rejoué le même [fichier de parole française fictive de 6,44 s](../p0/fixtures/README.md) avec le moteur du ZIP, en CI sur des machines virtuelles de deux cœurs et quatre processeurs logiques. Les temps totaux incluent le démarrage du moteur ; ce ne sont ni une latence d’affichage, ni un P95.

| Compilation et hôte CI | Traitement total AVX2 | Variante SSE2 |
| --- | ---: | --- |
| [MSVC, AMD EPYC 7763](https://github.com/sarbhakan/DocTranscript/actions/runs/43606814807) | 35,435 s | Délai de 90 s dépassé |
| ClangCL, Intel Xeon Platinum 8573C | 38,510 s, dont 36,888 s d’encodage, sans repli du décodeur | Délai de 90 s dépassé |
| [ClangCL + `GGML_LLAMAFILE`, Intel Xeon Platinum 8573C, 17,17 Go de RAM](https://github.com/sarbhakan/DocTranscript/actions/runs/43609865149) | 30,330 s, dont 28,689 s d’encodage, sans repli du décodeur ; paire « Prozac 20 mg » reconnue | Délai de 90 s dépassé |

L’encodeur représente l’essentiel du temps dans les deux essais instrumentés. Le dernier essai ([commit `940cf2a`](https://github.com/sarbhakan/DocTranscript/commit/940cf2a)) garde les mêmes poids et le même contexte audio complet. Les deux essais sur Xeon ont utilisé le même type de machine virtuelle, sans comparaison sur le même hôte ; on ne peut pas attribuer l’écart au noyau matriciel. Les résultats AMD et Intel ne permettent pas non plus d’isoler l’effet du compilateur. Le prochain essai porte sur OpenBLAS avec le même Turbo et le contexte complet ; aucun résultat n’est disponible.

Le dernier run a aussi exécuté le test automatisé d’interface. Celui-ci s’est arrêté sur `SetFocus` pendant l’actionnement de la fenêtre. Cet échec concerne le test et ne montre pas un plantage de NoteVive ; la recette d’interface reste à confirmer.

**Périmètre CPU du candidat : AVX2.** NoteVive vérifie la prise en charge d’AVX/AVX2 dans Windows et les extensions FMA, F16C, BMI1, BMI2, LZCNT, SSE4.2 et POPCNT. En cas d’incompatibilité, l’application garde l’accès aux notes mais ne charge pas le modèle et n’ouvre pas le micro. Les échecs SSE2 ci-dessus restent des résultats du diagnostic ; sa limite de 90 s demeure. La CI produit ne traite plus SSE2 comme un mode supporté.

L’essai OpenBLAS doit également rejouer les [deux extraits de régression](../p0/fixtures/README.md). Il vérifie les doses et les trois fractions attendues, la même suite de valeurs numériques et l’absence de négation ou de concentration ajoutée. Les mentions de médicaments sont rapportées sans garantie d’association clinique correcte entre nom, dose et prise.

Le [contexte audio réduit](../p0/audio_context_ablation.md) est écarté : il fait perdre 20 éléments critiques reconnus avec le contexte complet et réinsère, dans deux fichiers, une phrase issue d’une autre dictée fictive. Le contexte complet reste la référence. **La 0.3.0 n’est pas publiée tant que les échecs de recette persistent.** La prochaine validation porte sur le paquet lui-même puis sur les [deux PC physiques Windows](windows-recette-030.md), dont celui de 8 Go sans GPU dédié. La qualification clinique reste ouverte, indépendamment de la correction des performances.

## Historique : premier choix Mac 0.2.0

Les résultats ci-dessous sont conservés comme trace du premier protocole. La décision UltiMed concernait la .app Mac ; le candidat Windows actuel est décrit ci-dessus.

**Décision historique : Parakeet UltiMed INT8 avec filtre de présence de parole Silero est le seul candidat retenu pour l’intégration.** Whisper Turbo reste un témoin du banc. UltiMed reconnaît davantage de noms médicaux et renvoie le texte plus vite sur ce Mac. Les deux moteurs commettent des erreurs numériques graves. Le candidat est intégré au paquet Mac d’essai ; [les résultats de ce paquet](p0-recette-mac-020.md) ne permettent pas de valider un usage clinique.

## Essai apparié

Même audio sur un Mac Apple M1 Pro, 16 Gio, macOS 27.2. Chaque moteur reste chargé après préchauffage et décode en français après réception de la fin du fichier, avec quatre fils CPU côté ASR. Aucun lexique ni remplacement de mots. Les 71 cas sont 51 prescriptions simulées de 13 médecins de [PxCorpus/PxSLU v4](https://zenodo.org/records/10080490) (Kocabiyikoglu et coll., CC BY 4.0), 16 dictées fictives lues par la voix Jacques de macOS et quatre contrôles sans parole. Le lot Px prend au plus quatre prises par personne, de sessions distinctes, avec un médicament et sa force commerciale annotés ; les dix prises du premier essai sont exclues. Les index sont ceux des fichiers de données à base zéro. Le texte original et les WAV restent locaux. PxCorpus ne figure pas dans la liste publiée des données d’ajustement d’UltiMed ; un recoupement avec les données des modèles parents ne peut être exclu.

| Mesure | Whisper Turbo Q5_0 + Silero 6.2.0 | Parakeet UltiMed INT8 + Silero 6.2 |
| --- | ---: | ---: |
| Noms de médicaments identiques à la référence Px, hors casse et ponctuation | 15/51 | **25/51** |
| Sur les 40 références de nom recoupées avec une dénomination du catalogue BDPM | 12/40 | **20/40** |
| Valeur et unité de la **force commerciale** reconnues (notation normalisée) | **49/49** | 45/49 |
| Écarts de mots sur les prescriptions humaines | 199/663 (30,0 %) | 203/663 (30,6 %) |
| Écarts de mots sur les dictées synthétiques | 55/403 (13,6 %) | 49/403 (12,2 %) |
| P95 entre la commande de fin audio et le résultat, sur 67 fichiers parlés | 3,62 s | **0,48 s** |
| Contrôles de silence ou bruit avec sortie non vide | 0/4 | 0/4 |

Les écarts de mots incluent des différences de notation et les hésitations. Pour les forces commerciales, deux références annotées « micronisé » ont été exclues du score automatique. La cooccurrence d’un nom et d’un nombre ne suffit pas à valider leur association. La relecture des sorties a confirmé qu’UltiMed rendait un `400 mg` en `4 mg` et produisait aussi des décimaux ambigus. Whisper préservait les forces commerciales évaluées, mais rendait deux `un demi` en `1,5` dans la même prise et perdait deux mentions de `deux bouffées` dans une autre. Le score global masque ces écarts. Sur les noms, UltiMed devance Whisper chez huit des treize locuteurs, quatre sont à égalité, un est en faveur de Whisper. Ces effectifs n’établissent pas une supériorité clinique.

Le filtre d’UltiMed laisse passer le fichier complet s’il détecte de la parole ; les 67 sorties parlées étaient identiques à l’essai sans filtre. Sans filtre, UltiMed a produit une phrase sur l’un des contrôles de bruit. Whisper utilise Silero pour segmenter l’audio. Le tableau compare donc deux chaînes utilisables, avec des filtres distincts. Les quatre contrôles sont artificiels ; ils ne couvrent pas les bruits de cabinet ni les mots prononcés très brièvement.

Le P95 est le rang supérieur sur les 67 mesures. Il s’agit du temps de calcul après `end`, modèle chaud, sans délai de détection de la pause, interface ni micro. Le facteur temps réel P95 était de 0,63 pour Whisper et 0,033 pour UltiMed. La mémoire résidente maximale relevée pour les processus de décodage est de l’ordre de 1,0 Go pour Whisper et 1,7 Go pour UltiMed, sur Mac, avec des passages de longueurs différentes. Cette indication n’est pas une mesure des *Private Bytes* de l’application et du moteur sur Windows.

## Rejouer et qualifier

Depuis la racine du dépôt, préparer un dossier de mesure local avec l’archive PxCorpus v4 officielle. Le script vérifie son empreinte. Sans `--with-mac-synth`, il génère les 51 fichiers humains et les quatre contrôles, y compris sous Windows. Pour reproduire les mesures complètes avec les mêmes octets sur W1/W2, transférer les WAV de synthèse générés sur Mac ; ne pas refaire cette partie avec une autre voix.

```sh
python3 -m p0.corpus.prepare_head_to_head --px-archive /chemin/PxCorpus.zip --output /chemin/lot
```

Suivre les guides des [packs Whisper et Silero](../p0/bench/README.md#candidat-whisper--décodage-en-fin-de-phrase) et du [worker UltiMed](../p0/adapters/ultimed.md), avec `--speech-gate-dir` pour le candidat. Dans le banc utiliser le même manifeste et `--mode accelerated --chunk-ms 100 --warmup 1 --startup-timeout-s 90 --timeout-s 45 --include-text`, et quatre fils pour chaque worker. Pour le contrôle Px, comparer les sorties locales avec `python3 -m p0.review.px_paired /chemin/PxCorpus.zip --model whisper:/chemin/whisper/transcripts.ndjson --model ultimed:/chemin/ultimed/transcripts.ndjson`. Le rapprochement BDPM optionnel requiert le catalogue local, et ne constitue pas une correction des références. Les fichiers, les modèles et les sorties individuelles ne sont pas commités.

Avant distribution, vérifier l’export épinglé et son prétraitement dans un processus local supervisé, sans modifier le texte déjà validé. Mesurer sur deux PC Windows, dont le poste de 8 Go sans GPU, le délai jusqu’à l’affichage, la mémoire de l’application et du moteur, et l’endurance sur dictées longues. Tester les quantités administrées, fractions, décimaux, unités et négations sur des voix inédites avec relecture indépendante. Toute erreur critique reproductible sans mitigation bloque le pilote. Voir les [seuils du projet](feuille-de-route.md#critères-mesurables-proposés). Le [corpus Med-Dictate FR](https://huggingface.co/datasets/corti/med-dictate/tree/main/fr) peut compléter la validation des notes longues ; sa [licence](https://huggingface.co/datasets/corti/med-dictate/blob/main/LICENCE.md) autorise le benchmark et exclut l’entraînement ou l’adaptation à partir des données.
