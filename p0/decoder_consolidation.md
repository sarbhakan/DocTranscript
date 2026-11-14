# Consolidation du décodeur — 14 novembre 2026

**Décision : conserver le décodage actuel et intégrer le correctif officiel de reproductibilité.** Le profil plus large `beam5` reste au banc : ses gains ne compensent pas les nouvelles pertes de médicament et d’association médicament–dosage. Aucun poids n’a été entraîné et aucun gain médical n’est attribué au correctif de reproductibilité.

Les [résultats agrégés](decoder_consolidation.json) contiennent les empreintes, les effectifs et les gains **et** pertes appariés. Les sorties brutes restent locales. Les [comparaisons historiques des moteurs](asr_benchmark.md) restent disponibles sans réécriture de leurs résultats.

## Méthode

Trois profils ont traité les **85 mêmes WAV de développement**, soit 255 transcriptions, sur le Mac M1 Pro, 16 Gio, CPU à quatre fils de calcul. Le lot comprend 51 prescriptions humaines simulées de PxCorpus, des phrases de stress synthétiques et des contrôles. Les cohortes `p0` (71 fichiers) et `stress` (32) se recouvrent : elles ne doivent pas être additionnées. Les quatre fichiers Corti présents dans l’ancien manifeste sont exclus de cette comparaison de développement.

Les poids Whisper Large-v3 Turbo Q5_0, Silero 6.2, la pause demandée de 576 ms, les WAV et le contexte complet restent identiques. Aucune référence attendue ni liste de corrections n’est fournie au décodeur. L’ordre des profils alterne entre les fichiers ; les appels ASR sont séquentiels, après un préchauffage. Chaque profil conserve son contexte de calcul entre les fichiers ; le contexte textuel est désactivé et le VAD est réinitialisé entre WAV.

