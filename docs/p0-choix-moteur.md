# P0 · Décision Windows et historique des comparaisons

**Candidat unique pour le ZIP d’essai Windows 0.3.0 : Whisper Large-v3 Turbo Q5_0, whisper.cpp 1.8.5, OpenBLAS 0.3.34 et Silero VAD GGML 6.2.0, pause de 576 ms.** Le [benchmark élargi sur Mac](../p0/asr_benchmark.md) a comparé cinq modèles sur 89 fichiers audio. Le pont natif à 576 ms y préserve les huit fractions annotées du lot difficile mais commet encore des erreurs de doses, de négations et de termes médicaux. Son P95 estimé de 4,20 s entre la fin de parole et le texte dépasse le seuil de 2 s, sans mesure du micro ni de l’écran. CTranslate2 reste un moteur de comparaison du banc et n’entre pas dans le paquet Windows. La recette automatisée du paquet passe sous Windows Server 2022 ; les deux PC physiques restent à qualifier.

## Ce que montrent les premiers tests Windows

Les essais ont rejoué le même [fichier de parole française fictive de 6,44 s](../p0/fixtures/README.md) avec le moteur du ZIP, en CI sur des machines virtuelles de deux cœurs et quatre processeurs logiques. Les temps totaux incluent le démarrage du moteur ; ce ne sont ni une latence d’affichage, ni un P95.

