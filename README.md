<p align="center"><img src="assets/notevive.svg" width="84" alt="Logo NoteVive : une onde de voix sur une feuille"></p>

# NoteVive · DocTranscript

**Dictée médicale en français, aux pauses et hors ligne.** NoteVive transforme une dictée en brouillon éditable sur Windows. Les phrases reconnues sont ajoutées au fil des pauses. La bibliothèque locale permet de renommer les notes, les classer en dossiers et sous-dossiers, rechercher leur contenu et trier par titre, création ou modification.

**Préversion Windows 0.3.0, réservée aux données fictives.** Le paquet utilise Whisper Large-v3 Turbo Q5_0 avec whisper.cpp, OpenBLAS et Silero 6.2. Le traitement démarre après une pause de 576 ms ; l’affichage dépend ensuite du temps de calcul. La [CI Windows](https://github.com/sarbhakan/DocTranscript/actions/runs/43620136119/job/132523751821) valide les contrôles natifs, les trois extraits fictifs et le parcours automatisé de l’interface. Les [mesures](docs/p0-choix-moteur.md) montrent que le calcul reste plus long que la parole sur les contrôles Windows. Les essais au micro sur deux PC physiques, dont un à 8 Go sans GPU dédié, restent à faire.

## Préparer l’essai sur Windows 11 x64

**Téléchargement : [préversion Windows v0.3.0-essai](https://github.com/sarbhakan/DocTranscript/releases/tag/v0.3.0-essai).** Choisir `NoteVive-Windows-x64-Essai.zip` et son fichier `.sha256`. Les archives « Source code » ne contiennent pas l’EXE.

La dictée dans le candidat 0.3.0 demande un processeur x64 compatible **AVX2** et ses extensions associées, sans GPU dédié. Si le processeur est incompatible, NoteVive le signale avant d’ouvrir le micro et la bibliothèque reste accessible.

Vérifier le SHA-256 du ZIP, l’extraire en entier et ouvrir `NoteVive.exe` dans le dossier extrait. Le modèle est inclus. Pour un premier test, cliquer sur **Dicter**, attendre **Micro ouvert**, puis lire « Pas de douleur de la cheville droite. La gêne concerne la cheville gauche depuis cinq jours. » Cliquer sur **Arrêter**, relire et renommer la note. Fermer puis rouvrir NoteVive pour vérifier la sauvegarde.

[Guide d’essai et dépannage](docs/guide-essai-windows.md) · [Recette 0.3.0 sur deux PC](docs/windows-recette-030.md) · [Résultats comparés](p0/asr_benchmark.md)

Le prototype utilise le microphone par défaut de Windows et sauvegarde les brouillons chiffrés pour le compte Windows courant. Le bouton **Vocabulaire** consulte un catalogue de six référentiels ; il ne modifie pas la dictée. La Base de données publique des médicaments (BDPM) est exclue du ZIP public. Le texte reste dans NoteVive à ce stade. Le moteur tourne dans un processus séparé : une interruption signale l’erreur et conserve les phrases déjà affichées. Le raccourci F9 démarre et arrête la dictée dans NoteVive ; l’insertion directe dans un logiciel médical externe reste à réaliser.

## Essayer sur Mac

Le prototype natif pour **Mac Apple Silicon, macOS 15 ou ultérieur** inclut UltiMed INT8 et Silero pour afficher les phrases à chaque pause. Il propose une bibliothèque de notes avec sauvegarde automatique, recherche, dates et dossiers, un export TXT et [14 lexiques médicaux locaux par spécialité](lexique/PROFILS.md). Le [guide Mac](app/macos/README.md) décrit le lancement et la compilation. Cette branche publie aussi les sources de cette .app de test. Le changement de moteur de la version Windows ne remplace pas la .app Mac déjà installée.

## Lire et contribuer au projet

| Document | Ce qu’il permet de décider |
| --- | --- |
| [Feuille de route](docs/feuille-de-route.md) | Périmètre, tâches ordonnées, critères de passage et livraison. |
| [Exécutable Windows d’essai](app/README.md) | Lancement, choix techniques, construction et recette de l’EXE portable. |
| [Banc P0](p0/README.md) · [Procédure Windows](docs/p0-windows.md) | Préparer le lot, rejouer les dictées, comparer les moteurs sur deux PC. |
| [Recette par lot](docs/recette-iterative.md) | Contrôles indépendants de l’interface, des interactions, du stockage et de la livraison. |
| [Veille des moteurs](docs/veille-moteurs.md) | Candidats locaux, licences et protocole de mesure CPU. |
| [Architecture Windows](docs/architecture-windows.md) | Application, EXE, capture, stockage et transfert vers un champ externe. |
| [Qualité médicale](docs/qualite-medicale.md) | Vocabulaire, jeux d’essai, adaptation et évaluation des erreurs critiques. |
| [Référentiels médicaux](docs/referentiels-medicaux.md) · [Catalogue local](lexique/README.md) | Sources françaises, licences, imports reproductibles et recherche hors ligne. |
| [Adaptation lexicale](docs/adaptation-lexicale.md) · [Expérience praticien](docs/experience-praticien.md) | Vérifier l’apport du vocabulaire et éprouver les gestes quotidiens avant de figer l’interface. |
| [Données et usage professionnel](docs/donnees-et-usage.md) | Flux des données, mesures techniques et conditions préalables à un pilote. |
| [Veille des applications et outillage](docs/reemploi.md) | Références GitHub, stratégie de réemploi et rôle de Dev Toolkit Orchestrator. |
| [Registre de suivi](docs/suivi.md) | Statuts, décisions, risques et compte rendu de chaque boucle. |

Le produit vise **un paquet Windows et une configuration de transcription qualifiée**. Les moteurs du banc P0 restent des comparateurs de développement. Une éventuelle préversion publique sert aux essais fictifs ; une livraison stable demande la qualification Windows, la revue avec des praticiens et la signature de l’artefact. Les modèles et référentiels sont documentés par version, empreinte et conditions d’utilisation. Voir [les licences des composants](app/NOTICE.md). Le dépôt ne déclare pas encore de licence générale pour le code NoteVive.

Pour signaler un problème, utiliser les [Issues GitHub](https://github.com/sarbhakan/DocTranscript/issues) avec un exemple fictif, la version Windows et les étapes de reproduction. Ne joindre ni note ou audio patient, ni copie de la bibliothèque locale.

Logo de travail : [source SVG](assets/notevive.svg) · [aperçu PNG](assets/notevive.png).
