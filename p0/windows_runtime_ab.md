# Comparer les versions de Whisper sur le même CPU Windows

Le moteur du paquet d’essai 0.4 reste Whisper Turbo Q5_0, avec le runtime natif 1.8.5 et OpenBLAS. Dans le [run du paquet exact 0.4](https://github.com/sarbhakan/DocTranscript/actions/runs/43664693895), la VM Windows EPYC 9V74 (2 cœurs/4 fils logiques, 17,17 Go de RAM) a traité trois dictées de 6,44 s, 16,8 s et 15,2 s en **14,434 s, 52,710 s et 40,336 s** respectivement, lancement inclus. Le plus haut échantillon mémoire privée des processus du paquet était de 1 955 401 728 octets, soit 1,82 Gio. Les doses, fractions et suites numériques testées ont été préservées ; un nom de médicament manque. Ce résultat fixe le point de départ ; il ne mesure pas un vrai poste de 8 Go ni le délai d’affichage au micro.

Le premier candidat est [whisper.cpp 1.9.5](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5). Il conserve une API native compatible avec le pont : [initialisation depuis un chargeur et état Silero par trame](https://github.com/ggml-org/whisper.cpp/blob/v1.9.5/include/whisper.h). On le compile avec son propre en-tête : le support des mêmes fonctions C ne garantit pas que des structures échangées par valeur soient interchangeables. L’archive est contrôlée par SHA-256 `ff1a9053feb509ff9d7729703355541ae9690073a6b1c40eb692c962e0dc1720`. Le code Whisper est sous [licence MIT](https://github.com/ggml-org/whisper.cpp/blob/v1.9.5/LICENSE) ; les deux bras utilisent le même [OpenBLAS 0.3.34 sous licence BSD](https://github.com/OpenMathLib/OpenBLAS/blob/v0.3.34/LICENSE).

Il s’agit de mesurer les changements de Whisper et de ses noyaux GGML, à modèle et pont constants. Les deux versions activent déjà l’attention Flash dans leurs paramètres par défaut. Le [chemin OpenBLAS 1.9.5](https://github.com/ggml-org/whisper.cpp/blob/v1.9.5/ggml/src/ggml-blas/ggml-blas.cpp) conserve la conversion des matrices quantifiées pour le produit `cblas_sgemm`, ainsi que le réglage du nombre de fils par appel. On ne peut donc ni présumer d’un gain de latence, ni tester un réglage OpenBLAS en changeant uniquement une variable d’environnement. Le 1.8.5 du banc inclut le [correctif de réinitialisation du générateur](https://github.com/ggml-org/whisper.cpp/commit/6d0ed914991cac42ace012a05588880801831343), déjà intégré au code 1.9.5. La [réduction du contexte audio](audio_context_ablation.md), le [décodage beam5](decoder_consolidation.md) et [CT2 INT8](windows_runtime_benchmark.md) ont déjà produit des pertes sur des cas critiques de développement ou de régression ; on ne les active pas dans cette comparaison.

## Résultat sur la VM Windows

Le [run 43667755235](https://github.com/sarbhakan/DocTranscript/actions/runs/43667755235) ([révision 5442882](https://github.com/sarbhakan/DocTranscript/commit/54428823e7cd87e70df565db0d730b54dbc325e9)) a comparé les deux bras sur **la même VM** EPYC 7763, 2 cœurs, 4 fils logiques, 17 174 360 064 octets de RAM, Windows NT 10.0.20348. Les [mesures et leur provenance](windows_runtime_ab_report.json) reprennent l’archive **ASR-Windows-AB** (SHA-256 `cd7255295bd4f8c37f753ab1de3ac967e207f1626ec5f1e5c6ba79252de02295`). Cette empreinte identifie l’archive des mesures, distincte du ZIP NoteVive.

| Mesure | 1.8.5 avec correctif RNG | 1.9.5 |
|---|---:|---:|
| Rejeu à chaud, médiane sur 6 dictées | 45,60 s | 43,50 s |
| Rapport temps de calcul / durée audio à chaud, médiane | 3,00 | 2,86 |
| Calcul d’une tranche à chaud, médiane sur 16 tranches | 15,10 s | 14,38 s |
| Calcul d’une tranche à chaud, P95 empirique | 15,69 s | 14,96 s |
| Nouveau processus et dictée `px-826`, médiane sur 2 passages | 15,50 s | 16,22 s |
| Chargement du pont et des modèles dans le nouveau processus, médiane | 190 ms | 188 ms |
| Mémoire privée maximale échantillonnée | 1 982 943 232 octets | 1 981 001 728 octets |
| Mémoire résidente maximale échantillonnée | 847 110 144 octets | 844 685 312 octets |

Le rapport médian des six rejeux **appariés** est de **0,948**, soit environ **5,2 % de temps en moins** à chaud sur cette VM. Le P95 empirique baisse également. Le temps médian du nouveau processus avec dictée est plus élevé chez le candidat, mais avec deux passages seulement et un temps de chargement très proche, cet écart ne permet pas d’attribuer un ralentissement au chargement. Les modèles ont été lus pour vérifier leurs empreintes avant la mesure : « nouveau processus » ne signifie pas « cache disque vide ». Les maxima mémoire sont des échantillons relevés à un intervalle demandé de 50 ms, avec Python inclus ; ils peuvent manquer des pics. Les échecs individuels de sondage ne sont pas dénombrés.

Les 10 paires de sorties (dictées, passages à froid et silence compris) ont le même texte et les mêmes tranches PCM aux mêmes pauses ; les deux répétitions sont stables. Sur les trois dictées distinctes, les deux versions préservent les doses (3/3), les fractions (3/3) et les suites numériques (3/3). Elles reconnaissent les mêmes deux médicaments sur trois et omettent le même nom sur `px-23`. Le silence ne produit aucun texte. Aucune amélioration de fidélité n’est démontrée.

**Décision : garder 1.8.5 dans le produit.** Le candidat n’atteint pas le seuil de gain fixé à 20 %, et son RTF à chaud reste nettement au-dessus de 1 sur cet hôte. Cette mesure ne qualifie ni les négations prononcées ni la latence au micro sur un PC physique de 8 Go. Une autre VM doit faire l’objet d’un relevé distinct plutôt que d’une moyenne avec celui-ci.

## Réplication sur le code final

Le [run 43669761750](https://github.com/sarbhakan/DocTranscript/actions/runs/43669761750), sur la [révision 7aebb25](https://github.com/sarbhakan/DocTranscript/commit/7aebb25038bb94fffdf2d2990a66463a093807fb), utilise les mêmes modèles, réglages et fichiers, avec un inventaire Windows de même profil EPYC 7763. Ses [mesures séparées et leur provenance](windows_runtime_ab_replication.json) proviennent de l’archive de mesures SHA-256 `96a5b8b2df404c187b38b8f91928db932760c883f52cd58096e4bc9678444d31`.

| Mesure de la réplication | 1.8.5 avec correctif RNG | 1.9.5 |
|---|---:|---:|
| Rejeu à chaud, médiane sur 6 dictées | 45,31 s | 44,94 s |
| Calcul d’une tranche à chaud, médiane sur 16 tranches | 15,05 s | 14,85 s |
| Calcul d’une tranche à chaud, P95 empirique | 17,65 s | 15,66 s |
| Nouveau processus et dictée `px-826`, médiane sur 2 passages | 15,62 s | 15,48 s |

Le rapport médian **apparié** est de **0,974405**, soit **2,56 % de gain à chaud**, contre 5,20 % au premier passage. Les dix paires ont encore un texte et des portions PCM identiques entre versions dans cette exécution. Les doses, fractions et suites numériques restent à 3/3 et les noms de médicaments à 2/3. Ces contrôles portent sur les mêmes trois prescriptions et un silence ; ce ne sont pas de nouvelles dictées indépendantes.

Les rapports ne contiennent pas les textes bruts : l’égalité textuelle exacte **entre les deux exécutions** n’est pas établie. Les mesures restent séparées, sans moyenne entre exécutions ni assimilation à une validation clinique. Le petit écart au démarrage change de sens ; aucun gain stable de démarrage n’est démontré. Les deux gains à chaud restent sous le seuil de 20 % et la décision de conserver 1.8.5 est inchangée.

## Rejouer sur Windows

Préparer Windows x64, la même compatibilité AVX2 que NoteVive, Python 3.12 x64, Visual Studio 2022 avec le SDK x64 et ClangCL, CMake et Ninja. Lancer à la racine du dépôt dans PowerShell :

```powershell
python -m unittest p0.bench.test_runtime_ab
python -m p0.windows.runtime_ab --output "$env:TEMP/notevive-asr-ab" --jobs 4 --repeats 2
```

La sortie doit être un nouveau répertoire. Le script télécharge les deux archives sources, OpenBLAS, le poids Whisper Turbo Q5_0 et le poids Silero 6.2 ; leurs SHA sont imposés. Pour séparer la préparation connectée de la mesure déconnectée, réutiliser les cinq fichiers déjà préparés et vérifiés avec `--downloads C:\chemin\du\cache`. Aucune dépendance Python externe. Les deux DLL sont construites avec le même ClangCL, OpenBLAS statique Haswell (la même archive compilée dans les deux bras), CRT statique et sans GPU. Le pont NoteVive est copié dans le répertoire temporaire ; seule sa vérification textuelle de version change sur le bras 1.9.5. Aucune substitution de DLL du ZIP distribué.

- Les fichiers sont [trois dictées françaises fictives PxCorpus](fixtures/README.md), aux empreintes WAV et PCM vérifiées. Un fichier de silence numérique de huit secondes contrôle les sorties sans parole. Les deux bras passent le PCM complet au vrai pont et à Silero, en lots de 320 échantillons comme le paquet Windows, avec temporisation de pause 576 ms, un fil VAD, quatre fils ASR et le décodage français greedy à contexte audio standard. Les empreintes de tranches PCM, leur nombre d’échantillons, le paquet contenant le déclenchement et la phase pause/arrêt sont comparés.
- Deux répétitions alternent **A puis B**, **B puis A**. Un seul moteur tourne à la fois. Chaque bras a un processus neuf pour `px-826` et un autre processus pour l’ensemble à chaud, après un passage d’échauffement de `px-826`. « À froid » désigne ici un nouveau processus et modèle non chargé ; le cache de fichiers Windows n’est pas purgé. « À chaud » désigne le rejeu VAD + Whisper, sans micro, transfert vers l’interface ni attente entre les blocs audio.
- Le rapport fournit le temps de lancement et le temps de chargement du pont et des modèles séparément, le temps de rejeu ramené à la durée du fichier (RTF), la médiane et le P95 empirique du décodage des tranches, les pics échantillonnés à 50 ms de mémoire privée et de mémoire résidente (*working set*). Le P95 ne représente qu’un petit échantillon. Les données de mémoire concernent le processus du banc, qui inclut Python ; elles ne remplacent pas les mesures du ZIP.
- Les deux sorties sont comparées pour égalité exacte du texte, stabilité entre répétitions, conservation des doses, fractions, quantités, termes et absence d’une négation ajoutée. Une baisse sur un fichier est visible même si le score moyen reste constant. Les trois cas sont affirmatifs : ils ne vérifient pas la préservation d’une négation présente, son objet ni le maintien des associations entre plusieurs médicaments. Les transcriptions ne sont ni publiées ni écrites sur disque par le contrôleur ; seuls `report.json` et l’inventaire matériel de la CI sont à partager.

Pour passer à une confirmation, on recherche un rapport médian candidat/témoin à chaud ≤ 0,80, un P95 de tranche non dégradé, les mêmes tranches, des textes stables et aucune perte sur les champs mesurés. Tout texte différent à score égal requiert une revue de fidélité. Ce seuil de tri ne qualifie pas le moteur : la qualité doit ensuite être vérifiée sur de nouvelles voix et dictées fictives, avec plusieurs médicaments, unités, doses fractionnées et négations ciblées, et le gain doit être confirmé sur les deux PC Windows physiques, dont le 8 Go sans GPU dédié, avec dictée au micro et mesure jusqu’à l’affichage. En l’absence de ces données, le produit reste sur le moteur 0.4.
