# NoteVive Mac : comparaison appariée du lexique

Le test rejoue strictement les mêmes octets dans une seule application Mac signée, avec les mêmes poids UltiMed INT8, la même détection de pause Silero et le même traitement audio. Aucun réseau, micro, ni dossier de notes n’est nécessaire. Les références et annotations restent dans le processus du banc. Seuls l’identifiant de la spécialité et le WAV sont transmis à NoteVive.

1. Préparer le [lot P0](../docs/p0-choix-moteur.md#rejouer-et-qualifier) à partir de l’archive PxCorpus v4 épinglée, avec `--with-mac-synth`. Le rejeu Mac a besoin du lot existant et de la voix Jacques pour les nouvelles dictées.
2. Préparer le lot de 32 cas et l’exécuter avec le binaire signé sur Mac (sans superposer un autre bac à sable à celui de l’application) :

```sh
python3 -m p0.lexicon_ab prepare --p0-lot /chemin/lot-p0 --output /chemin/lot-lexique
python3 -m p0.lexicon_ab run \
  --binary /chemin/NoteVive.app/Contents/MacOS/NoteVive \
  --cases /chemin/lot-lexique --output /chemin/lexique.ndjson --repeats 3 --include-full
python3 -m p0.lexicon_ab score \
  --cases /chemin/lot-lexique --results /chemin/lexique.ndjson \
  --profiles /chemin/profiles.json --output /chemin/lexique-mesures.json
```

Les options comparent le décodeur de référence sans lexique, le profil avec liste prioritaire et, avec `--include-full`, la totalité des candidats admissibles du profil. Ce troisième bras est un test exploratoire et n’est pas un réglage livré. Les entrées affichées dans le catalogue, les termes admissibles et ceux effectivement encodés peuvent avoir des effectifs différents. Les essais de vitesse gardent le modèle chargé, préchauffent chaque profil et alternent l’ordre de passage. Ne pas les exécuter en concurrence avec un autre banc lourd. Les répétitions servent à la vitesse : elles n’ajoutent ni locuteur ni cas de fidélité.

Les 32 WAV couvrent 11 des 14 profils. Ils comprennent dix longues dictées fictives proposées pour tester NoteVive, sept prises humaines de [PxCorpus/PxSLU v4](https://zenodo.org/records/10080490), cinq autres notes médicales synthétiques, six notes ou leurres en français courant et quatre contrôles sans parole. Les 66 mentions lexicales et les 64 attributs critiques sont annotés avant rejeu. Les fins de parole sont estimées sur les phrases synthétiques séparées par une seconde de silence. Le délai indiqué est l’écart jusqu’au paquet audio émis par le détecteur, plus le temps de décodage du segment : il ne comprend ni le micro, ni l’affichage. Le temps de construction du contexte est publié séparément.

Le score lexical admet des graphies explicitement annotées ; les contrôles de dose acceptent des notations strictement équivalentes telles que « quatre cents milligrammes » et « 400 mg ». Une occurrence ne peut valider deux mentions identiques. Les écarts avec référence d’un terme présent dans le profil sont des signalements pour relecture ; ils ne démontrent pas à eux seuls un mot inventé par le décodeur. Les changements entre les deux bras doivent être relus pour vérifier aussi les ajouts, la portée des négations et l’association d’une dose au bon médicament. Ce petit lot mesure un effet technique. Il ne valide ni la précision clinique, ni les performances Windows, ni chaque spécialité ou terme du catalogue. Les WAV et les transcriptions brutes restent locaux.

## Mesures du 14 novembre 2026

NoteVive 0.2.1, Apple M1 Pro, 16 Gio, macOS 27.2, CPU. Trois répétitions de 32 WAV dans chacun des trois bras : 288 passages en tout, 213 segments et 96 pauses synthétiques mesurées par bras. Le catalogue du paquet final testé a pour SHA-256 `8929b965a9053972832c89ae1a13908525e251758ec9b0fda3d4ac95bb4cf18c`. Les WAV de ce passage sont identifiés par le manifeste `92eacbfa49c1e5f20495df25c65eeb418d217b1f66643c2db91e9d8480ecdb19` et leurs empreintes individuelles.

| Mesure | Sans lexique | Liste prioritaire | Catalogue complet admissible |
| --- | ---: | ---: | ---: |
| Termes pris en compte par profil testé | 0 | 107–205 | 5 332–9 250 |
| Mentions lexicales correctes | 25/66 | 25/66 | 25/66 |
| Attributs critiques correctement rendus | 46/64 | 46/64 | 46/64 |
| Contrôles sans parole produisant du texte | 0/4 | 0/4 | 0/4 |
| Décodage par segment, P95 | 366 ms | 372 ms | 371 ms |
| Fin de parole → texte, estimation P95 | 1 150 ms | 1 146 ms | 1 151 ms |
| Préparation du contexte, P95, modèle chaud | 2,7 ms | 2,5 ms | 58,8 ms |

Les segments, leurs positions dans l’audio et les textes étaient identiques dans les trois bras et les trois répétitions. Ils n’ont pas changé après la correction de la classification des signes absents dans le catalogue. La transcription sans lexique est identique à celle de NoteVive 0.2.0 sur les mêmes 32 fichiers. Aucun terme ajouté ni dégradation de fidélité n’a été observé, mais aucun gain n’a été démontré non plus. Le lexique prioritaire contenait 4 des 66 mentions cibles avant filtrage par le décodeur ; les catalogues complets en contenaient 23, dont 14 manquées dans les trois bras. La fidélité absolue reste insuffisante : 14/26 contrôles de dose ou unité, 20/22 de négation, 7/8 de fraction, 4/4 de latéralité, 1/2 de délai et 0/2 de quantité ont réussi. Des erreurs préexistantes, telles que « 400 mg » rendu « quatre milligrammes » et « 0,3 mL » rendu « 0,3 millimètre », persistent dans les trois bras.
