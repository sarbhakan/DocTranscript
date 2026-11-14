# P0 · Whisper natif et CTranslate2 sur le même hôte Windows

Sur huit mêmes tranches de parole, **CTranslate2 INT8 à quatre threads ramène le temps médian de calcul d’environ 12,93 s à 7,05 s**. Avec deux threads, la médiane est de 8,70 s. CTranslate2 mérite une suite pour les performances, mais le calcul à lui seul reste bien au-delà de l’objectif de 2 s après la fin de la parole. Le paquet Windows équipé de whisper.cpp reste le candidat d’essai ; aucun ZIP 0.3.0 n’est publié dans les Releases.

Le [run Windows `43614042322`](https://github.com/sarbhakan/DocTranscript/actions/runs/43614042322) a mesuré les trois configurations successivement sur une VM AMD EPYC 9V74, 2 cœurs, 4 processeurs logiques, environ 17,17 Go de RAM. Révision : [`265d16`](https://github.com/sarbhakan/DocTranscript/commit/265d16). SHA-256 du ZIP candidat : `5357bb1dbe8ae436b8858d0276492d5f9f8e8df8e0ba51662b31655a7c5dcc2d`. Les [mesures agrégées et leurs empreintes](windows_runtime_benchmark.json) ne contiennent ni audio ni transcription. Ce run compare les temps du moteur ; il ne qualifie ni le parcours d’interface ni un poste physique à 8 Go.

## Entrées et chronomètres

Trois [enregistrements de prescriptions simulées PxCorpus](fixtures/README.md), soit 38,44 s de WAV, donnent huit tranches avec **Silero GGML 6.2 et une pause de 576 ms**. Le [verrou des tranches](packs/ct2-silero-slices.lock.json) donne les bornes et les empreintes SHA-256 de la source et des tranches PCM. Les huit empreintes FNV-1a du signal float32 reçu par le moteur natif sous Windows correspondent au verrou utilisé pour alimenter CTranslate2. FNV-1a sert ici à vérifier la concordance des signaux observés, pas à authentifier un fichier.

- **Natif — whisper.cpp 1.8.5, OpenBLAS 0.3.34, AVX2, quatre threads.** Le modèle Turbo Q5_0 tourne sans GPU. Chaque WAV complet est rejoué rapidement par un nouveau processus moteur : le total par fichier couvre démarrage, chargement, détection, décodage et fin du processus. Pour chaque tranche, le chronomètre du journal vise `whisper_full` ; la première tranche de chaque fichier n’a pas été précédée d’un préchauffage de décodage. Le moteur utilise le français, un décodage glouton et aucun contexte de texte entre tranches. Silero tourne en amont, sans deuxième détection dans Whisper.
- **Sonde — faster-whisper 1.2.1 et CTranslate2 4.9.0**, un seul worker CPU en `int8_float32`, avec quatre threads puis deux. Le checkpoint amont est le même Whisper Large-v3 Turbo ; le [modèle converti](packs/ct2-turbo.lock.json), les représentations Q5_0/INT8 et les réglages de décodage diffèrent. La sonde utilise le français, un faisceau et un candidat, température zéro, sans texte précédent. Elle préchauffe le modèle sur `px-826` avant de mesurer ; la mesure par tranche couvre la transcription et l’itération de ses résultats, sans la conversion PCM ni la détection de parole. Le total par fichier de la sonde inclut la conversion PCM, mais exclut l’import, le chargement et le préchauffage. L’[environnement Python](packs/ct2-cp312-win-amd64.lock.txt) est celui du banc, pas un deuxième paquet utilisateur.

Les deux chronomètres par tranche n’ont pas exactement les mêmes bornes. Les mêmes entrées sur le même hôte réduisent une source d’écart, mais cet essai séquentiel ne sépare pas l’effet de la bibliothèque de ceux du préchauffage, de la quantification et du décodage. Aucun temps d’interface, de microphone ou de file d’attente en dictée réelle n’est mesuré.

## Temps et mémoire observés

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

## Fidélité constatée et prochaine décision

Les trois configurations donnent les mêmes résultats aux contrôles automatiques. Sur `px-23` et `px-584`, les deux doses et les trois fractions attendues sont retrouvées, dans la même suite numérique, sans concentration ni négation ajoutée. Le terme de `px-584` passe ; **« Imovane » sur `px-23` ne passe dans aucune configuration**. Ces contrôles ne démontrent pas que chaque médicament, quantité et moment de prise restent associés à la bonne proposition. Aucune des trois références ne contient une négation prononcée : l’absence de négation ajoutée ne mesure pas la conservation d’une négation dictée.

Sur `px-826`, les trois résultats bruts gardent `numeric_sequence_equal=false` et `passed=false` bien que la dose et le terme passent. La reproduction native sur Mac a isolé un défaut du scoreur : « une gélule » est écarté de la suite numérique face à la référence « 1 gélule ». Les transcriptions Windows ne sont pas conservées ; la même explication est plausible mais reste à confirmer sur ce run de comparaison. Le correctif ciblé et son test sont prêts. Il faut rejouer les trois configurations avec le scoreur corrigé, sans réécrire les résultats bruts historiques.

Garder CTranslate2 comme piste de réduction du temps de calcul. Avant un changement de moteur, rejouer les mêmes tranches à froid et à chaud avec des options aussi proches que possible, contrôler le lot inédit de 12 négations Corti en préparation et mesurer le parcours de bout en bout sur les deux [PC physiques de la recette](../docs/windows-recette-030.md). Le candidat natif, lui aussi trop lent sur cette VM, reste non publié.
