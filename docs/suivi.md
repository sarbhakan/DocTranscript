# Registre de suivi · NoteVive

Dernière mise à jour : 13 novembre 2026. Ce registre suit les décisions, les preuves et les suites. Un lot peut être **À faire**, **En cours**, **En revue**, **Vérifié**, **Bloqué** ou **Rouvert**. « Vérifié » porte sur le livrable cité : une étude documentaire ne vaut pas essai Windows.

| ID | Statut | Responsable proposé | Résultat ou prochaine preuve |
| --- | --- | --- | --- |
| C0 | Vérifié | Coordination | Périmètre, feuille de route, dépôt cible, registre et proposition de nom/logo. |
| C1 | Vérifié | Agent moteurs | [Veille et banc d’essai](veille-moteurs.md) documentés ; aucune mesure projet. |
| C2 | Vérifié | Agent Windows | [Architecture et qualification](architecture-windows.md) documentées ; aucun poste testé. |
| C3 | Vérifié | Agent qualité | [Protocole médical et sources](qualite-medicale.md) documentés ; pas de praticien engagé à ce stade. |
| C4 | Vérifié | Coordination | [Flux, risques et revue du pilote](donnees-et-usage.md) et [réemploi GitHub](reemploi.md) documentés. |
| P0.1 | En cours | Coordination + Windows | [Procédure et inventaire](p0-windows.md) prêts. Relever les configurations de deux postes physiques, dont W1 à 8 Go sans GPU dédié. |
| P0.2 | En cours | Qualité + praticiens | [Lot dev](../p0/corpus/README.md) : 26 scénarios, 105 attributs et quatre contrôles sans parole générables. Enregistrer et annoter les voix, puis préparer et geler la confirmation privée avec des voix distinctes. |
| P0.3 | En cours | Moteurs + Windows | [Banc et packs](../p0/README.md) prêts, simulés sur macOS. Préparer le lot de poids/wheels vérifiés, puis exécuter les quatre adaptateurs sur W1/W2. |
| P0.4 | En cours | QA indépendant + suivi | Revue des interfaces et des cas d’échec lancée. Reste la contre-vérification physique, le rapport chiffré et le choix de l’unique configuration distribuée. |
| P1 | En revue | Développement + QA | [Prototype EXE portable](../app/README.md) compilé pour Windows x64. Vérifier sur Windows l’ouverture hors ligne, la capture, l’éditeur, les notes chiffrées et les interruptions avant qualification. |
| P2 | À faire | Windows + QA | Matrice de destinations, transfert confirmé, tests de refus et reprise. |
| P3.1 | Vérifié sur macOS | Coordination + sources + QA indépendant | [Catalogue compilé](../lexique/README.md) et reconstruit indépendamment : 90 266 entrées, sept référentiels, huit fichiers d’entrée. Transférer et vérifier sur Windows ; rien n’est injecté au moteur. |
| P3.2 | À faire | Moteurs + qualité + praticiens | [Protocole](../p0/lexical_experiment.md) prêt ; sélectionner les variantes parlées, mesurer avec et sans biais, revoir les erreurs et les règles de mise en forme. |
| P4 | À faire | Coordination + QA + praticiens | Bêta simulée, documentation de support, signature et publication après revue. |

| Décision | État | Condition de clôture |
| --- | --- | --- |
| D01 · Poste minimal et moteur unique | Ouverte | Rapport P0 reproductible sur matériel représentatif, configuration retenue et conditions d’indisponibilité justifiées. |
| D02 · Stack WPF et .NET, modèle embarqué | Proposition | Exécutable et moteur validés sur machine neuve hors ligne. |
| D03 · Niveau de transfert externe | Ouverte | Validation d’un champ et de sa destination ; privilégier l’intégration éditeur en clinique. |
| D04 · Conservation de l’audio | Proposition : aucune par défaut | Confirmer le besoin de réécoute persistante et le cadre avec le cabinet avant tout ajout. |
| D05 · Licence du projet, nom et logo | Ouverte | Le dépôt de sources est public sans licence générale déclarée. Choisir une licence, vérifier la marque et finaliser l’inventaire des droits amont avant distribution stable. |
| D06 · Mise en forme avancée et spécialités suivantes | Ouverte | Gabarits d’abord ; vérifier la demande et la fidélité avant chaque extension. |
| D07 · Un installateur et une configuration ASR | Actée | Les comparateurs P0 restent au banc ; les profils de pratique partagent le moteur et l’éditeur. Publier une version stable après recette locale Windows et revue des artefacts. |

