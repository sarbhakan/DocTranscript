# P0 · Choix du moteur de dictée, 14 novembre 2026

**Décision : Parakeet UltiMed INT8 avec filtre de présence de parole Silero est le seul candidat retenu pour l’intégration.** Whisper Turbo reste un témoin du banc. UltiMed reconnaît davantage de noms médicaux et renvoie le texte plus vite sur ce Mac. Les deux moteurs commettent des erreurs numériques graves. Ce choix oriente le développement ; le moteur de l’application livrée reste inchangé jusqu’à qualification.

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
