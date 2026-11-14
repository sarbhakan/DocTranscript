# Recette Windows de NoteVive 0.3.0

Effectuer cette recette avec **un seul ZIP Windows x64**, identique sur les deux postes. Le candidat 0.3.0, non publié, est réservé aux données fictives. Tant que les mesures ci-dessous ne sont pas remplies sur les deux PC, le fonctionnement et le confort sur un poste à 8 Go ne sont pas établis. La construction sous Windows, les tests hors interface et les comparaisons sur Mac ne remplacent pas cette recette. Aucun résultat de ce document ne vaut qualification clinique.

## Préparer les deux postes

1. **W1 :** Windows 11 x64, 8 Go de RAM, sans GPU dédié, sur un PC physique représentatif du plancher visé. **W2 :** autre PC physique Windows 11 x64, avec son matériel consigné. La dictée requiert sur les deux postes AVX/AVX2 utilisables sous Windows, FMA, F16C, BMI1, BMI2, LZCNT, SSE4.2 et POPCNT. Le moteur utilise le processeur même si W2 a un GPU. Noter la version exacte de Windows, le CPU, la RAM, le stockage, le micro et le profil d’alimentation. Tester sur secteur à conditions de bruit et distance au micro comparables. Suivre le [banc Windows P0](p0-windows.md) pour relever les ressources sans données sensibles.
2. Utiliser des comptes Windows de test. Préparer un dossier local sur disque fixe pour l’application et un dossier séparé pour les résultats. Télécharger le ZIP sur le poste de préparation, puis vérifier son empreinte avec `Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\Chemin\NoteVive-Windows-x64-Essai.zip'` et la comparer au fichier SHA-256 de la même release. Décompresser le ZIP en entier, y compris `runtime` et `Licences`. Garder une copie intacte. Ne pas déplacer le dossier de bibliothèque de l’utilisateur courant.
3. Couper Wi‑Fi et Ethernet avant le premier lancement. Vérifier que NoteVive démarre avec son modèle et son catalogue présents, sans installateur ni téléchargement. Tester les deux postes avec la même archive et les réglages livrés. Noter le SHA-256, le runtime, le détecteur et le réglage de pause dans le relevé. Le moteur est whisper.cpp 1.8.5 avec Whisper Large v3 Turbo Q5_0 et Silero VAD GGML 6.2.0, pause réglée à **576 ms** ; aucun profil lexical n’est injecté dans le décodeur Windows. L’ancien Zipformer a été évalué comme référence et écarté de ce paquet ; voir le [choix du moteur](p0-choix-moteur.md).
4. Dans NoteVive, lancer une dictée avec F9, attendre « Micro ouvert », puis vérifier l’entrée audio. Faire les tests de latence et de qualité en deux séries distinctes : pas de correction ou d’édition de la note pendant la collecte. Pour les essais avec pannes, n’ouvrir aucun document réel ; utiliser seulement le compte et la copie réservés à la recette.

## Lire les mêmes exemples fictifs

Les valeurs suivantes sont **du texte d’épreuve**, sans indication de traitement. Lire à débit naturel ; une barre verticale marque une pause prévue et ne se prononce pas. Utiliser le même locuteur pour la comparaison directe W1/W2, puis au moins un second locuteur pour tester la sensibilité à la voix. Conserver chaque sortie originale avant correction pour la relecture locale.

| Cas | Phrase à lire | Attributs à relever |
| --- | --- | --- |
| W030-01 | « Pas de douleur à la cheville droite. » `│` « La gêne concerne la cheville gauche depuis cinq jours. » | Négation, deux latéralités et durée. |
| W030-02 | « Épreuve fictive : zéro virgule cinq milligramme, et non cinq milligrammes. » | `0,5 mg`, valeur contrastive `5 mg`, relation « et non ». |
| W030-03 | « Cette ligne d’essai contient trois quarts de comprimé, puis un demi-comprimé sur la ligne suivante. » | `3/4` et `1/2` attachés à la bonne proposition. |
| W030-04 | « Le scénario indique zéro virgule trois millilitre de solution à zéro virgule un pour cent. » | `0,3 mL` et `0,1 %` ; surveiller la confusion `mL` / `mm`. |
| W030-05 | « Discussion paraclinique : électroneuromyographie, anticorps anti-MuSK et myasthénie. Aucun argument pour un syndrome de Lambert-Eaton. » | Trois termes techniques, syndrome et portée d’« aucun ». |
| W030-06 | « Hypothèses fictives : maladie de Vaquez, thrombocytémie essentielle et mutation JAK2. » `│` « Dans cet exemple, le mot hydroxycarbamide est dicté une fois. » | Maladies, sigle et substance ; aucun ajout de médicament. |
| W030-07 | « À l’OCT, drusen maculaires à droite et absence d’œdème maculaire à gauche. L’aflibercept est cité comme terme de test. » | Côtés, négation, examen, terme rare et produit. |
| W030-08 | « La tobramycine apparaît au lexique fictif. » `│` « Le texte ne décrit aucune exacerbation de bronchectasies. » | Substance, terme rare et double marque de négation sans renversement de sens. |
| W030-09 | « Un milligramme » — à voix basse et seul, puis garder le silence. | Parole brève et faible : compter l’omission éventuelle, sans lui substituer une phrase entière inventée. |
| W030-10 | Rester silencieux 10 s, puis refaire séparément avec des bruits de clavier sans parole. | Aucun texte ajouté à la note dans les deux essais ; arrêt fonctionnel. |

