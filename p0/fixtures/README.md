# Extraits de parole pour les tests Windows

Ces enregistrements sont des prescriptions simulées pour des exercices de reconnaissance vocale, sans lien avec un patient. Les valeurs sont des références de test, sans valeur de consigne de traitement. [Le protocole de collecte](https://arxiv.org/html/2311.03510v1#S5.SS2) décrit les exemples proposés aux participants.

| Fichier | Durée | Contrôle attendu | Ligne source dans `PxSLU/paths.txt`, index de départ 0 |
| --- | ---: | --- | ---: |
| `px-826.wav.gz` | 6,44 s | Médicament simulé « Prozac 20 mg ». Métadonnées historiques : [`fixture.json`](fixture.json). | 826 |
| `px-23.wav.gz` | 16,80 s | « Imovane », `7,5 mg`, un quart de comprimé. | 23 |
| `px-584.wav.gz` | 15,20 s | « Sotalex », `80 mg`, deux mentions distinctes : un demi le matin et un demi le soir. | 584 |

Les extraits sont tirés de [PxCorpus v4, jeu PxSLU](https://doi.org/10.5281/zenodo.10080490), par Ali Can Kocabiyikoglu, François Portet, Prudence Gibert, Hervé Blanchon, Jean-Marc Babouchkine et Gaëtan Gavazzi, sous licence [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/). [`regressions.json`](regressions.json) fixe pour les deux extraits longs les fichiers source, le texte de référence et les annotations du banc, ainsi que les empreintes de l’archive, de l’enregistrement original, du WAV canonique, du signal PCM et du gzip.

Chaque en-tête WAV source indique un alignement de trame de 4 octets. La seule modification du WAV consiste à fixer ce champ à 2 octets (offset 32, entier non signé sur 16 bits en ordre petit-boutiste) pour le PCM mono sur 16 bits à 16 kHz. Le signal est identique octet par octet à la source. Les fichiers sont compressés en gzip au niveau 9 avec un horodatage nul (`mtime=0`) et sans nom de fichier stocké dans l’en-tête. Le WAV décompressé doit rester identique aux empreintes publiées ; l’empreinte du gzip identifie séparément le fichier versionné.

Ces trois extraits sont réservés aux tests et ne sont pas distribués dans le paquet Windows. Ils vérifient des régressions connues sur les mêmes fichiers, dont les trois fractions que le candidat avait reconnues sur Mac. Ils ne qualifient ni la fidélité médicale ni les performances sur un PC à 8 Go. Les autres enregistrements des corpus complets restent locaux.
