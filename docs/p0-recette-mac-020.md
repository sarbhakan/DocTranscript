# NoteVive 0.2.0 · Recette Mac du 14 novembre 2026

**Prêt pour les essais fictifs sur ce Mac, échec du contrôle de fidélité clinique.** La chaîne native regroupe la parole avec Silero 6.2 et transcrit chaque passage avec UltiMed INT8 sur CPU. Elle transmet le dernier passage à l’arrêt. Le prétraitement utilise le graphe ONNX officiel épinglé ; les sorties peuvent différer du banc Python qui transcrivait les fichiers entiers. Aucun correcteur numérique ne modifie le brouillon.

## Contrôles du paquet signé

- Mac Apple M1 Pro, 16 Gio, macOS 27.2. Signature locale stricte vérifiée sur la `.app`, après extraction du ZIP et après installation. Le ZIP inclut les modèles, le runtime et leurs licences ; il ne contient aucun WAV de test. Le système refuse les opérations réseau entrantes et sortantes au processus qui a transcrit la dictée fictive avec « un demi » et « un quart ».
- Le même audio fictif a été rejoué à 16, 44,1 et 48 kHz : deux passages obtenus avant la fin de l’audio et le troisième à l’arrêt, avec le même texte aux trois fréquences. Les quatre WAV de silence ou de bruit n’ont donné aucun texte. Un WAV invalide est refusé avec une erreur lisible.
- Trois contrôles de rappel Core Audio sans micro physique et cinq tests de bibliothèque ont réussi. La fenêtre ouverte depuis le Finder mesurait 995 × 647 points et la note de la version précédente était toujours accessible. L’expérience complète au micro de ce paquet reste à vérifier avec un utilisateur.

| Contrôle | Résultat observé dans la `.app` |
| --- | --- |
| Dose décimale et fréquence (`dev-04`) | « 7,5 milligrammes », « une fois par semaine » et « n’est pas confirmée » conservés. Le nom du médicament comporte une faute. |
| Deux doses proches (`dev-05`) | « 25 microgrammes » et « 50 microgrammes » conservés dans leurs phrases respectives. |
| Volume et négations (`dev-06`) | Les deux négations sont conservées. « 0,3 millilitres » devient « 0,3 millimètres ». |
| Négation, latéralité et correction (`dev-08`, `dev-09`, `dev-17`) | Les négations ciblées et gauche/droite sont conservés. Le passage de « 15 jours » à « 5 jours » reste explicite. |
| Demi et quart (dictée synthétique) | « Un demi comprimé » à la pause, « un quart de comprimé » à l’arrêt. |
| Quart en voix humaine (`px-23`) | « 7,5 milligrammes » et « un quart de comprimé » conservés. |
| Deux demis en voix humaine (`px-584`) | Premier « un demi » rendu « à demi » ; second « un demi » conservé. |
| Forces commerciales (`px-212`, `px-1331`) | « 400 mg » devient « quatre milligrammes » et « 0,13 % » devient « 0,3 % ». |
| Quantité et heure (`px-634`) | « Deux bouffées » est déformé et « sept heures trente » est incomplet. |

Les identifiants renvoient au [lot comparatif P0](p0-choix-moteur.md). Les lignes ci-dessus décrivent des cas contrôlés, sans prétendre mesurer le taux d’erreur sur toutes les négations ou fractions. En complément, le rejeu via les deux composants natifs a donné du texte pour les 67 fichiers parlés (95 segments) et aucune sortie pour les quatre témoins sans parole. Le décodage d’un segment prenait 163 ms en médiane et 308 ms au 95e percentile, hors délai de pause, capture, interface et sauvegarde. Ce rejeu natif a reconnu 47 des 49 forces commerciales évaluées et 26 des 51 noms de médicaments à l’identique. Ces scores ne couvrent pas toutes les quantités administrées ni leur association au médicament.

Pour reproduire les cas, préparer le lot P0 avec `--with-mac-synth` pour les dictées fictives, puis utiliser [les commandes du guide Mac](../app/macos/README.md#rejouer-les-contrôles) avec les WAV nommés par identifiant. Pour l’essai au micro, dicter deux phrases fictives avec une pause d’une seconde, vérifier le premier résultat avant de cliquer sur **Arrêter**, puis relire et rouvrir la note. Toute dose, unité, fraction ou négation modifiée compte comme un échec, même si le reste du texte est fidèle.