| Risque prioritaire | Signal d’alerte | Réponse et lot |
| --- | --- | --- |
| Débit insuffisant ou texte instable sur PC modeste | Hypothèses tardives, files qui grossissent | Comparer vrai flux, fenêtre et phrase ; ajuster le plancher matériel ou réduire le périmètre (P0). |
| Négation, dose ou terme clinique inversé | Erreur critique récurrente, y compris avec glossaire | Corpus à risque, revue humaine, retrait d’un profil ou d’un biais sans bénéfice démontré (P0/P3). |
| Champ ou dossier patient incorrect | Le focus, le contexte ou la destination sont ambigus | Refus par défaut ; garder le texte dans l’éditeur ; intégration explicite avant ouverture clinique (P2). |
| Données copiées ou perdues | Trace dans un log, destinataire synchronisé, restauration impossible | Modèle de flux, essais hors réseau, vérification des traces et restauration (P1/P4). |
| Licence ou provenance insuffisante | Poids, lexique ou source non redistribuable | Relever la licence de l’artefact exact, exclure/remplacer le composant ou distribuer séparément si autorisé (P0/P4). |

Pour chaque boucle, l’agent de suivi ajoute une entrée avec : **date | lot | version/commit et empreintes | poste et corpus | résultat / seuil / effectif | preuve et écart | responsable | décision et prochaine action**. Le testeur indépendant confirme le scénario, le résultat et les blocages. Les liens pointent vers des preuves fictives ou agrégées et n’exposent ni audio privé ni identifiant patient. Une régression de sécurité, d’intégrité ou de fidélité critique fait passer le lot à « Rouvert » ; une décision externe indispensable et indisponible est marquée « Bloqué » avec son prérequis.

**13 novembre 2026 · C0–C4.** Trois axes de veille en parallèle : moteurs, Windows, français médical. Relecture croisée de la feuille de route, des mesures moteur et du flux des données. Rapport intégré localement, nom NoteVive provisoire, logo SVG source et aperçu PNG. Hôte de cadrage macOS ARM64 ; aucune exécution Windows ni aucun essai clinique. Cible distante [DocTranscript](https://github.com/sarbhakan/DocTranscript) vérifiée comme publique et vide lors du cadrage ; aucune publication à ce stade. Prochaine action : P0.1–P0.3 en parallèle, puis recette P0.4.

**13 novembre 2026 · P0, préparation.** Trois agents en parallèle : banc/protocole, corpus, recette Windows ; coordination, adaptateurs, packs et grille de revue à l’intégration. Contre-vérifications des échecs du banc, des empreintes de packs, du corpus et de la grille de revue. Les 13 tests du banc et le parcours des quatre contrôles passent sur macOS avec un moteur simulé. Les [portes suivantes](recette-iterative.md) séparent explicitement interface et audio, base locale, intégration de champs et fidélité médicale. Prochaine preuve : chargement réel hors ligne, puis mesures W1/W2 et relecture des dictées fictives humaines. Aucun résultat Windows, aucun corpus de confirmation enregistré, aucune publication GitHub pour ce lot à ce stade.

**13 novembre 2026 · Catalogue et ergonomie.** Trois agents en parallèle : référentiels et licences, adaptation du moteur, recette praticien. Intégration des convertisseurs et du manifeste, puis reconstruction et recherches par un agent indépendant. La revue a identifié la limite NTFS de l’écriture atomique et une erreur d’encodage en redirection ; NTFS est documenté et le scénario d’encodage a été ajouté à la recette automatisée. La [maquette et les scénarios E1 à E6](experience-praticien.md) définissent la première note, la correction en direct, l’interruption, la recherche de notes et le transfert contrôlé. Aucune mesure de fidélité nouvelle, aucun moteur entraîné, aucun praticien ni poste Windows testé dans cette boucle.

**13 novembre 2026 · Prototype portable.** Répartition interface Win32, moteur en flux WinMM/Sherpa-ONNX et bibliothèque DPAPI ; intégration de la recherche locale, des empreintes, du logo et des notices au paquet. Les poids inclus ont produit une transcription sur un extrait de démonstration public avec le moteur macOS de même version. C’est un contrôle de fonctionnement, sans mesure médicale ni résultat Windows. Les exécutables de test des notes et du moteur sont compilés pour Windows ; les exécuter avec la recette du paquet sur W1/W2 avant de décider la suite. Pas de publication GitHub.

**13 novembre 2026 · Publication des sources.** Sources, documentation et corpus fictif publiés sur [DocTranscript](https://github.com/sarbhakan/DocTranscript) ; premier commit du prototype [`adf5d55`](https://github.com/sarbhakan/DocTranscript/commit/adf5d558950b5423e42f38c213b915903b3902e0). Les 19 tests du banc et du catalogue passent sur macOS ; le manifeste des 26 cas et 105 attributs est cohérent. Le ZIP d’essai reste local. Les empreintes des deux fichiers BDPM concordent avec les téléchargements officiels et le fichier des informations importantes a été consulté. Avant une diffusion publique du paquet incluant la BDPM, définir comment vérifier les nouvelles corrections, actualiser le catalogue hors ligne et remplacer les paquets périmés, conformément aux [conditions du portail BDPM](https://base-donnees-publique.medicaments.gouv.fr/telechargement). Prochaine preuve : recette du même paquet sur W1/W2, dont W1 à 8 Go sans GPU dédié.
