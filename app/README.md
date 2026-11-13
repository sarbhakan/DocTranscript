# NoteVive · premier exécutable Windows

Le paquet d’essai vise un usage simple sur Windows 11 x64 : extraire le dossier et ouvrir `NoteVive.exe`, puis cliquer sur **Dicter**. Le microphone est celui sélectionné par défaut dans Windows. Le texte en cours apparaît dans une zone séparée ; les segments terminés rejoignent la note éditable. **Arrêter** coupe la capture et termine le texte reçu. Le titre et le brouillon sont sauvegardés automatiquement et retrouvables à la réouverture. Le bouton **Vocabulaire** permet de consulter les libellés et leur provenance. Il ne corrige pas la note et n’oriente pas le moteur.

Le paquet inclut l’unique modèle de ce prototype, ses bibliothèques CPU et le catalogue de référence. Aucun compte, Python, .NET ou téléchargement n’est nécessaire côté utilisateur. C’est une archive portable : garder `runtime` à côté de l’EXE. L’exécutable n’est pas signé ; ce paquet sert à la recette sur exemples fictifs. Dans cet essai, le texte reste dans NoteVive ; les champs de notes n’écrivent pas dans le presse-papiers Windows. Voir le [guide d’essai Windows](../docs/guide-essai-windows.md) pour le lancement et le dépannage.

## Choix techniques et portée

- **Win32 natif / C++17**, construit pour x64 avec [Zig 0.15.2](https://ziglang.org/download/). WPF reste une option d’architecture ; l’essai choisit Win32 pour produire et inspecter un EXE autonome depuis macOS sans dépendre d’un framework d’interface installé sur Windows. Contrôler l’accessibilité, le clavier et le changement d’échelle sur poste avant de figer ce choix.
- **Capture WinMM** et micro par défaut, en PCM mono à 16 kHz. Le fil de capture est distinct du décodage. Une file pleine, un périphérique indisponible ou un arrêt non confirmé sont signalés. WASAPI reste une option si la recette sur les microphones du parc révèle des limites. Les notes restent internes à NoteVive ; F9 fonctionne lorsque l’application est active.
- **Sherpa-ONNX v2.0.1 et Zipformer français** : un transducteur en flux, deux fils de calcul CPU, encodeur et joint quantifiés, décodeur non quantifié. Ce choix produit un candidat testable ; P0 doit encore déterminer quelle configuration passe les critères de latence et de fidélité sur deux postes. Les majuscules, la ponctuation, les acronymes et les termes médicaux reflètent les capacités du modèle livré. Aucun biais lexical ni adaptation des poids n’est activé.
- **Notes chiffrées avec DPAPI**, liées au compte Windows courant, sous `%LOCALAPPDATA%\NoteVive-Pilote\notes`. Aucun audio n’est sauvegardé par l’application. Le catalogue SQLite 3.54.1 est séparé, lu en lecture seule et vérifié avant ouverture. Les notes chiffrées ne constituent pas une sauvegarde transportable vers un autre poste ; la restauration et la gestion du poste restent à qualifier.

Les versions, sources et empreintes de construction sont dans [inputs.lock.json](inputs.lock.json). Le paquet transporte les attributions, licences et empreintes de ses fichiers. Les archives téléchargées, les catalogues générés et les EXE ne font pas partie du code source publié. Les empreintes contrôlent l’identité des fichiers ; elles ne remplacent pas la signature de l’installateur à venir.

## Refaire la compilation

1. Sur un poste de préparation, télécharger la distribution officielle Zig 0.15.2 correspondant à l’hôte et comparer son SHA-256 à `zig` dans le verrou. L’extraire localement ; pas d’installation système requise.
2. Enregistrer chaque URL `downloads` du verrou sous le nom indiqué dans `app/private/downloads/`. Le script vérifie l’ensemble des empreintes. Reconstituer le [catalogue lexical](../lexique/README.md) ; cet EXE épingle les octets du catalogue testé. Si SQLite produit un fichier différent sur un autre hôte, utiliser l’instantané revu ou requalifier le nouvel instantané et mettre à jour les empreintes de construction et d’exécution ensemble.
3. Depuis la racine du projet, avec Python 3.12 **sur la machine de construction seulement** :

```text
python app/build_windows.py --zig CHEMIN_VERS_ZIG
```

Le script n’utilise pas le réseau. Il construit le binaire, ajoute le manifeste Windows et l’icône, puis génère `dist/NoteVive-Windows-x64-Essai.zip` et un fichier `.sha256`. Une sortie déjà présente n’est pas écrasée.

## Vérifier sur les deux PC

1. Sur W1 (8 Go, sans carte graphique dédiée) et W2, vérifier le SHA-256 du ZIP, extraire localement, couper le réseau et lancer le même paquet. Vérifier qu’il démarre sans installation et que le micro reste fermé jusqu’au clic. Refaire ensuite la [recette hors ligne](../docs/p0-windows.md#5-vérifier-le-hors-ligne-et-contre-vérifier) dans les conditions approuvées pour surveiller les tentatives réseau.
2. Lire « Pas de douleur de la cheville droite. La gêne concerne la cheville gauche depuis cinq jours. » Vérifier l’apparition du provisoire pendant la parole, puis le résultat après **Arrêter**. Noter à part toute perte de « pas », permutation de côté ou valeur erronée. Refaire avec un silence, puis avec le navigateur et un document fictif ouverts. Pour les mesures reproductibles, utiliser les mêmes WAV et la [procédure P0](../docs/p0-windows.md).
3. Pendant une deuxième dictée, corriger un passage stable. Vérifier que la correction et le curseur restent intacts. Interrompre par minimisation, débranchement du micro, verrouillage puis veille : le micro doit s’arrêter, la capture ne reprend jamais seule et le brouillon doit rester disponible. Contrôler que le texte est bien affiché et que la boîte Vocabulaire trouve `hémoglobine` avec une source, puis fermer et rouvrir NoteVive pour retrouver la note.
4. Vérifier l’échec lisible d’une copie du paquet avec un fichier modèle absent ou altéré. Ne pas modifier la copie de référence. Pour isoler les défauts, les sources incluent `engine_smoke.cpp` (WAV PCM16 mono 16 kHz, modes `--speech` et `--silence`) et `notes_test.cpp` (DPAPI, écriture, conflits et corruption). Ils sont compilés à part et ne sont pas nécessaires à l’utilisation.

Les résultats de compilation et d’inspection PE ne valent pas validation du micro, des notes ou de la réactivité sous Windows. Une livraison stable demande la recette sur ces postes, des essais praticiens avec notes fictives et la signature de l’artefact de diffusion.