Accepter des graphies équivalentes, par exemple `demi` et `½` ; une unité différente, une valeur déplacée, une négation perdue, une latéralité échangée ou une information critique inventée sont des erreurs de sens. Noter chaque ajout et omission séparément, ainsi que chaque mot rare correct. Ce petit lot permet de repérer des défauts ; pour une qualification, les [seuils du projet](feuille-de-route.md#critères-mesurables-proposés) demandent un lot inédit et relu indépendamment, avec au moins 200 attributs critiques.

## Chronométrer et mettre en charge

1. **Démarrage.** Au premier lancement après un redémarrage du poste, mesurer l’ouverture de la fenêtre et le délai du premier clic « Dicter » jusqu’à « Micro ouvert ». Faire trois démarrages à froid de processus par poste, dont un après redémarrage si possible. Mesurer séparément trois démarrages à chaud. Un processus neuf n’implique pas un cache disque froid.
2. **Affichage à la pause.** Mesurer au moins 20 pauses parlées par poste, moteur chaud, avec les cas W030-01 à 08 répétés. Après chaque phrase, conserver assez de silence pour laisser apparaître le texte. Filmer localement, par exemple avec une caméra à 60 images/s qui voit l’écran et enregistre la voix du testeur. Vérifier d’abord le décalage audio/vidéo sur un claquement visible et audible ; noter l’incertitude. Sans mesure alignée, marquer « estimation » et ne pas utiliser le résultat pour valider le seuil. Annoter début de parole, fin effective du dernier mot, premier affichage correct du premier mot et premier affichage de tout le segment confirmé, puis calculer leurs écarts. Un texte incorrect ou qui n’arrive pas est un échec, jamais une mesure de zéro. Faire une série distincte à débit continu et à pauses de 0,5 s / 1 s / 1,5 s ; relever fusions, répétitions, phrases perdues et accumulation.
3. **Bouton Arrêter.** Pour chaque poste, trois fois après une courte phrase et trois fois après une tirade, cliquer juste après le dernier mot. Mesurer séparément clic → micro fermé et clic → dernier segment affiché / état terminal. Vérifier le dernier mot en prononçant une valeur ou une négation dans les derniers instants. Ne pas mélanger ce chronomètre avec celui démarrant en fin de parole.
4. **Endurance et ressources.** Faire sur chaque poste trois dictées de 15 min avec des pauses naturelles, dont au moins une pendant l’utilisation locale d’un navigateur et d’un logiciel métier simulé. Scander des repères vocaux différents (« repère alpha », « repère bravo », etc.) toutes les 30 s et les vérifier après enregistrement. Observer les temps au début et à la fin, la charge CPU, le **pic de la somme des Private Bytes** de NoteVive et de son processus ASR, un éventuel retard, les débordements audio et la réactivité de la fenêtre. Si le Gestionnaire des tâches sert au premier passage, indiquer que ce relevé est indicatif et n’est pas une mesure du pic privé réel ; utiliser le [protocole P0](p0-windows.md) ou un outil Windows approuvé pour confirmer. Le facteur temps réel **RTF** vient uniquement du replay accéléré : temps de calcul divisé par durée audio, même source et même [chaîne de replay](../p0/asr_benchmark.md) sur W1/W2. Ne pas le déduire d’une dictée en direct.
5. **Bilan de latence.** Prendre la médiane et le P95 des temps d’affichage, puis reporter le taux de succès. Pour le P95 de contrôle, classer les échecs derrière toutes les latences réussies et indiquer que le P95 n’est pas satisfait si le quantile tombe sur un échec. Les objectifs projet à confronter au réel sont P95 ≤ 1,5 s entre début de la parole et premier mot correct, P95 ≤ 2 s entre fin de parole et segment final, mémoire privée ≤ 2 Go en incluant le démarrage et RTF ≤ 0,8 sur W1. Le découpage à la pause peut dépasser la cible de premier mot sur des passages continus et le [banc sans interface](../p0/asr_benchmark.md) a déjà relevé un P95 estimé de 4,20 s après la parole pour ce réglage ; le noter tel quel, sans requalifier artificiellement une mesure.

Sur un poste incompatible, vérifier que **Dicter** et `F9` restent indisponibles, que le message mentionne AVX2 et que le moteur et le micro ne démarrent pas. Vérifier la lecture et la modification d’une note fictive. Inscrire ce poste comme incompatible pour la dictée ; choisir un autre poste représentatif compatible pour mesurer W1 ou W2. La variante SSE2 se rejoue uniquement dans le [banc de diagnostic](../app/README.md) avec `--include-unsupported-baseline` et son délai inchangé de 90 s. Elle ne constitue pas un mode utilisateur ni un résultat de recette produit.

## Bibliothèque et récupération

| Essai | Manipulation sur données fictives | Attendu |
| --- | --- | --- |
| B1 — Réouverture | Créer une note « Suivi fictif 030 » contenant le marqueur `Œdème-banc-030`. Enregistrer, fermer, rouvrir. | Texte, titre et dates retrouvés, même si le ZIP a été extrait dans un autre dossier sur ce poste et ce compte. |
| B2 — Dossiers | Créer « Consultations », puis « Suivis » et « Contrôles » sous « Consultations ». Classer la note dans « Suivis », déplacer ensuite « Suivis » sous « Contrôles », renommer le dossier et rouvrir. | Arborescence et note au bon endroit ; l’identifiant et la date de création de la note restent fixes ; déplacement ou renommage du dossier parent sans réécriture des notes. Le choix de placer un dossier dans ses descendants est absent ou refusé. |
| B3 — Recherche et tri | Créer trois notes aux titres distincts avec des dates différentes ; modifier la plus ancienne. Chercher `oedeme` dans le contenu et `suivi fictif` dans le titre, puis passer du sous-dossier à tous les dossiers. Tester les trois tris. | Correspondances malgré accents et ligatures ; recherche locale limitée à la branche sélectionnée ou élargie selon l’option ; ordre différent entre création et modification ; tri titre cohérent. |
| B4 — Historique | Sur le même compte de test, enregistrer auparavant une note fictive avec l’ancien paquet Windows ; après fermeture, lancer le nouveau ZIP. Rouvrir, relire puis classer la note. | Ancienne note accessible sans import. Titre, texte et date de création préservés ; date de modification actualisée après classement. L’ancien pilote ne lit pas les notes rangées dont le format a évolué. |
| B5 — Panne du moteur | Pendant une dictée fictive, attendre un segment confirmé et vérifier le statut d’enregistrement. Dans le Gestionnaire des tâches, terminer uniquement le processus ASR de cette instance, pas la fenêtre NoteVive. | Fenêtre et texte confirmé conservés ; erreur lisible ; micro relâché ; nouvelle dictée possible sans écraser la note. Le passage non confirmé peut être perdu. |
| B6 — Fermeture forcée | Après avoir enregistré un marqueur, forcer l’arrêt de NoteVive via le Gestionnaire des tâches. Rouvrir et rechercher le marqueur. | Pas de perte du texte qui avait le statut enregistré. Vérifier que le processus ASR est lui aussi arrêté. |
| B7 — Veille et déconnexion | Sur une dictée fictive, verrouiller la session, puis tester une mise en veille et un débranchement de micro lors d’essais séparés. | Arrêt ou message explicite, aucune reprise automatique, texte confirmé sauvegardé conservé. |
| B8 — Fichier invalide | Sur une **copie** du ZIP, renommer temporairement le fichier modèle alors que l’application est fermée. Sur le compte de test seulement, le test DPAPI isolé peut simuler un fichier de note/dossier endommagé. | L’application signale le moteur indisponible sans perdre l’accès aux notes. Un dossier illisible ne masque pas les notes lisibles ; voir le [test de stockage](../app/windows/notes.md). |
| B9 — Conflit | Ouvrir la même note dans deux instances autorisées sur ce compte de test. Modifier et enregistrer dans la première, puis essayer d’écrire depuis la seconde. | Refus de l’écrasement de la version plus récente ; brouillon de la seconde gardé dans son éditeur, avec la possibilité d’une copie selon le parcours de sauvegarde. |

Après les tests de panne, confirmer que NoteVive ne reprend pas le micro à la relance. Sur un réseau de test isolé et avec des outils approuvés, observer aussi les sorties réseau des deux processus ; un test Wi‑Fi/Ethernet coupés établit la capacité à fonctionner hors ligne, pas à lui seul l’absence de tentative réseau.

## Relevé à remplir sur place

| Indicateur | W1 — 8 Go, sans GPU dédié | W2 — autre PC |
| --- | --- | --- |
| Windows/CPU/RAM/micro/stockage | | |
| SHA-256 ZIP, réglage de pause, date de l’essai | | |
| Démarrage fenêtre / micro à froid ; micro chaud | | |
| Début de parole → premier mot correct (médiane / P95 / échecs) | | |
| Fin de parole → segment final (médiane / P95 / échecs) | | |
| Arrêter → micro fermé / segment final (médiane / max) | | |
| Erreurs d’unités, doses, fractions, négations, latéralités ; ajouts / omissions | | |
| Termes rares corrects / total et contrôles de silence réussis | | |
| RTF replay / pic Private Bytes / surcharge / défauts audio | | |
| B1 à B9 : succès, échec ou non exécuté ; preuves locales | | |

Conserver les preuves brutes localement et partager seulement les métriques et anomalies sur données fictives. Une perte de texte confirmé et enregistré, un dossier invisible sans signal d’erreur, un micro qui reste actif après interruption ou une erreur critique de sens doit être consignée avant tout élargissement de l’essai. Un poste non testé reste **à qualifier**.