| Profil | Différence testée |
| --- | --- |
| `baseline` | whisper.cpp 1.8.5, recherche gloutonne, `best_of=5`, repli en température amont |
| `rng` | Même réglage, avec le [correctif amont 6d0ed914](https://github.com/ggml-org/whisper.cpp/commit/6d0ed914991cac42ace012a05588880801831343) qui réinitialise le générateur aléatoire à chaque appel |
| `beam5` | Correctif RNG et paramètres natifs `BEAM_SEARCH` : cinq faisceaux ; un seul décodeur lors du repli à température positive |

La dernière comparaison porte donc sur **deux profils complets**, pas sur l’effet isolé du nombre de faisceaux. Les trois profils partagent les mêmes bibliothèques GGML locales. Cette construction Mac sert à comparer les réglages ; ce n’est pas le binaire Windows distribué.

## Fidélité mesurée

Sur les 85 fichiers, **`rng` donne exactement les mêmes textes que `baseline`**. Aucun attribut suivi n’est gagné ou perdu. Cela établit l’absence de régression observée sur ce lot, pas l’absence d’erreur médicale.

| Contrôle, lot de stress | Référence | Correctif RNG retenu | Profil `beam5` écarté |
| --- | ---: | ---: | ---: |
| Doses | 22/26 | 22/26 | 22/26 |
| Fractions | 8/8 | 8/8 | 8/8 |
| Négations, contrôle strict | 15/22 | 15/22 | 16/22 |
| Latéralités | 4/4 | 4/4 | 4/4 |
| Quantités | 0/2 | 0/2 | 0/2 |
| Délais | 1/2 | 1/2 | 1/2 |
| Termes rares | 25/66 | 25/66 | 26/66 |

Le total de termes rares masque deux gains et une perte avec `beam5`. Ce profil modifie 41 transcriptions sur 85. Les contrôles de silence et de bruit restent sans texte dans les trois profils, sur quatre fichiers.

Sur les 51 prescriptions humaines, les trois profils donnent les mêmes totaux : **14/51 noms de médicaments exacts**, **49/49 dosages attendus présents** et **11/49 associations médicament–dosage** selon le contrôle renforcé. La présence d’une valeur ne prouve pas son association au bon médicament ni l’absence de nombres supplémentaires. Le contrôle historique de proximité donne 14/49 ; il est conservé séparément et ne doit pas être présenté comme une validation clinique.

Malgré ces totaux identiques, `beam5` **récupère un nom et son association stricte sur un cas, puis perd le nom et l’association sur un autre cas**. Ces deux pertes décrivent le même échec de prescription, pas deux cas indépendants. Le contrôle de quantité administrée passe de 31/49 à 32/49, sans perte détectée ; celui de durée reste à 41/43. Ces gains partiels ne satisfont pas le critère d’absence de nouvelle erreur critique. Le profil n’est pas intégré à l’application.

Les contrôles renforcés repèrent notamment les signes négatifs, concentrations, unités, durées et fractions rattachées au moment de prise. Ils restent des règles automatiques ciblées : les 85 dictées doivent encore faire l’objet d’une revue humaine pour conclure sur la fidélité de leur sens.

## Reproductibilité et temps de calcul

Un contrôle séparé force la température à 0,4, sans augmentation, pour exercer le chemin aléatoire : le même audio `dev-17`, répété trois fois après préchauffage, donne **deux textes distincts avant correction, un seul texte répété après**. Ce contrôle n’utilise pas les réglages du produit et ne démontre pas une amélioration du vocabulaire. Il confirme le mécanisme corrigé ; il ne garantit pas des textes identiques entre processeurs ou bibliothèques différents.

Sur le lot de stress, le P95 **estimé** après la fin de parole, file séquentielle incluse, est de **4,16 s** pour la référence, **4,12 s** pour RNG et **5,00 s** pour `beam5`. Une seule passe par fichier a été effectuée. Des tâches légères de compilation et de vérification ont eu lieu pendant une partie du lot : ces temps sont exploratoires et l’écart de 0,04 s ne permet pas de conclure à une accélération. Il ne s’agit pas d’une mesure entre le microphone et l’écran Windows.

Le [candidat Windows vérifié en CI](https://github.com/sarbhakan/DocTranscript/actions/runs/43629555263), commit `5566eefe4193ea51b9c20b7bffb24b8134a64a4b`, passe le stockage, les migrations, le protocole, le superviseur, les trois contrôles audio chiffrés et le parcours d’interface avec sauvegarde et réouverture. Les [mesures agrégées Windows](windows_consolidation.json) proviennent d’une VM Xeon 6973P-C, deux cœurs / quatre processeurs logiques, 17,17 Go de mémoire. Pour 6,44 s, 16,8 s et 15,2 s de parole, le traitement prend respectivement **14,127 s, 53,074 s et 39,912 s**, démarrage du processus compris. Le maximum échantillonné de mémoire privée parent et moteur est d’environ 1,956 Go. Un échantillon mémoire est partiel sur le troisième cas : ce relevé n’est pas une borne supérieure garantie.

Les valeurs et les trois fractions contrôlées passent, mais le nom **Imovane** manque encore sur `px-23`. Aucun micro physique n’est présent dans cette CI. Ni la vitesse sur un PC de 8 Go ni la précision clinique ne sont validées.

La **Release 0.3.1** a ensuite été reconstruite et validée au commit `8e9693a` dans le [run final](https://github.com/sarbhakan/DocTranscript/actions/runs/43632194234). Les mesures figurent dans `release_validation` du même JSON Windows, en préservant celles du candidat. Sur cette autre VM AMD EPYC 7763, les trois fichiers de parole demandent 16,376 s, 62,163 s et 46,040 s. Les contrôles numériques et le parcours d’interface passent ; Imovane reste absent. Le changement de processeur interdit d’attribuer cet écart de temps à la mise à jour.

## Rejouer le comparatif

Le script [decoder_ab.py](decoder_ab.py) construit les variantes sur macOS à partir des sources exactes de whisper.cpp 1.8.5 et de bibliothèques GGML compatibles déjà présentes. Il nécessite les outils de compilation Apple et NumPy pour la lecture audio. Le [banc historique](asr_benchmark.md) décrit la préparation du manifeste et des WAV ; les chemins ci-dessous sont à remplacer par les emplacements locaux préparés. Utiliser des dossiers de sortie neufs, hors dépôt et hors synchronisation.

```sh
python3 -m p0.decoder_ab build --source /chemin/whisper.cpp-1.8.5 --runtime /chemin/ggml-dylibs --output /chemin/comparatif-build
python3 -m p0.decoder_ab run --build /chemin/comparatif-build --manifest /chemin/cases.json --model /chemin/ggml-large-v3-turbo-q5_0.bin --vad /chemin/ggml-silero-v6.2.0.bin --profiles baseline rng beam5 --cohort development --output /chemin/comparatif-runs
python3 -m p0.decoder_report --manifest /chemin/cases.json --px-archive /chemin/PxCorpus.zip --runs /chemin/comparatif-runs --output /chemin/comparatif-rapport.json
```

Pour le seul contrôle de répétition, utiliser `--profiles forced-baseline forced-rng --cohort development --repeat 3` avec une nouvelle sortie. Le générateur de rapport refuse ces réglages forcés et exige les 85 résultats de chaque profil ; il refuse les identifiants dupliqués et les métadonnées incompatibles.

Les sources et binaires du lot publié sont identifiés par le manifeste de construction dont l’empreinte figure dans le JSON. Après ce lot, le constructeur a été renforcé pour copier et empreinter également les en-têtes du projet et de GGML, et noter le compilateur. Cette nouvelle construction a été exécutée avec succès ; elle n’a pas servi à refaire les 255 transcriptions et n’est pas présentée comme une seconde série de mesures.

Les données de développement ont déjà été examinées. Elles permettent de rejeter une régression et d’étudier un mécanisme, pas d’établir un taux d’erreur généralisable aux cabinets. La prochaine preuve de fidélité doit venir d’un lot inédit, relu par un praticien, avec d’autres voix et textes.