| Compilation et hôte CI | Traitement total AVX2 | Variante SSE2 |
| --- | ---: | --- |
| [MSVC, AMD EPYC 7763](https://github.com/sarbhakan/DocTranscript/actions/runs/43606814807) | 35,435 s | Délai de 90 s dépassé |
| ClangCL, Intel Xeon Platinum 8573C | 38,510 s, dont 36,888 s d’encodage, sans repli du décodeur | Délai de 90 s dépassé |
| [ClangCL + `GGML_LLAMAFILE`, Intel Xeon Platinum 8573C, 17,17 Go de RAM](https://github.com/sarbhakan/DocTranscript/actions/runs/43609865149) | 30,330 s, dont 28,689 s d’encodage, sans repli du décodeur ; paire « Prozac 20 mg » reconnue | Délai de 90 s dépassé |
| [ClangCL + OpenBLAS 0.3.34, Intel Xeon Platinum 8573C, 17,17 Go de RAM](https://github.com/sarbhakan/DocTranscript/actions/runs/43612396023) | 14,742 s, dont 13,443 s dans Whisper et 13,272 s dans l’encodeur | Non testé dans la recette produit |

L’encodeur représente l’essentiel du temps. L’essai OpenBLAS garde les mêmes poids et le même contexte audio complet ; le journal confirme `nv_accel=BLAS`. Les temps de 30,330 s et 14,742 s proviennent de VM différentes du même type de processeur. Cette comparaison ne permet pas de chiffrer l’effet propre d’OpenBLAS. Les résultats AMD et Intel ne permettent pas non plus d’isoler l’effet du compilateur. Sur le contrôle de 6,44 s, le calcul Whisper dure encore plus de deux fois la durée de la parole, avant toute mesure au micro ou à l’écran.

La construction, le paquet, les tests natifs et les contrôles audio passent sur le premier run OpenBLAS. Lors de la mise au point de la recette, le script d’interface s’est d’abord arrêté sur `SetFocus`, puis à la recherche du dossier parent. Le [run de diagnostic `265d16`](https://github.com/sarbhakan/DocTranscript/actions/runs/43614042322) a isolé un cas de fournisseur UI Automation qui ne renvoyait pas les enfants du contrôle malgré la présence du dossier sur disque. Ces échecs n’établissent pas un plantage de NoteVive.

**Périmètre CPU du candidat : AVX2.** NoteVive vérifie la prise en charge d’AVX/AVX2 dans Windows et les extensions FMA, F16C, BMI1, BMI2, LZCNT, SSE4.2 et POPCNT. En cas d’incompatibilité, l’application garde l’accès aux notes mais ne charge pas le modèle et n’ouvre pas le micro. Les échecs SSE2 ci-dessus restent des résultats du diagnostic ; sa limite de 90 s demeure. La CI produit ne traite plus SSE2 comme un mode supporté.

### Détail du run OpenBLAS

Sur cet hôte CI (Xeon Platinum 8573C, deux cœurs, quatre processeurs logiques, 17 174 360 064 octets de RAM), le banc a mesuré le temps total et le maximum **échantillonné** de mémoire privée à travers les processus parent et moteur. Les temps ci-dessous incluent le démarrage et l’exécution du contrôle complet, y compris plusieurs segments sur les enregistrements longs.

| Audio | Traitement total | Maximum échantillonné (octets) | Résultat |
| --- | ---: | ---: | --- |
| Français court, 6,44 s | 14,742 s | 1 954 541 568 | Contrôle de parole réussi ; encodeur : 13,272 s. |
| `px-23`, 16,8 s | 57,819 s | 1 955 332 096 | 4 segments ; 1/1 dose, 1/1 fraction ; nom exact « Imovane » non reconnu (0/1). |
| `px-584`, 15,2 s | 42,915 s | 1 954 459 648 | 3 segments ; 1/1 dose, 2/2 fractions ; 1/1 terme. |
| Silence, 8 s | 1,322 s | — | Aucune sortie texte. |

Sur les deux [extraits de régression](../p0/fixtures/README.md), la suite des valeurs numériques est identique à la référence et aucune négation ni concentration n’a été ajoutée. Les termes sont comptés séparément ; ces contrôles ne valident ni leur association clinique aux doses ni la fidélité sur un lot indépendant. La mémoire échantillonnée est un repère sur cette VM, pas une qualification à 8 Go.

Le [run Windows `b880817`](https://github.com/sarbhakan/DocTranscript/actions/runs/43616372644) passe le silence et les contrôles chiffrés des trois dictées avec le moteur natif. Les temps totaux sont 16,252 s pour `px-826`, 60,482 s pour `px-23` et 45,999 s pour `px-584`. Les trois doses et les trois fractions attendues passent. La suite numérique, l’absence d’ajout de négation et l’absence d’ajout de concentration passent également ; le nom attendu sur `px-23` manque toujours. Le pic cumulé échantillonné tourne autour de 1,95 Go sur le runner ; ces mesures portent sur le traitement des fichiers, sans micro ni affichage.

Le [contexte audio réduit](../p0/audio_context_ablation.md) est écarté : il fait perdre 20 éléments critiques reconnus avec le contexte complet et réinsère, dans deux fichiers, une phrase issue d’une autre dictée fictive. Le contexte complet reste la référence. La recette automatisée du paquet est maintenant réussie. La prochaine validation porte sur les [deux PC physiques Windows](windows-recette-030.md), dont celui de 8 Go sans GPU dédié. La qualification clinique reste ouverte, indépendamment de la correction des performances.

## Comparaison Windows sur un même hôte

Le [comparatif CTranslate2 / whisper.cpp](../p0/windows_runtime_benchmark.md) mesure huit tranches identiques sur le run `265d16`. À quatre threads, CTranslate2 INT8 passe d’une médiane de 12,93 s à 7,05 s par tranche, avec environ 2 Go de mémoire privée échantillonnée dans les deux chaînes. Les doses et fractions de `px-23` et `px-584` ont les mêmes scores sur ce run. Le contrôle `px-826` brut échoue pour les trois configurations ; le scoreur ne normalisait pas la quantité féminine « une gélule » vers « 1 gélule ». La correction est ciblée et testée contre les quantités absentes, doublées ou répétées. Le contrôle `px-826` passe pour le moteur natif et CT2 sur `b880817` ; les anciens résultats bruts restent inchangés.

Sur `b880817`, CTranslate2 ne passe plus le contrôle `px-584` : **0/2 fractions reconnues par le scoreur**, suite numérique différente de la référence. La notation de la sortie doit être vérifiée avant de qualifier cette erreur ; la garde reste en échec. L’essai [sur deux notes longues Corti](../p0/windows/ct2_corti.md) trouve **7/12 négations strictes** pour CT2 Windows et 7/12 pour whisper.cpp Mac, sans gain ni perte appariés. Les cinq négations non validées, les deux seules notes et les différences de plateforme et de quantification limitent la portée du résultat. Les mesures de décodage ont également dépassé l’objectif de 2 s par tranche et n’incluent ni capture ni affichage. **CT2 n’est pas retenu dans le ZIP d’essai.** L’[étude d’un éventuel paquet CT2](../p0/windows-ct2-packaging.md) reste une piste future soumise à de nouveaux essais de fidélité et de vitesse, ainsi qu’à la validation de sa distribution hors ligne.

Le [troisième run `0c0661b`](https://github.com/sarbhakan/DocTranscript/actions/runs/43618734575), sur EPYC 9V74, retrouve les trois doses et trois fractions avec les deux moteurs ; CT2 donne cette fois la suite attendue `80 · ½ · ½ · 2`. Cela ne permet pas de reconstruire la sortie du run EPYC 7763, ni d’en attribuer la cause au processeur. CT2 reste un comparateur facultatif, relançable par `workflow_dispatch` avec `compare_ct2`. Le candidat produit reste le moteur natif, dont les contrôles numériques passent sur les trois comparaisons.

## Recette automatisée du paquet Windows

Le [run `88461ee`](https://github.com/sarbhakan/DocTranscript/actions/runs/43620136119) passe les tests du stockage chiffré, des migrations, du protocole, de la compatibilité CPU et de la reprise après panne du moteur. Le vrai ZIP est extrait puis testé : silence, trois prescriptions fictives et parcours complet de la bibliothèque, sans microphone. L’interface crée deux dossiers imbriqués et deux notes, vérifie les trois tris et la recherche sans accents, renomme et classe les notes, puis contrôle le contenu après réouverture.

Les [preuves agrégées](../p0/windows_release_candidate.json) conservent l’environnement, les mesures et l’état des étapes. Hôte : VM Windows Server 2022, AMD EPYC 9V45, 2 cœurs et 4 processeurs logiques, 17 174 360 064 octets de RAM. Les replays natifs à froid prennent 12,157 s pour 6,44 s d’audio, 45,451 s pour 16,8 s et 34,542 s pour 15,2 s. Les trois doses, trois fractions et suites numériques passent ; le nom exact « Imovane » manque encore. Le maximum de mémoire privée échantillonnée atteint 1 955 536 896 octets. Ces temps ne sont pas ceux d’une dictée au micro ; la différence de VM interdit de les attribuer à une nouvelle optimisation du moteur.

Les problèmes d’automatisation ont été corrigés en lisant les contrôles natifs Windows et en actionnant le vrai menu de renommage. Aucune assertion de persistance, de tri ou de classement n’a été retirée. CTranslate2 et Corti restent relançables explicitement dans le workflow, sans téléchargement de leurs dépendances dans une construction produit ordinaire. La [préversion 0.3.0](https://github.com/sarbhakan/DocTranscript/releases/tag/v0.3.0-essai) reste destinée aux essais fictifs ; elle n’est ni une qualification Windows 11 physique, ni une qualification du poste de 8 Go ou de la fidélité clinique.

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
