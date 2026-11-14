# Extrait de parole pour le test Windows

`px-826.wav.gz` contient 6,44 secondes de parole française. Le texte de référence est « prozac 20 milligrammes 1 gélule matin et soir ». C’est une prescription simulée pour un exercice de reconnaissance vocale, sans lien avec un patient, et ne constitue pas une consigne de traitement. [Le protocole de collecte](https://arxiv.org/html/2311.03510v1#S5.SS2) détaille les exemples proposés aux participants.

L’extrait est tiré de [PxCorpus v4, jeu PxSLU](https://doi.org/10.5281/zenodo.10080490), par Ali Can Kocabiyikoglu, François Portet, Prudence Gibert, Hervé Blanchon, Jean-Marc Babouchkine et Gaëtan Gavazzi, sous licence [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/). Il correspond à la ligne 826 de `PxSLU/paths.txt` en comptant depuis zéro et au fichier `PxCorpus/PxSLU/recordings/jYV4F135rb/recording_4.wav`.

L’en-tête WAV source indique un alignement de trame de 4 octets. Il est corrigé à 2 à l’octet 32 pour une trame PCM mono sur 16 bits. Les 103 040 trames à 16 kHz sont identiques à la source. Le fichier est compressé en gzip sans nom d’origine ni horodatage ; [`fixture.json`](fixture.json) fixe les empreintes du WAV, du signal PCM et du fichier compressé.

Cet extrait est la seule exception dans ce répertoire à la conservation locale des enregistrements des corpus complets. Il est réservé aux tests, absent du paquet Windows et ne qualifie ni la fidélité médicale ni les performances sur un PC à 8 Go.
