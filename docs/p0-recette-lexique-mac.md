# NoteVive 0.2.1 · Lexiques de spécialité sur Mac

NoteVive contient **14 profils consultables hors ligne**, de **6 222 à 10 000 entrées chacun**. Le même modèle UltiMed INT8 sert à toutes les spécialités ; Silero continue à découper la dictée aux pauses. Ce travail ne modifie pas les poids du modèle et ne nécessite aucun nouvel accès au réseau.

Une entrée peut figurer dans plusieurs profils. Les 14 profils contiennent ensemble **41 178 libellés distincts** après rapprochement des variantes de graphie. Le [détail par spécialité](../lexique/PROFILS.md) sépare le vocabulaire directement rattaché, les domaines voisins et le socle commun. Le contenu inclut des maladies, synonymes, signes, médicaments et, selon le profil, des gestes, analyses et dispositifs. L’édition Medic’AM retenue couvre les produits remboursés délivrés en officine ; le catalogue ne couvre donc pas exhaustivement les médicaments hospitaliers. Voir [les attributions et éditions](../lexique/NOTICE-profils.md). Aucun extrait de la BDPM n’est intégré à ce paquet.

Dans l’application, **Consulter le lexique…** permet de rechercher sur l’ensemble du profil. La liste prioritaire est préparée indépendamment des transcriptions de test. Elle reste volontairement plus courte que le catalogue ; jusqu’à 24 favoris du profil choisi peuvent être proposés en priorité lors de la dictée suivante. La préférence « Sans aide lexicale » reste le point de départ. Une alternative du décodeur n’est acceptée que si la modification correspond à un terme complet du profil et si le texte en dehors de ce terme reste identique. Les valeurs et marqueurs critiques sont exclus des termes proposés. Ces garde-fous ne corrigent pas les erreurs du moteur de référence.

## Protocole

Le banc rejoue les mêmes WAV, sur la même application signée et le même Mac, avec le même modèle chargé et des ordres alternés. Les 32 fichiers incluent les 10 dictées longues de l’essai précédent lues par une voix synthétique française, 7 extraits publics PxCorpus en voix humaine, des cas de français courant et 4 contrôles sans parole. Le test contient 66 occurrences de termes et 64 passages critiques annotés, dont 26 sur les valeurs ou unités, 22 sur la négation et 8 sur les fractions. Les répétitions servent aux temps ; elles n’augmentent pas le nombre de voix ni d’occurrences.

- **Sans aide** : décodage de référence.
- **Priorités** : liste fixe du profil associé à la spécialité de la note.
- **Catalogue admissible** : exploration avec tous les termes du profil passant les filtres du moteur, sans injecter chiffres, unités, fractions ou négations comme indices.

Les temps de calcul sont relevés dans la chaîne de dictée sur les segments Silero. Le délai après la parole est estimé à partir des pauses artificielles et du temps de décodage. Il ne mesure pas la capture réelle ni l’affichage de l’interface. Les mots et les attributs sont vérifiés sur l’audio de référence ; les formes équivalentes comme « 25 µg » et « vingt-cinq microgrammes » sont admises pour les valeurs.

Pour reproduire l’essai et consulter les résultats : suivre [la procédure et les mesures A/B](../p0/lexicon_macos.md). Les références, enregistrements et sorties de PxCorpus restent locaux. Aucun cas n’est utilisé pour promouvoir un terme dans le profil.
