<p align="center"><img src="assets/notevive.svg" width="84" alt="Logo NoteVive : une onde de voix sur une feuille"></p>

# NoteVive · DocTranscript

**Dictez une note en français, relisez-la et retrouvez-la sur votre ordinateur.** NoteVive transforme la voix en texte et vous permet de classer, rechercher et copier vos notes. Le traitement et la sauvegarde se font sur votre PC. Une fois le téléchargement terminé, NoteVive fonctionne sans Internet.

## Télécharger et essayer l’application

### [Télécharger NoteVive 0.4.1 pour Windows — ZIP prêt à ouvrir](https://github.com/sarbhakan/DocTranscript/releases/download/v0.4.1-essai/NoteVive-Windows-x64-Essai.zip)

[Voir la Release et son fichier de contrôle](https://github.com/sarbhakan/DocTranscript/releases/tag/v0.4.1-essai) · Un seul paquet, modèle et catalogue inclus.

**[Ouvrir le guide pas à pas pour débuter](docs/guide-essai-windows.md)**

Le téléchargement est public : aucun compte GitHub ou NoteVive n’est nécessaire. Le ZIP contient l’application et son modèle de reconnaissance vocale. Vous n’avez aucun outil de programmation à installer.

**Version d’essai : utilisez uniquement des dictées fictives.** La transcription peut se tromper, notamment sur les doses et les négations. Le texte apparaît après les pauses et le calcul, dont la durée dépend du PC. L’application n’est pas qualifiée pour les dossiers patients.

1. **Téléchargez `NoteVive-Windows-x64-Essai.zip`** avec le lien direct ci-dessus ou dans les fichiers de la Release 0.4.1. Attendez la fin du téléchargement, puis retrouvez le ZIP, souvent dans **Téléchargements**.
2. **Faites un clic droit sur le ZIP, puis « Extraire tout ».** Ouvrez le dossier obtenu, puis le dossier **NoteVive** qu’il contient. Gardez tous les fichiers ensemble.
3. **Double-cliquez sur `NoteVive.exe`.** Windows peut afficher simplement **NoteVive**, avec le type **Application**. C’est le fichier à ouvrir à chaque utilisation ; il n’y a pas d’assistant d’installation.
4. **Cliquez sur « Nouvelle note »**, donnez un titre, puis cliquez sur **Dicter**. Attendez le message **Micro ouvert**. Dites « Pas de douleur à la cheville droite », puis laissez une pause pour voir le texte apparaître.
5. **Cliquez sur « Arrêter »**, attendez la fin du traitement, relisez et attendez la confirmation de sauvegarde automatique. Une fois la sauvegarde confirmée, fermez et rouvrez l’application pour retrouver votre note.

Si Windows bloque le lancement, suivez la rubrique [dépannage](docs/guide-essai-windows.md#depannage). Le paquet d’essai est non signé ; certains postes demandent l’intervention du service informatique.

> Sur GitHub, **« Code → Download ZIP »** et **« Source code »** téléchargent les fichiers de développement. Pour utiliser l’application, choisissez le fichier **`NoteVive-Windows-x64-Essai.zip`** lié ci-dessus. Le petit fichier `.sha256` sert à vérifier le téléchargement ; il ne lance pas NoteVive.

## Sur quel ordinateur ?

| Votre ordinateur | Ce qui est disponible |
| --- | --- |
| **Windows 11, processeur Intel ou AMD, système x64** | Le ZIP d’essai prêt à ouvrir. Un microphone est nécessaire pour dicter. Aucune carte graphique dédiée n’est requise. NoteVive vérifie lui-même la compatibilité du processeur avant la dictée. |
| **Mac** | Les sources du prototype Mac et son [guide technique](app/macos/README.md). **Aucune `.app` Mac prête à télécharger n’est actuellement publiée dans les Releases.** Une personne disposant seulement de ce dépôt ne peut donc pas encore installer la version Mac sans la construire. |

La dictée Windows exige un processeur compatible **AVX2** et ses extensions associées. Les tests sur deux PC physiques, dont un modèle à **8 Go de mémoire sans GPU dédié**, restent à faire : la compatibilité et la vitesse sur ce poste ne sont pas encore validées. Le [guide](docs/guide-essai-windows.md#avant-de-commencer) explique comment vérifier la version de Windows.

## Ce que vous pouvez tester

- Dicter dans la fenêtre NoteVive, puis modifier le texte et le titre.
- Créer des dossiers et des sous-dossiers ; ranger une note avec **Actions → Classer la note…**.
- Rechercher dans les titres et le texte ; trier par modification, création ou titre.
- Fermer puis rouvrir l’application pour retrouver les notes du même compte Windows sur le même PC.
- Avec **Copier** ou **Ctrl+Maj+C**, copier uniquement le corps de la note pour le coller vous-même.
- Avec **Ctrl+Alt+Espace**, essayer la dictée vers un champ externe compatible. NoteVive crée une note locale par session et y sauvegarde chaque passage confirmé avant de l’envoyer.
- Consulter le catalogue médical local avec **Actions → Vocabulaire médical…**.

Le [guide d’utilisation](docs/guide-essai-windows.md#organiser-les-notes) détaille ces gestes. Les notes sont sauvegardées séparément du dossier de l’application et chiffrées pour le compte Windows courant. Aucun enregistrement audio n’est conservé.

Pour la [dictée vers Word ou le navigateur](docs/dictee-externe.md), utilisez uniquement un document ou un champ fictif. **Edge et Word restent à qualifier sur un poste Windows réel.** Si le champ est refusé, dictez dans NoteVive puis utilisez **Copier** après relecture. La compatibilité dépend du champ et la destination peut synchroniser ce qu’elle reçoit. Gardez le curseur dans le même champ et vérifiez le résultat après l’envoi. Le texte copié reste lisible par les applications locales qui ont accès au presse-papiers. **F9** continue d’agir dans la fenêtre NoteVive ; **Vocabulaire médical** reste un catalogue de consultation. Les fonctions du prototype Mac peuvent différer.

## Ce qui change dans cet essai

La version **0.4.1** simplifie la fenêtre : **Nouvelle note**, **Dicter / Arrêter**, **Copier** et **Actions** sont les quatre commandes visibles. Le menu Actions rassemble le classement, les dossiers, les tris et les fonctions occasionnelles. La recherche reste dans la bibliothèque et le texte occupe l’essentiel de l’écran. Le [guide du carnet](docs/ui-041.md) explique ce parcours.

Le [vocabulaire enrichi](docs/lexique-041.md) contient **100 175 entrées, soit 99 192 libellés distincts**, dont les médicaments et substances du RUIM de l’ANSM, avec des domaines et des types pour affiner la recherche. Les maladies rares sont rattachées aux **33 classifications françaises d’Orphanet**. Ces domaines se recouvrent ; le nombre de libellés n’est ni un taux de précision ni une couverture complète de toutes les spécialités. Le glossaire est consultatif et ne remplace aucun mot ou dosage automatiquement.

Le [bilan de consolidation](docs/consolidation-041.md) distingue le correctif d’entraînement, les comparaisons de reconnaissance et les vérifications Windows. Les trois nouveaux adaptateurs et l’injection globale du lexique ont été écartés après des régressions sur des éléments critiques. Le moteur et le modèle distribués sont conservés. Le [test lexical apparié](p0/lexical_cpp_041.md) montre qu’un meilleur score sur les noms de médicaments peut s’accompagner de pertes de doses, de fractions et de négations. Les [33 dictées fictives à lire](docs/dictees-fiabilisation.md) permettent de poursuivre les essais. Les [expériences précédentes sur 96 extraits](docs/precision-vitesse-041.md) et l’[entraînement initial](docs/entrainement-local.md) restent consultables.

## Besoin d’aide ou envie de transmettre un résultat ?

Commencez par le [dépannage pas à pas](docs/guide-essai-windows.md#depannage). Pour nous transmettre un essai, ouvrez le [formulaire de retour](https://github.com/sarbhakan/DocTranscript/issues/new?template=essai-notevive.yml) : il vous guide sur les informations utiles, même si vous ne connaissez pas les caractéristiques techniques du PC. Un compte GitHub est nécessaire pour envoyer ce formulaire. Vous pouvez aussi transmettre les mêmes observations à la personne qui vous a fourni le lien du dépôt.

Utilisez uniquement des exemples fictifs dans vos retours et captures d’écran. La [recette sur deux PC](docs/windows-recette-030.md) s’adresse aux personnes qui souhaitent faire des essais plus approfondis.

## Comprendre les fichiers du dépôt

Pour essayer l’application, le **ZIP de la Release** et le **guide pas à pas** suffisent. Les autres fichiers servent à documenter et à faire évoluer le projet.

| Dossier | Contenu et public concerné |
| --- | --- |
| [`docs/`](docs/) | Guide d’utilisation, suivi du projet, choix techniques et protocoles d’essai. |
| [`app/`](app/README.md) | Code de l’application Windows, notices et instructions de construction pour développeurs. Le sous-dossier [`macos/`](app/macos/README.md) contient le prototype Mac. |
| [`p0/`](p0/README.md) | Outils et résultats de comparaison des moteurs de transcription. Réservés aux essais techniques. |
| [`lexique/`](lexique/README.md) | Sources, licences et préparation des catalogues médicaux locaux. Le catalogue nécessaire à l’essai Windows est déjà dans le ZIP. |
| [`assets/`](assets/) | Logo et éléments visuels du projet. |

<details>
<summary><strong>Documentation technique et contribution</strong></summary>

Le paquet Windows s’appuie sur **Whisper Large-v3 Turbo, whisper.cpp 1.8.5, OpenBLAS 0.3.34 et Silero 6.2**. Le traitement démarre après une pause de 576 ms ; le temps de calcul s’y ajoute. Le moteur tourne dans un processus séparé. Le catalogue public contient 100 175 entrées de douze sources déclarées, avec les entrées RUIM et sans extrait des fichiers BDPM. Le prototype Mac 0.2.1 utilise UltiMed INT8 et Silero ; il reste distinct de ce paquet Windows.

| Document | Ce qu’il permet de comprendre |
| --- | --- |
| [Plan de fiabilisation médicale](docs/plan-fiabilisation-medicale.md) | Prochaines étapes, rôle de Hakan et des médecins, méthodes d’amélioration et preuves nécessaires avant un pilote. |
| [Feuille de route](docs/feuille-de-route.md) · [Registre de suivi](docs/suivi.md) | Périmètre, tâches, décisions, risques et preuves de réalisation. |
| [Construction Windows](app/README.md) · [Architecture](docs/architecture-windows.md) | Composants, compilation, capture et stockage. |
| [Résultats comparés](p0/asr_benchmark.md) · [Choix du moteur](docs/p0-choix-moteur.md) | Mesures disponibles, erreurs observées et limites de performance. |
| [Banc P0](p0/README.md) · [Procédure Windows](docs/p0-windows.md) · [Recette par lot](docs/recette-iterative.md) | Préparation des essais, reproduction et critères de vérification. |
| [Veille des moteurs](docs/veille-moteurs.md) · [Réemploi](docs/reemploi.md) | Alternatives, licences et rôle de Dev Toolkit Orchestrator. |
| [Carnet simplifié](docs/ui-041.md) · [Toolkit et composants retenus](docs/toolkit-040.md) | Choix d’interface, accessibilité, sources réutilisées et périmètre des outils. |
| [Entraînement local](docs/entrainement-local.md) · [Outils de reproduction](p0/training/README.md) | Données séparées, adaptation LoRA, contrôles critiques et décision sur les poids. |
| [Derniers essais médicaux et Windows](docs/consolidation-041.md) · [Dictées fictives](docs/dictees-fiabilisation.md) | Résultats sur 96 enregistrements, échecs conservés, comparaison Windows appariée et scripts accessibles. |
| [Qualité médicale](docs/qualite-medicale.md) · [Adaptation lexicale](docs/adaptation-lexicale.md) | Vocabulaire, évaluation des erreurs critiques et effets des lexiques. |
| [Référentiels médicaux](docs/referentiels-medicaux.md) · [Catalogue local](lexique/README.md) | Sources françaises, licences et imports reproductibles. |
| [Expérience praticien](docs/experience-praticien.md) · [Données et usage professionnel](docs/donnees-et-usage.md) | Scénarios d’usage, flux des données et conditions préalables à un pilote. |

Les vérifications Windows sont consultables dans les [exécutions de l’intégration continue](https://github.com/sarbhakan/DocTranscript/actions/workflows/windows.yml). Elles ne remplacent pas les essais au micro sur les deux PC physiques, ni les essais manuels dans Word et le navigateur. Les [mesures Windows déjà disponibles](docs/p0-choix-moteur.md) restent au-dessus des objectifs de latence.

Le projet vise **un paquet Windows et une configuration de transcription qualifiée**. Une livraison stable demande encore les essais physiques, la revue avec des praticiens et la signature de l’application. Les versions, empreintes et [licences des composants](app/NOTICE.md) sont documentées. Le dépôt ne déclare pas encore de licence générale pour le code NoteVive.

</details>
