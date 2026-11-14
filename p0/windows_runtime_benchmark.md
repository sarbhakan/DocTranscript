# P0 · Whisper natif et CTranslate2 sur le même hôte Windows

**Garder Whisper.cpp Turbo Q5_0 et OpenBLAS comme unique moteur candidat à l’essai Windows.** Lors de la première comparaison, CTranslate2 INT8 a réduit le temps de calcul médian de **12,93 s à 7,05 s** sur les huit mêmes tranches. Son contrôle des deux fractions de `px-584` passe dans deux des trois runs, mais obtient 0/2 expressions attendues sur EPYC 7763 ; la sortie de ce dernier run n’est pas conservée et sa notation exacte reste inconnue. Le moteur natif a passé ce contrôle sur les trois. Le calcul seul dépasse déjà les 2 s visées pour le rendu après pause ; aucun de ces essais sur VM ne qualifie un PC physique à 8 Go.

Le [premier run Windows `43614042322`](https://github.com/sarbhakan/DocTranscript/actions/runs/43614042322) a mesuré les trois configurations successivement sur une VM AMD EPYC 9V74, 2 cœurs, 4 processeurs logiques, environ 17,17 Go de RAM. Révision : [`265d16`](https://github.com/sarbhakan/DocTranscript/commit/265d16). Le SHA-256 `5357bb1dbe8ae436b8858d0276492d5f9f8e8df8e0ba51662b31655a7c5dcc2d` identifie l’archive **Mesures-Windows**, distincte du paquet d’essai. Les [mesures agrégées et leurs empreintes](windows_runtime_benchmark.json) ne contiennent ni audio ni transcription. Ce run compare les temps du moteur ; il ne qualifie ni le parcours d’interface ni un poste physique à 8 Go.

## Entrées et chronomètres

Trois [enregistrements de prescriptions simulées PxCorpus](fixtures/README.md), soit 38,44 s de WAV, donnent huit tranches avec **Silero GGML 6.2 et une pause de 576 ms**. Le [verrou des tranches](packs/ct2-silero-slices.lock.json) donne les bornes et les empreintes SHA-256 de la source et des tranches PCM. Les huit empreintes FNV-1a du signal float32 reçu par le moteur natif sous Windows correspondent au verrou utilisé pour alimenter CTranslate2. FNV-1a sert ici à vérifier la concordance des signaux observés, pas à authentifier un fichier.

- **Natif — whisper.cpp 1.8.5, OpenBLAS 0.3.34, AVX2, quatre threads.** Le modèle Turbo Q5_0 tourne sans GPU. Chaque WAV complet est rejoué rapidement par un nouveau processus moteur : le total par fichier couvre démarrage, chargement, détection, décodage et fin du processus. Pour chaque tranche, le chronomètre du journal vise `whisper_full` ; la première tranche de chaque fichier n’a pas été précédée d’un préchauffage de décodage. Le moteur utilise le français, un décodage glouton et aucun contexte de texte entre tranches. Silero tourne en amont, sans deuxième détection dans Whisper.
- **Sonde — faster-whisper 1.2.1 et CTranslate2 4.9.0**, un seul worker CPU en `int8_float32`, avec quatre threads puis deux. Le checkpoint amont est le même Whisper Large-v3 Turbo ; le [modèle converti](packs/ct2-turbo.lock.json), les représentations Q5_0/INT8 et les réglages de décodage diffèrent. La sonde utilise le français, un faisceau et un candidat, température zéro, sans texte précédent. Elle préchauffe le modèle sur `px-826` avant de mesurer ; la mesure par tranche couvre la transcription et l’itération de ses résultats, sans la conversion PCM ni la détection de parole. Le total par fichier de la sonde inclut la conversion PCM, mais exclut l’import, le chargement et le préchauffage. L’[environnement Python](packs/ct2-cp312-win-amd64.lock.txt) est celui du banc, pas un deuxième paquet utilisateur.

Les deux chronomètres par tranche n’ont pas exactement les mêmes bornes. Les mêmes entrées sur le même hôte réduisent une source d’écart, mais cet essai séquentiel ne sépare pas l’effet de la bibliothèque de ceux du préchauffage, de la quantification et du décodage. Aucun temps d’interface, de microphone ou de file d’attente en dictée réelle n’est mesuré.

## Première comparaison : temps et mémoire

| Calcul par tranche, huit tranches appariées | Natif, 4 threads | CTranslate2, 4 threads | CTranslate2, 2 threads |
| --- | ---: | ---: | ---: |
| Médiane | 12,933 s | 7,049 s | 8,696 s |
| Min. – max. | 12,809 – 13,118 s | 6,969 – 7,179 s | 8,285 – 8,776 s |
| Somme | 103,424 s | 56,503 s | 69,250 s |
| Somme native / somme de la configuration | 1,00× | 1,83× | 1,49× |

| Contrôle | Durée du WAV | Tranches | Natif, rejeu complet à froid | CTranslate2, 4 threads, préchauffé | CTranslate2, 2 threads, préchauffé |
| --- | ---: | ---: | ---: | ---: | ---: |
| `px-826` | 6,44 s | 1 | 13,995 s | 7,179 s | 8,766 s |
| `px-23` | 16,80 s | 4 | 53,108 s | 28,164 s | 34,938 s |
| `px-584` | 15,20 s | 3 | 39,602 s | 21,162 s | 25,547 s |
| Silence natif | 8,00 s | 0 | 1,093 s ; aucun texte | — | — |

Sur la sonde à quatre threads, import 0,552 s, chargement 2,757 s, préchauffage 7,219 s ; à deux threads, 0,122 s, 2,599 s et 8,596 s. Le maximum de **mémoire privée échantillonnée** dans l’arbre de processus, avec un intervalle demandé de 200 ms, atteint 1 992 622 080 octets pour le contrôle natif le plus élevé (`px-584`), et 2 026 213 376 / 2 024 824 832 octets pour les sondes complètes à quatre / deux threads. Les exécutions n’ont pas des périmètres identiques et l’échantillonnage peut manquer un pic plus court. Les deux sondes dépassent 2 Go décimaux sur ce relevé ; ces chiffres ne démontrent pas le confort sur un poste à 8 Go.

## Première comparaison : fidélité

Les trois configurations donnent les mêmes résultats aux contrôles automatiques. Sur `px-23` et `px-584`, les deux doses et les trois fractions attendues sont retrouvées, dans la même suite numérique, sans concentration ni négation ajoutée. Le terme de `px-584` passe ; **« Imovane » sur `px-23` ne passe dans aucune configuration**. Ces contrôles ne démontrent pas que chaque médicament, quantité et moment de prise restent associés à la bonne proposition. Aucune des trois références ne contient une négation prononcée : l’absence de négation ajoutée ne mesure pas la conservation d’une négation dictée.

Sur `px-826`, les trois résultats historiques gardent `numeric_sequence_equal=false` et `passed=false` bien que la dose et le terme passent. La reproduction native sur Mac a isolé un défaut du scoreur : « une gélule » était écarté de la suite numérique face à « 1 gélule ». Le deuxième run passe ce cas avec le scoreur corrigé ; les sorties brutes du premier run ne sont pas disponibles pour confirmer leur libellé exact. Les valeurs historiques sont conservées.

## Deuxième comparaison : stabilité des fractions

Le [run `43616372644`](https://github.com/sarbhakan/DocTranscript/actions/runs/43616372644) ([`b880817`](https://github.com/sarbhakan/DocTranscript/commit/b880817)) rejoue les trois mêmes WAV avec CTranslate2 à quatre threads et ajoute le lot Corti. L’hôte est une VM sur AMD EPYC 7763 avec 2 cœurs, 4 processeurs logiques et 17 174 360 064 octets de RAM, relevés dans le journal natif. Le SHA-256 `a4fe29f28e2224e455f735976bb9cd5e3ff003a5cef6aec1fcd5ead59e5c54eb` correspond à l’archive **Mesures-Windows** de ce run.

| Contrôle | Whisper.cpp, rejeu complet à froid | CT2, rejeu préchauffé | Doses / fractions Whisper.cpp | Doses / fractions CT2 |
| --- | ---: | ---: | ---: | ---: |
| `px-826` | 16,252 s | 10,714 s | 1/1 · — | 1/1 · — |
| `px-23` | 60,482 s | 42,825 s | 1/1 · 1/1 | 1/1 · 1/1 |
| `px-584` | 45,999 s | 32,553 s | 1/1 · 2/2 | 1/1 · **0/2** |

Ce deuxième run passe `px-826` pour les deux moteurs. Sur `px-584`, CT2 ne retrouve aucune des deux expressions de fraction associées à un moment de prise et sa suite des nombres normalisés diffère de la référence. Le moteur natif passe les deux contrôles sur les deux runs. Les deux moteurs reconnaissent deux noms de médicaments sur trois ; « Imovane » manque toujours. CT2 avait passé `px-584` lors du premier run, y compris à deux threads : **la non-régression de cette sortie n’est pas établie entre hôtes**.

L’artefact de ce run n’inclut ni le texte reconnu ni les suites numériques. Le scoreur accepte « un demi », « 1/2 » et « ½ » au bon endroit, mais une forme comme « 0,5 le matin » n’est pas normalisée en fraction. Ce cas possible n’exclut ni un nombre erroné ni une omission. [CTranslate2 choisit notamment MKL ou oneDNN selon le type de CPU et la construction](https://github.com/OpenNMT/CTranslate2/blob/v4.9.0/src/cpu/backend.cc#L7-L61). Les deux processeurs observés sont des AMD EPYC ; aucun changement de backend entre ces runs n’a été établi. Les différences de quantification et de décodage entre moteurs ne suffisent pas non plus à expliquer cet écart.

CT2 calcule une tranche en **10,735 s de médiane** (min. 10,653 ; max. 11,001 ; somme 86,089 s), hors détection de pauses, avec 2 025 652 224 octets de mémoire privée au plus haut échantillon du processus complet. Le contrôle natif le plus élevé sur ce run atteint 1 955 422 208 octets. Les temps de rejeu de la table ont des périmètres différents et ne constituent pas un rapport de vitesse de bout en bout.

## Troisième comparaison : journal des suites numériques

Le [run `43618734575`](https://github.com/sarbhakan/DocTranscript/actions/runs/43618734575) ([`0c0661b`](https://github.com/sarbhakan/DocTranscript/commit/0c0661b6916916419242ca4b8884de7ef32b23d1)) rejoue les mêmes cas sur une VM AMD EPYC 9V74, 2 cœurs et 4 processeurs logiques. Le SHA-256 `30359c486361903972e2bf3effd2688690bae39280063790d2ade03ce2de61cf` est celui de l’archive **Mesures-Windows**. Le scoreur enregistre maintenant la suite attendue et la suite obtenue pour chaque cas fictif, sans changer la règle de réussite ni publier la transcription.

| Contrôle | Whisper.cpp, rejeu complet à froid | CT2, rejeu préchauffé | Suite numérique normalisée, identique pour les deux |
| --- | ---: | ---: | --- |
| `px-826` | 14,202 s | 7,349 s | `20 · 1` |
| `px-23` | 53,480 s | 28,531 s | `7,5 · 1 · ¼ · 7` |
| `px-584` | 40,548 s | 21,427 s | `80 · ½ · ½ · 2` |

Les deux moteurs passent les trois contrôles automatiques, avec trois doses et trois fractions reconnues. « Imovane » reste manquant pour les deux. CT2 retrouve ici les deux fractions de `px-584`, avec une suite exacte ; cela ne restitue pas la sortie du run précédent sur EPYC 7763 et n’en clôt pas l’écart. Cette comparaison établit une réussite sur le 9V74, pas une relation de cause à effet avec le matériel.

CT2 calcule une tranche en **7,139 s de médiane** (min. 7,077 ; max. 7,348 ; somme 57,306 s), hors détection des pauses. Le pic échantillonné de mémoire privée atteint 2 092 257 280 octets pour la sonde et 1 955 414 016 octets pour le contrôle natif le plus élevé. Le contrôle sans parole natif se termine en 1,101 s. Le calcul de la sonde ne mesure toujours ni capture micro ni affichage réel.

## Contrôle des négations : deux dictées Corti

Le [contrôle Corti](windows/ct2_corti.md) compare CT2 Windows aux sorties antérieures de Whisper.cpp Mac sur deux notes en français, soit quatre minutes d’audio et 18 tranches figées. Il mesure des correspondances strictes de spans ; les chronomètres des deux plateformes ne sont pas comparés.

| Mesure | Whisper.cpp macOS | CT2 Windows EPYC 7763 | CT2 Windows EPYC 9V74 |
| --- | ---: | ---: | ---: |
| Négations | 7/12 | 7/12 | 7/12 |
| Doses | 3/4 | 3/4 | 3/4 |
| Latéralités | 1/3 | 1/3 | 1/3 |
| Attributs critiques, total | 18/27 | 18/27 | 18/27 |
| Écarts lexicaux normalisés | 110/433 (25,40 %) | 107/433 (24,71 %) | 109/433 (25,17 %) |

Les mêmes 18 attributs sont correctement reconnus dans les trois exécutions, sans gain ni perte de span strict pour CT2 par rapport à la référence Mac. Les cinq autres négations ne sont retrouvées dans aucune sortie selon ce score. Ce résultat ne vérifie ni tous les ajouts ni la portée des négations, et n’établit pas une équivalence clinique. CT2 a cumulé 212,206 s puis 144,884 s de calcul par lot de 18 tranches préchauffées, sans microphone ni interface. Source : Corti ApS, Nix et al., [*Symphony for Speech-to-Text: Supporting Real-Time Medical Voice Interfaces*](https://doi.org/10.48550/arXiv.2605.16545), usage [réservé à l’évaluation](https://huggingface.co/datasets/corti/med-dictate/blob/2a840558d221b4f306c52419d58f93270ea599bb/LICENCE.md).

Conserver le moteur natif et une seule configuration produit pour la prochaine recette. CTranslate2 reste un banc de comparaison à déclencher à la demande, en dehors de la construction du produit. Avant d’envisager son intégration, reproduire le contrôle `px-584` sur les hôtes qui diffèrent, relire les fractions et leur moment de prise, confirmer la polarité sur de nouvelles dictées et mesurer le paquet complet sur les deux [PC physiques de la recette](../docs/windows-recette-030.md). La stabilité des champs médicaux et une latence acceptable restent à démontrer avant usage réel.
