# Essai de dictée au micro sur Mac

Ce parcours teste une voix réelle, l’affichage et la sauvegarde dans NoteVive. Il ne classe pas les moteurs : pour les comparer, rejouer les mêmes WAV du [banc P0](README.md), avec plusieurs voix. Utiliser une phrase fictive, sans nom, coordonnées ni information de patient.

1. Dans NoteVive, créer une transcription intitulée `Essai micro fictif` et cliquer sur **Dicter**. Si macOS demande l’accès au microphone, le testeur choisit de l’accorder. Rester dans la fenêtre de NoteVive : le passage à une autre application coupe la capture. Attendre **Micro ouvert**. Lire au débit habituel, sans dicter la ponctuation :

   > Pas de douleur à la cheville droite. La gêne concerne la cheville gauche depuis cinq jours.

2. Pendant la lecture, vérifier que le **Texte provisoire** montre des mots avant de cliquer sur **Arrêter**. Noter le délai approximatif entre le début de la parole et le premier mot visible et, séparément, si le premier mot correct a été vu pendant la lecture. Pour chronométrer, utiliser un second observateur ou un appareil séparé. Si personne n’a pu l’observer, noter « non observé ».
3. Après **Arrêter**, attendre que le micro soit coupé, que le **Brouillon à relire** soit rempli et que l’application affiche **Enregistré sur ce Mac**. Noter le délai approximatif du clic à l’apparition du dernier segment. Conserver le brouillon **tel quel** pour la cotation. Pour une comparaison exacte, cliquer sur **Exporter le texte…** et nommer le fichier `avant.txt` dans un dossier local non synchronisé. Si aucun texte n’est produit, relever l’échec de dictée ; une note vide retrouvée ne valide pas la sauvegarde d’une transcription.
4. Quitter avec `⌘Q`, relancer `NoteVive.app` depuis le Finder, puis rouvrir la note dans **Bibliothèque**. Vérifier le titre, la date et l’intégralité du texte. Si le premier export a été fait, exporter de nouveau sous `apres.txt` dans le même dossier, sans éditer le texte.

| Point à vérifier | Attendu dans le brouillon final |
| --- | --- |
| Terme | **douleur**, **cheville**, **gêne**. |
| Négation et côté | La douleur est **absente à droite** ; la gêne est **à gauche**. Retrouver les mots séparément ne suffit pas. |
| Nombre et unité de durée | **Cinq jours** ou **5 jours**, rattachés à la gêne à gauche. |
| Ajouts | Aucun symptôme, côté, durée ou autre détail clinique inventé. |

Noter chaque point comme exact, substitué, omis ou non observable ; relever tout ajout séparément. Les accents, la ponctuation ou l’écriture d’un nombre en lettres sont à distinguer d’un changement de sens. Consigner séparément le déroulement (micro ouvert, provisoire visible, brouillon final, sauvegarde, relance) et la fidélité du texte. Un texte erroné peut être enregistré parfaitement.

Depuis la racine du projet, le score lexical optionnel utilise le même calcul que le banc ; il ne réimprime pas le verbatim et ne classe pas les erreurs cliniques. Sans `--apres`, la sauvegarde est indiquée comme non vérifiée. Avec deux exports, `identique` signifie que les fichiers ont le même contenu non vide ; le titre reste à vérifier à l’écran.

```sh
python3 -m p0.bench.macos_smoke /chemin/local/avant.txt --apres /chemin/local/apres.txt
```

Si ce premier parcours fonctionne, répéter sur le [cas `dev-17`](../corpus/scripts-dev.md), avec `--cas dev-17` et deux nouveaux exports. Vérifier **paresthésie**, le pouce **droit** sans paresthésie, les **quatrième et cinquième doigts** de la main **gauche** pour les fourmillements, et l’incertitude sur le côté du message précédent ([attributs de référence](../corpus/attributs.csv)). Lire le cas en entier, y compris la dernière phrase. Garder les exports et les résultats individuels hors Git.
