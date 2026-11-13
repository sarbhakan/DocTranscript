# Banc P0 : exécution et protocole

Depuis la racine du dépôt, avec Python 3.12, sans installation de bibliothèque pour le banc. Sur Windows, remplacer `python3` par `py -3` ou le chemin de l’interpréteur de l’environnement du projet.

```sh
python3 -m unittest p0.bench.test_bench
python3 p0/corpus/generer_controles.py --wav-dir /tmp/notevive-controles
python3 -m p0.bench --cases /tmp/notevive-controles/cas-controles.csv --wav-dir /tmp/notevive-controles --output /tmp/notevive-smoke --mode accelerated -- python3 -m p0.bench.fake_worker --behavior silent
```

Le simulateur est marqué `simulation_only` dans les résultats. Il ignore le signal audio et vérifie uniquement le protocole et les artefacts du banc. Aucun résultat de ce simulateur ne mesure une reconnaissance vocale. Voir le guide Windows du projet pour préparer le worker et lancer le même banc avec un moteur et des poids locaux.

## Entrées et sorties

- `--cases` : CSV UTF-8 (`id,partition,kind,reference` obligatoires), `--wav-dir` : WAV nommés `<id>.wav`, PCM16 little endian, mono, 16 kHz. Les types pris en charge sont `speech`, `silence` et `noise` ; les deux derniers ont une référence vide. Les identifiants de cas sont limités à 128 caractères ASCII alphanumériques, tirets et underscores, avec premier caractère alphanumérique. Les champs facultatifs `speech_start_ms,speech_end_ms` sont renseignés ensemble, à partir de l’origine WAV, après écoute et annotation. Le banc les exige pour inclure un cas de parole dans les percentiles de latence.
- `--partition dev` est le défaut ; plusieurs options sélectionnent plusieurs partitions dans l’ordre du CSV. `--partition all` sélectionne tout et est réservé à un corpus sans jeu confidentiel. En confirmation, employer un CSV indépendant et un dossier de sortie local séparé.
- `--mode realtime` envoie le bloc quand son dernier échantillon aurait été capturé. `--mode accelerated` envoie les blocs sans cadence et calcule le facteur temps réel du worker, protocoles et acheminement compris ; le temps de chargement du modèle est mesuré à part. Garder `--chunk-ms` constant pour comparer ; défaut 20 ms.
- `--warmup` vaut 1 par défaut. Le premier cas de parole de `dev` peut être rejoué sans être compté une deuxième fois dans les scores. Pour une partition de confirmation seule, fournir explicitement `--warmup-wav` avec un WAV distinct issu du développement, ou mettre `--warmup 0` pour un essai sans préchauffage. Sans ce WAV ni cas dev, aucun échauffement n’est fait. Un WAV d’échauffement identique à un WAV sélectionné hors dev est refusé. Éviter de mélanger dev et confirm pour décider d’un moteur.
- `--startup-timeout-s` vaut 30 par défaut pour atteindre `ready`. `--timeout-s` vaut 30 ; c’est un budget total par cas en accéléré, et un budget en plus de la durée audio nominale en temps réel. Augmenter ces délais avant le test gelé si nécessaire. Un échec de worker arrête le lot et inscrit les cas restants comme non exécutés.
- `--output` doit désigner un dossier vide ou à créer. Le banc écrit `manifest.json` (paramètres, métadonnées moteur, SHA-256 des WAV et du CSV), `results.json`, `cases.csv` et `trace.ndjson` (événements horodatés sans texte). `--include-text` ajoute `transcripts.ndjson` (`id,status,text` ; texte final observé ou null) pour l’analyse locale. Si le worker émet `final` puis échoue, le texte reste observable dans cet artefact optionnel, mais le cas compte comme échoué. Les références restent dans le CSV source. Les arguments bruts de la commande et le stderr du worker ne sont pas sauvegardés.
- Code retour 0 si le protocole a abouti, 1 en cas de panne du worker ou de son protocole, 2 si les entrées ou la configuration du banc sont invalides. Un score insuffisant n’est pas une panne du banc.

