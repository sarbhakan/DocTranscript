# Validation de NoteVive Windows 0.4.0

État au 15 novembre 2026 : [préversion 0.4.0 publiée](https://github.com/sarbhakan/DocTranscript/releases/tag/v0.4.0-essai), reconstruite et vérifiée sur son commit exact. Recettes du produit, des champs Win32 et du chemin UI Automation WPF réussies. Cette page sépare les preuves de fonctionnement, la comparaison des poids et la qualification d’un usage médical. La version reste un essai sur des données fictives.

## Changements examinés

L’[interface](ui-040.md) conserve les contrôles Windows et leur navigation au clavier, avec une nouvelle hiérarchie visuelle, une bibliothèque latérale et un éditeur plus lisible. La [dictée externe](dictee-externe.md) vérifie la destination, affiche un indicateur du micro et enregistre le texte localement avant son envoi. La copie est une action explicite. Le moteur et les poids du paquet 0.3.1 sont conservés.

## Recette logicielle

Sur Mac, le banc exécute 98 tests : 97 réussis et un cas optionnel PEFT ignoré dans l’environnement Python ordinaire. Le lexique exécute 12 tests : 11 réussis et un cas ignoré faute de fixture optionnelle. La compilation croisée stricte des nouveaux composants complète ces vérifications. Une compilation croisée ne prouve ni l’apparence native ni la saisie dans Word.

Le [run Windows initial de cette refonte](https://github.com/sarbhakan/DocTranscript/actions/runs/43640910690) passe le stockage chiffré, les migrations, les dossiers imbriqués, la récupération, le protocole, le superviseur, la construction du ZIP et les contrôles audio des doses et fractions. Le parcours de bibliothèque passe également la recherche, les tris, le classement et la réouverture. Il échoue ensuite sur le bouton Copier resté désactivé après chargement d’une note. Ce défaut produit est corrigé : l’état de la copie est recalculé après chaque chargement, modification ou changement de visibilité. La recette exige aussi que la copie soit désactivée pour une note vide.

Le premier essai de capture échoue parce que le même compte possède déjà les notes fictives de la recette précédente. La version réservée aux captures utilise maintenant un dossier de stockage distinct et marqué comme tel. Aucun profil n’est supprimé pour faire passer le test. Ce binaire ne fait pas partie du ZIP distribué ; la protection de capture de l’application ordinaire reste active.

Les sondes de dictée externe sont exécutées dans un job indépendant. Les premiers essais ont révélé que le serveur Windows de CI et son bureau fonctionnent en administrateur ; la protection du produit refuse correctement cette destination. La recette doit utiliser une session de test non élevée. Un échec d’initialisation du processus de recette n’est pas présenté comme une réussite de la saisie.

Le [run `625d94e`](https://github.com/sarbhakan/DocTranscript/actions/runs/43643536468/job/132596101512) crée un véritable compte standard et réussit la recette des champs `EDIT` natifs. Les insertions Unicode au curseur, les deux segments, l’absence d’écriture dans l’autre champ, le refus des mots de passe, de la lecture seule, des contrôles ANSI et des sélections, ainsi que l’invalidation après changement de champ ou de fenêtre sont vérifiés. Le même run échoue ensuite au démarrage du profil Edge de test, avant toute assertion de saisie dans le navigateur. La compatibilité navigateur n’est donc pas encore déclarée réussie sur cette preuve.

Le [job Windows `bd8f7ee`](https://github.com/sarbhakan/DocTranscript/actions/runs/43645646862/job/132602688270) réussit ensuite toutes les étapes obligatoires de construction, de stockage, d’audio et d’interface. La recette utilise le ZIP extrait ; elle vérifie aussi la copie après réouverture et son indisponibilité pour une note vide. La [capture réelle](../assets/notevive-windows-040.png) issue du parcours fictif a été inspectée : bibliothèque, éditeur, boutons, polices, version 0.4.0 et état de copie sont visibles. Le binaire destiné aux captures reste séparé du paquet distribué.

Les [mesures agrégées du candidat](../p0/windows_040.json) proviennent d’une VM AMD EPYC 9V74, avec deux cœurs, quatre processeurs logiques et 17,17 Go de mémoire. Les trois paroles de 6,44 / 16,8 / 15,2 s prennent 14,399 / 53,951 / 39,872 s, démarrage compris. Les contrôles numériques et les fractions passent ; le nom exact « Imovane » manque toujours sur une fixture. La mémoire privée maximale échantillonnée, parent et moteur réunis, atteint 1 955 463 168 octets ; un échantillon partiel est signalé sur cette fixture. Ces durées ne sont pas le délai après une pause au microphone et les hôtes diffèrent entre les runs. Aucun gain de vitesse ni qualification d’un PC physique à 8 Go n’est déduit de cette mesure.

La relecture indépendante de `main.cpp`, `external_target.cpp`, `dictation_overlay.cpp` et `ui_theme.cpp` n’identifie pas de nouveau défaut bloquant ou P1. Elle vérifie notamment la sauvegarde avant envoi, l’invalidation permanente de la destination, le blocage des changements de note et le maintien de l’alerte lorsque l’arrêt du microphone n’est pas confirmé. Cette lecture statique ne remplace pas la recette réelle des applications de destination.

Les preuves du paquet publié et son empreinte figurent ci-dessous. Les échecs du lanceur Edge sous le compte standard de la VM de CI restent visibles dans l’historique : ils ne sont pas comptés comme des tests réussis du navigateur.

## Périmètre de la porte de publication

La préversion fictive exige la réussite de la construction du ZIP, du stockage et de la récupération, des contrôles audio, de l’interface, des champs Win32 et du chemin UI Automation / `SendInput` sur des champs WPF synthétiques. Le [premier test WPF](https://github.com/sarbhakan/DocTranscript/actions/runs/43662506430/job/132654688388) a renvoyé `unsupported` à la capture, avant tout envoi. Cet échec a été conservé et diagnostiqué avant toute publication. Les clients natif et managé ne voyaient alors que la fenêtre, sans les champs du fournisseur WPF.

Le même run isole le blocage préalable du rendu Edge : Windows refuse l’accès au répertoire NPFS AppContainer du compte secondaire. La lecture non mutante des ancêtres confirme notamment le refus de lecture de cette branche. Aucun droit NPFS n’est modifié ; les droits temporaires des autres objets sont restaurés et vérifiés. Le test n’atteint aucune assertion de saisie dans Edge. Il ne constitue donc ni une réussite de compatibilité, ni une preuve de panne du produit dans une session Windows ordinaire.

Après revue indépendante, ce contrôle d’environnement reste disponible sous sa forme stricte avec l’entrée manuelle `diagnostic_edge` du workflow. Il est séparé des critères de cette préversion ; son absence dans un run ordinaire signifie **non exécuté**, pas validé. La recette Edge inchangée doit être exécutée dans une vraie session Windows 11 avec un compte standard avant toute annonce de compatibilité navigateur. Word demande aussi une recette réelle. La réussite WPF qualifie seulement la voie technique testée. La copie explicite reste le recours proposé pour les logiciels non qualifiés.

Le [test `97a6510`](https://github.com/sarbhakan/DocTranscript/actions/runs/43664261422/job/132660044750) réussit ensuite Win32 et WPF avec les mêmes contrôles et les mêmes assertions. Le seul changement concerne le compte de recette : accès temporaire `0xF` à `BaseNamedObjects`, déjà mesuré nécessaire à la création d’un mutex local sur ce serveur. Le bureau Native, le confinement et les protections du produit restent inchangés ; aucun accès AppContainer n’est ajouté pour WPF. L’accès précédemment refusé est vérifié, puis la DACL d’origine est restaurée et relue après l’arrêt des descendants.

La capture WPF réussit dès la première tentative. Les caractères `é` et `½` arrivent exactement au curseur dans deux champs distincts ; les autres champs conservent leur contenu. Le changement de focus invalide définitivement la cible, et les sélections, champs en lecture seule et mots de passe sont refusés. Les diagnostics conditionnels restent absents du binaire de production. Ces résultats ne valident ni Word ni Edge et ne mesurent pas une dictée au microphone.

## Paquet publié et vérifié

La [Release `v0.4.0-essai`](https://github.com/sarbhakan/DocTranscript/releases/tag/v0.4.0-essai) provient du commit `e91e81e873b1687063b5dd11f9c2ffa4a40e9b1a`. Le [workflow de livraison](https://github.com/sarbhakan/DocTranscript/actions/runs/43664693895) reconstruit le ZIP, l’extrait et réussit les tests de stockage, d’audio, d’interface, de Win32 et de WPF, puis vérifie les octets du ZIP avant publication. Le tag résout vers ce même commit. Edge est non exécuté dans ce passage et reste non qualifié.

Un seul paquet applicatif est publié : `NoteVive-Windows-x64-Essai.zip`, **544 461 363 octets**, SHA-256 `6bb31379213506fb60ca0cd49014ad8061a34fc56829d629a80d3bfa38ce49d9`. Le fichier de contrôle téléchargé concorde avec ce SHA et avec le digest de l’asset GitHub. Les archives « Source code » sont produites par GitHub et ne constituent pas d’autres paquets applicatifs.

Les [mesures exactes de livraison](../p0/windows_040.json) sont conservées séparément du candidat. Sur la VM EPYC 9V74 à deux cœurs/quatre processeurs logiques et 17,17 Go de mémoire, les trois paroles de 6,44 / 16,8 / 15,2 s prennent **14,434 / 52,710 / 40,336 s**, démarrage compris. Trois doses, trois fractions et les trois suites numériques attendues passent ; deux noms sur trois sont présents, avec « Imovane » toujours manquant sur `px-23`. Le maximum de mémoire privée échantillonnée, parent et moteur réunis, atteint **1 955 401 728 octets** ; aucun échantillon partiel n’est signalé. Ces résultats ne mesurent pas la latence après une pause au micro et ne qualifient pas un PC physique à 8 Go.

## Entraînement réellement exécuté, modèle distribué conservé

Le [rapport d’entraînement](entrainement-local.md) et les rapports JSON dans `p0/training` documentent une passe complète : 1 081 extraits, 32 voix, 271 mises à jour LoRA, puis 282 extraits de validation sur huit autres voix. La copie exacte des poids, la fin de séquence, le gel du modèle de base et l’absence de recouvrement des partitions sont contrôlés.

Sur 32 dictées sélectionnées pour le développement, les erreurs de mots passent de 80/371 à 30/371 avec l’adaptateur final. Le contrôle apparié trouve néanmoins deux pertes de noms de médicaments et une perte d’association médicament–dosage. Les points 50 et 150 sont également refusés. Les bénéfices moyens ne compensent pas de nouvelles erreurs critiques. Aucun modèle adapté n’est exporté ni ajouté au ZIP ; le lot de régression de 85 WAV réservé à cette étape n’est pas utilisé pour choisir un autre réglage.

Ce petit lot ne représente pas les spécialités médicales. Il contient seulement trois occurrences de fractions dans une même dictée et une négation d’instruction ; il ne valide pas les négations cliniques. Les temps mesurés sur Mac ne qualifient pas le délai sur Windows.

## Essais encore nécessaires

1. Essayer le même ZIP sur deux PC Windows physiques compatibles, dont un à 8 Go sans GPU dédié : installation, ouverture, micro, délai après les pauses, sauvegarde, fermeture et réouverture.
2. Dans des documents fictifs, vérifier Word, un éditeur Windows et les champs réellement utilisés dans le navigateur : insertion Unicode, raccourci, changement de champ, arrêt, restauration et absence de doublon. Les contrôles automatisés sur une page locale ne couvrent pas tous les logiciels métier.
3. Observer le redimensionnement, le clavier, le contraste élevé et les facteurs d’affichage 100–200 % sur un écran réel.
4. Faire relire de courtes dictées fictives par le médecin volontaire. Constituer des voix et des textes indépendants, avec annotation explicite des médicaments, doses, fractions, latéralités et négations avant tout nouvel entraînement.

Ces points restent des conditions d’évolution vers un pilote ; la préversion ne vaut pas validation en cabinet.