## Mesures et limites

En temps réel, le banc horodate chaque ligne complète reçue sur stdout avec un compteur monotone. Il mesure **le worker**, sans micro, capture Windows, écran ni logiciel métier. Un mot est compté comme premier mot correct si le premier mot de référence est en tête d’une hypothèse normalisée, y compris le final. La métrique complémentaire `first_correct_before_speech_end` indique si ce mot est arrivé pendant la prise de parole. Le premier texte non vide, les révisions du provisoire et le retard d’envoi des blocs sont rapportés séparément.

L’événement `final` correspond à l’ensemble du cas et suit `end`. Le délai fin de parole → final inclut le silence restant à la fin du WAV. Le délai requête `end` → final est également consigné. Ce protocole ne mesure pas l’endpointing automatique pendant la dictée. Pour l’acceptation, ajouter une mesure jusqu’à l’affichage avec le client Windows.

Les percentiles sont au rang supérieur : trier puis prendre le rang `ceil(0,95 × n)`, à partir de 1. Un cas annoté sans résultat utilisable est placé en fin de série comme latence infinie ; le rapport l’encode en JSON `null` si le percentile l’atteint, avec `failed_percentile`. Le nombre d’échecs est toujours indiqué. `not_applicable` signifie qu’aucun cas n’était éligible, par exemple si le run accéléré ne mesure pas une latence liée à la parole. Les cas non annotés n’entrent pas dans les percentiles de parole.

Le WER est `somme des insertions, substitutions et suppressions / somme des mots attendus`. Le tokenizeur harmonise casse, apostrophes et séparateur décimal ; il garde accents et valeurs, sépare les ponctuations et ne convertit pas des nombres écrits en lettres. Toute dictée échouée ou non exécutée compte comme une hypothèse vide. Les contrôles sans parole sont séparés du WER ; toute hypothèse non vide, même provisoire, y est comptée. Ce comptage est conservateur et ne constitue pas la cotation des erreurs critiques, qui exige une revue distincte.

## Protocole NDJSON v1

Un processus persistant par exécution, sans shell. Les messages UTF-8 sont chacun sur une ligne terminée par LF (CRLF accepté en sortie). Le worker doit écrire et vider le tampon après chaque événement. Stdout est réservé au protocole ; aucun texte libre ou journal natif. L’ordre des cas est séquentiel, y compris l’échauffement, et les messages ne portent que sur le cas actif.

| Direction | Événement | Champs |
| --- | --- | --- |
| Worker → banc | `ready` | `protocol: 1`, `engine` identifiant ASCII, `simulated` booléen, `details` objet optionnel contenant les versions, paramètres et empreintes techniques. Ne pas placer de chemins, secrets ou transcriptions dans `details`. |
| Banc → worker | `start` | `id`, `sample_rate:16000`, `channels:1`, `sample_format:"pcm_s16le"` |
| Banc → worker | `audio` | `id`, `seq` à partir de 0, `pcm_b64` échantillons bruts, blocs non vides |
| Banc → worker | `end` | `id`, aucun bloc suivant pour le cas |
| Worker → banc | `partial` | `id`, `text` hypothèse cumulative complète, zéro ou plusieurs fois |
| Worker → banc | `final` | `id`, `text` transcription cumulative complète, éventuellement vide, exactement une fois après `end` |
| Worker → banc | `done` | `id`, exactement une fois, après `final` |
| Worker → banc | `error` | `id` sauf au démarrage ; `code` identifiant technique ASCII sans contenu ni détails personnels ; termine le lot |

La fermeture de stdin termine le worker. Une ligne de réponse est limitée à 1 MiB et un texte à 32 768 caractères. Tout processus enfant du worker doit être borné et nettoyé par le worker ; le banc tue le processus qu’il a lancé en cas d’échec. Le banc n’intercepte pas le réseau : le caractère hors ligne du worker et de ses dépendances doit être contrôlé indépendamment.
