# NoteVive : plan de progression vers un pilote médical

**Proposition de travail du 14 novembre 2026, à partir du paquet Windows 0.3.0.** Ce document décrit les travaux à réaliser et leurs conditions de réussite. Il ne déclare ni un entraînement effectué, ni de nouveaux scores, ni une autorisation d’usage clinique. Hakan indique pouvoir probablement solliciter un médecin généraliste ; sa participation reste à confirmer.

Le premier objectif recommandé est une dictée post-consultation de médecine générale, sur Windows, entièrement locale, avec relecture obligatoire. Les autres spécialités seront évaluées progressivement dans **la même application**. Une bibliothèque de mots transversale peut exister dès maintenant ; une promesse de fiabilité pour toutes les spécialités demande des preuves propres à chaque usage.

**Travaux réalisés depuis ce plan :** l’[audit de consolidation 0.3.1](audit-consolidation-031.md) décrit les correctifs Windows, le correctif amont du décodeur, la comparaison appariée et la préparation effective d’un corpus humain. Les poids n’ont pas été entraînés ; le mode d’essai guidé F1 et la qualification clinique restent des travaux à réaliser.

## 1. Notre point de départ réel

Le produit Windows utilise Whisper Large-v3 Turbo Q5_0, whisper.cpp 1.8.5, OpenBLAS et Silero. Le code décode aujourd’hui les fragments en français, sans réutiliser le contexte des notes précédentes, avec une recherche simple et quatre fils de calcul. Le prototype Mac utilise UltiMed INT8 ; ses résultats ne qualifient pas le produit Windows.

Trois constats guident la suite :

- **Le vocabulaire seul n’a pas résolu les erreurs.** Dans l’[essai apparié Mac](../p0/lexicon_macos.md), les 32 mêmes fichiers ont produit les mêmes textes sans lexique, avec une liste courte et avec le catalogue admissible complet : 25/66 mentions lexicales et 46/64 attributs critiques reconnus. Cela démontre l’absence de gain de cette intégration sur ce lot, pas l’inutilité de toute méthode de contextualisation.
- **Le découpage change la fidélité.** Sur les 32 cas difficiles du [comparatif](../p0/asr_benchmark.md), le candidat Turbo aux pauses reconnaît 22/26 éléments de dose ou unité, 8/8 fractions et 15/22 négations strictes. Allonger la pause à 1 216 ms fait notamment régresser les fractions à 5/8. Un échec du score de négation peut être une différence de formulation ; les sorties doivent être relues pour distinguer cette différence d’une inversion de sens.
- **La cible matérielle reste à vérifier.** Les [tests Windows](p0-choix-moteur.md) passent sur des machines virtuelles mais restent lents. La latence réelle à l’écran et la tenue sur un PC physique de 8 Go ne sont pas établies. Un bon résultat sur le Mac ne suffit pas.

Les 89 fichiers déjà comparés servent désormais au développement et à la non-régression. Puisqu’ils ont servi à choisir le moteur et ses réglages, ils ne constituent pas une confirmation finale indépendante.

## 2. Qui fait quoi ?

| Participant | Rôle proposé | Ce qui ne lui est pas demandé |
| --- | --- | --- |
| **Hakan** | Ouvrir les paquets préparés, lire quelques phrases fictives, décrire les difficultés, solliciter le généraliste et faciliter l’accès aux deux PC. Arbitrer les compromis de confort à partir de résultats lisibles. | Programmer, lancer des commandes, installer Python, régler les modèles ou juger seul la justesse médicale. |
| **Assistant de développement** | Préparer les scénarios, le mode d’essai, les corpus et les rapports ; modifier le code ; comparer les configurations ; organiser une vérification distincte de l’implémentation ; documenter et préparer les paquets. Travail effectué dans les sessions avec les outils et machines accessibles. | Se substituer à un médecin, certifier la sécurité clinique ou promettre des résultats sur un poste inaccessible. |
| **Généraliste volontaire, à confirmer** | Valider le réalisme et les formulations, relire les erreurs et essayer le parcours de dictée/correction. Aider à classer les erreurs par gravité. | Comprendre les outils de développement, annoter seul un énorme corpus ou valider les autres spécialités. |
| **Intervenant compétent avant données réelles** | Revoir le périmètre professionnel, les mesures de protection, les obligations applicables et le dispositif du pilote avec le cabinet. | Donner une approbation sur la seule base d’un score de transcription. |

Pour démarrer, proposer à Hakan des séances de **15 à 20 minutes**, et au généraliste deux séances de **30 à 45 minutes** : cadrage des usages, puis revue d’un premier résultat. Ce sont des formats de participation suggérés, pas une estimation de tout le travail nécessaire à un pilote.

## 3. Premier cycle : rendre les erreurs observables sans compétence technique

### F1 — Préparer un essai guidé

**À développer ; absent du ZIP actuel.** Un mode d’essai dans NoteVive présentera une phrase fictive, les boutons « Enregistrer l’essai », « Réécouter » et « Signaler une différence », puis un bilan simple. L’application affichera le micro choisi et un indicateur de niveau. Hakan n’aura pas à manipuler des WAV ou des scripts.

Dans ce mode explicitement activé, l’audio fictif pourra être conservé localement pour rejouer exactement le même son. La référence doit décrire ce qui a réellement été prononcé : si le lecteur saute un mot, le texte de la consigne n’est plus une référence exacte. Le mode ordinaire conservera son absence de sauvegarde audio par défaut. Aucun enregistrement patient ni envoi automatique à ChatGPT ou GitHub ne sera utilisé pour cette collecte.

**Premier exercice proposé : 20 dictées courtes.** Répartir les cas entre notes courantes, médicaments dans une phrase, nombres/fractions/unités et négations/latéralité. Ajouter quelques bruits et silences séparés. Ce lot sert à diagnostiquer les erreurs, pas à annoncer une fiabilité clinique.

**Preuve attendue :** le même fichier est rejouable, la référence est relue, les états du micro sont visibles et un arrêt ou une panne ne perd pas les notes déjà sauvegardées.

### F2 — Construire un petit corpus humain, puis réserver une confirmation

Après le premier diagnostic, viser un premier corpus de l’ordre de **60 à 100 prises courtes**, avec plusieurs voix, dont celle du généraliste si sa participation se confirme. Ce volume est une taille de départ pour explorer les défauts, pas un volume suffisant pour couvrir la médecine générale. Les personnes enregistrées doivent accepter l’usage de leurs prises pour les essais prévus.

Inclure des notes réalistes, des reformulations naturelles, des hésitations, des sigles, des termes fréquents et des mots rares. Les longues phrases artificiellement difficiles complètent ce corpus ; elles ne représentent pas à elles seules le travail quotidien d’un médecin. Annoter notamment :

- Le médicament et sa force commerciale, puis séparément la quantité administrée, l’unité, la voie, la fréquence et la durée lorsqu’elles sont dites.
- L’association entre les bonnes valeurs et le bon médicament, notamment lorsque deux traitements figurent dans une note.
- La négation et sa portée, la latéralité, les allergies, la temporalité, l’hypothèse versus l’affirmation.
- Les substitutions, omissions et ajouts, y compris les termes médicaux plausibles mais absents du son.

Séparer **avant réglage** les prises de développement et celles de confirmation. La confirmation utilise des formulations et des locuteurs non utilisés pour régler ou entraîner le candidat ; des prises répétées d’une même personne ne créent pas de nouveaux locuteurs. Si cette diversité n’est pas encore accessible, le résultat reste exploratoire. Une confirmation ouverte pour corriger le modèle ne reste pas ensuite un test inédit : préparer une nouvelle réserve.

L’assistant prépare l’annotation ; le praticien revoit les passages médicaux et les ambiguïtés à partir du son. Les données de synthèse complètent les cas de stress mais ne remplacent pas cette évaluation humaine.

**Preuve attendue :** manifeste des fichiers et de leurs droits, références corrigées, séparation des lots, classement des erreurs et mesure initiale reproductible.

## 4. Améliorer d’abord ce que nous pouvons maîtriser sans réentraîner

### F3 — Corriger la capture et la coupure des phrases

Examiner les passages ratés pour savoir si le moteur reçoit toute la parole : début de mot coupé, silence dans un nom composé, unité séparée de sa valeur, fin de phrase manquante. Mesurer le niveau du micro, l’écrêtage et les changements de périphérique. Un nettoyage audio agressif peut aussi dégrader la reconnaissance ; conserver un témoin sans ce traitement.

Tester au banc une modification à la fois : marges avant/après parole, regroupement de fragments ou chevauchement contrôlé. Ne pas réappliquer arbitrairement la pause longue déjà en échec. En cas de chevauchement, vérifier aussi les répétitions de mots et de doses.

Un essai de reconnaissance d’une phrase plus complète peut être pertinent si la précision progresse. Une éventuelle deuxième lecture utilisera d’abord le **même modèle**, seulement dans le banc, et son coût sera mesuré. Elle ne doit jamais réécrire silencieusement du texte corrigé ou validé. Sur 8 Go, doubler le calcul peut être incompatible avec l’usage : cette piste peut être abandonnée.

**Preuve attendue :** réduction des défauts de segmentation sur le même son, sans nouvelle omission, duplication ou perte critique, avec mesure du délai supplémentaire.

### F4 — Tester une petite aide lexicale qui agit réellement sur le moteur

Conserver les grands catalogues locaux et leurs sources. Séparer leur fonction de consultation de la petite sélection transmise à la reconnaissance. Le catalogue Mac comporte déjà 14 profils de 6 222 à 10 000 entrées, avec des chevauchements ; ces effectifs ne signifient pas que le modèle sait reconnaître chaque entrée.

Pour Whisper, tester un contexte court par pratique, puis éventuellement quelques favoris choisis explicitement. Le SDK [whisper.cpp 1.8.5](https://github.com/ggml-org/whisper.cpp/blob/v1.8.5/include/whisper.h) expose une amorce textuelle et une recherche parmi plusieurs hypothèses ; le contexte est borné. Vérifier le nombre de jetons du modèle exact, la réapplication de l’amorce et la remise à zéro entre dictées. Une liste de milliers de mots ne rentre pas dans ce mécanisme.

Comparer séparément : référence sans aide, recherche parmi plusieurs hypothèses sans aide, puis même recherche avec une courte sélection. Cette séparation évite d’attribuer au lexique un effet dû au décodeur. Commencer par quelques termes utiles, pas par tout un profil. La liste est préparée indépendamment des références de test. Ne jamais donner au moteur la phrase attendue.

Ajouter des contre-exemples où les termes proposés ne sont pas prononcés, où un autre médicament est dit, et où le profil ne correspond pas à la dictée. Ne pas injecter de doses, de négations ou de valeurs attendues dans l’amorce. Un médicament plausible mais inventé est un échec, même si les autres mots sont mieux orthographiés.

Les corrections manuelles peuvent alimenter une liste personnelle **après acceptation explicite** ; elles ne deviennent pas un apprentissage automatique. Un changement éditorial de la note n’est pas nécessairement une erreur de reconnaissance.

**Preuve attendue :** gain sur les termes de nouvelles dictées, effet réel du mécanisme vérifié, absence de régression critique observée et coût CPU compatible. Si aucun gain n’apparaît, garder le catalogue en consultation et abandonner ce réglage.

### F5 — Comparer les moteurs et la vitesse sur les PC cibles

Whisper Turbo reste le témoin Windows. UltiMed reste un comparateur intéressant pour le vocabulaire, sans oublier les erreurs numériques déjà observées. La [fiche d’UltiMed](https://huggingface.co/Olicorne/parakeet-tdt-0.6b-v3-ultra-UltiMed-onnx) publie ses limites et prévoit une révision entraînable ; ses résultats d’auteur ne remplacent pas nos mesures.

Évaluer CTranslate2/faster-whisper comme une autre manière d’exécuter Whisper, pas comme un modèle automatiquement meilleur. Le [projet officiel](https://github.com/SYSTRAN/faster-whisper) prend en charge le CPU INT8. Notre comparaison Windows a rencontré un échec de fractions sur un run : l’expliquer et le rejouer avant toute substitution. Une optimisation de quantification, de moteur ou de recherche doit repasser les mêmes contrôles de fidélité.

Faire les comparaisons sur le même PC, les mêmes audios et un nombre de fils comparable, avec ordre alterné, démarrage froid séparé et modèle préchauffé. Mesurer le vrai parcours micro → pause → texte visible, ainsi que la mémoire totale de l’application et du moteur. Ne pas confondre vitesse d’un fichier traité en accéléré et délai ressenti pendant une dictée.

**Deux postes physiques requis pour conclure sur Windows :** un PC de 8 Go compatible avec le paquet et un second poste représentatif. L’assistant prépare des essais lançables simplement et le rapport ; une personne devant chaque PC réalise les gestes. Le Mac reste utile pour développer et préparer les enregistrements.

**Preuve attendue :** compromis qualité/vitesse documenté sur les deux postes. S’il est impossible de tenir les objectifs avec le matériel minimal, proposer explicitement à Hakan de revoir le délai acceptable, le minimum matériel ou le périmètre. Ne pas déplacer les seuils discrètement. Une seule configuration retenue est intégrée dans le paquet utilisateur.

## 5. Entraîner uniquement si un manque précis subsiste

### F6 — Faire un petit essai d’adaptation des poids

Une liste de mots peut servir à construire des exemples et un contexte lexical. Pour apprendre à mieux reconnaître la parole, il faut des **enregistrements accompagnés de leur transcription exacte**. Lire quelques mots peut aider à diagnostiquer une prononciation ; cela ne produit pas instantanément un modèle médical général.

Si les étapes précédentes laissent des erreurs systématiques, monter un essai limité sur une famille d’erreurs identifiée. Préparer un sous-ensemble autorisé, des voix variées, des notes courantes de contrôle et une validation humaine indépendante. Étudier une courbe d’apprentissage avec des volumes croissants : il n’existe pas de nombre d’heures que nous puissions promettre suffisant pour toutes les spécialités.

La documentation [Hugging Face PEFT](https://huggingface.co/docs/peft/main/task_guides/int8-asr) fournit un exemple d’adaptation de Whisper par LoRA, méthode qui entraîne un ensemble restreint de paramètres. Cet exemple porte sur Whisper large-v2 ; la compatibilité exacte avec Turbo, l’export puis la quantification de notre candidat doivent être prouvés. Le fichier GGML Q5_0 distribué n’est pas directement le point de départ de cet entraînement. La voie UltiMed part de son checkpoint NeMo, puis doit être exportée et réévaluée dans notre runtime.

L’assistant peut préparer le code, contrôler les données et analyser les résultats. Il faut néanmoins un calculateur adapté, en pratique une machine disposant d’un GPU compatible pour ce type d’essai. Ce travail n’est pas à imposer aux PC des médecins. Pour rester dans le périmètre local, privilégier une machine dédiée accessible ou prêtée ; aucune location, prestation ni transmission de données à un service distant n’est engagée par ce plan. Un besoin de budget devra être chiffré puis décidé.

Ressources à réutiliser avec séparation stricte des usages :

| Ressource | Usage envisagé et limite |
| --- | --- |
| Enregistrements fictifs volontaires | Première source pour nos erreurs réelles ; accord des participants, référence relue et distinction entraînement/validation. |
| [PxCorpus v4](https://zenodo.org/records/10080490) | Prescriptions simulées en français avec audio et annotations, sous CC BY 4.0. Utile pour élargir les voix ; conserver les attributions et séparer les locuteurs. Les prises déjà utilisées au benchmark ne redeviennent pas une validation inédite. |
| [UltiMed-ASR-FR-v1](https://huggingface.co/datasets/Olicorne/UltiMed-ASR-FR-v1) | Sélectionner les sous-ensembles compatibles avec l’usage prévu ; le corpus principal est synthétique et monovoix. Le sous-ensemble PARROT a une licence distincte et reste exclu de notre entraînement produit. Ne pas télécharger tout le corpus pour démarrer. |
| [Corti Med-Dictate](https://huggingface.co/datasets/corti/med-dictate/blob/main/LICENCE.md) | Réservé aux usages d’évaluation autorisés par sa licence. Aucun entraînement, adaptation, distillation ou utilisation comme signal d’entraînement. Les données et erreurs de ce lot ne doivent pas alimenter notre corpus d’ajustement. |
| Référentiels de vocabulaire | Poursuivre les sources déjà documentées : Orphanet, HPO, CCAM, NABM, EMDN, CISP et Medic’AM. Exemple : [la CCAM publiée par l’ANS](https://smt.esante.gouv.fr/terminologie-ccam/) précise sa version et sa licence. Une disponibilité en ligne ne vaut pas autorisation de tous les usages. La BDPM reste exclue du paquet public actuel. |

**Preuve attendue :** amélioration confirmée sur des voix et formulations inédites, maintien du français courant, des doses et négations, puis reproduction après export et quantification. Sans gain suffisant, conserver le modèle de référence. La synthèse vocale produite pour entraîner ne sert pas à elle seule à valider le résultat.

## 6. Réduire le risque d’une erreur restante dans l’interface

### F7 — Aider la relecture et vérifier le gain de temps

Faire évoluer l’interface pour distinguer brouillon, corrections et note validée. Mettre en évidence les nombres, unités, médicaments, côtés du corps et expressions négatives afin de guider la relecture. Proposer un terme du catalogue comme suggestion séparée, avec acceptation explicite. Ne pas remplacer automatiquement un médicament par un nom ressemblant ni demander à un modèle génératif de « corriger médicalement » la note.

Cette aide n’est pas un détecteur infaillible : une négation supprimée ne figure plus dans le texte à surligner. Un score de confiance n’est pas une probabilité clinique validée et une phrase fluide peut être fausse. La relecture complète reste nécessaire. Étudier une réécoute locale du dernier passage à durée limitée, avec décision explicite sur la conservation et les traces possibles ; ne pas ajouter silencieusement un enregistrement permanent.

Tester avec le praticien des tâches fictives comparables : saisie manuelle, puis dictée et correction, en alternant l’ordre. Mesurer le temps jusqu’à une note correcte et validée, le nombre d’erreurs avant/après relecture et les manipulations nécessaires. Une transcription plus rapide qui demande beaucoup de corrections peut être moins utile.

**Preuve attendue :** le praticien repère et corrige les erreurs, aucune correction validée n’est écrasée, la note revient après relance et le gain de temps subsiste après relecture. Une amélioration du moteur et une meilleure détection par l’utilisateur sont deux résultats distincts.

## 7. Conditions avant un pilote avec de vraies données

### F8 — Confirmer sur Windows et préparer l’exploitation

Geler le candidat, les lexiques, le protocole et les seuils avant d’ouvrir la confirmation. Les [objectifs existants du projet](feuille-de-route.md#critères-mesurables-proposés) restent des objectifs d’ingénierie, à revoir avec le praticien ; ils ne sont pas une certification :

| Dimension | Preuve à rechercher |
| --- | --- |
| Fidélité | Objectifs initiaux WER normalisé ≤ 12 % et exactitude des attributs critiques ≥ 98 %, avec au moins 200 attributs de confirmation annotés. Ajouter le contrôle des associations, des omissions et des ajouts, et les résultats par catégorie et locuteur. Le score global ne masque aucun défaut critique. |
| Relecture | Aucune erreur critique résiduelle observée après la revue des scénarios simulés ; tout défaut critique reproductible sans mitigation bloque le pilote. L’effectif et l’incertitude sont publiés : zéro erreur observée ne prouve pas un risque nul. |
| Délais et charge | Les objectifs initiaux de rendu après pause ≤ 2 s au P95, de facteur temps réel ≤ 0,8 et de mémoire privée cumulée ≤ 2 Go restent à mesurer sur le PC plancher. Tout compromis différent nécessite une décision explicite. |
| Utilité | Objectif initial d’au moins 20 % de temps gagné jusqu’à la note validée, correction comprise, sur des tâches comparables. Aucun résultat de ce type n’est actuellement acquis. |
| Robustesse | Installation hors ligne sur poste propre, trois dictées de 15 minutes, micro débranché, veille, fermeture, mise à jour, reprise après panne et absence de perte des notes confirmées. |
| Exploitation | Application signée, sauvegarde chiffrée et restauration testée sur un autre poste, suppression et conservation définies, support documenté, contrôles réseau et journaux sans contenu patient. |
| Destination du texte | Parcours de validation puis transfert explicite vers une destination qualifiée. L’export et l’insertion externe ne sont pas présents dans le ZIP actuel ; leur intégration constitue un travail distinct. |

Les notes actuelles sont liées au compte Windows et au poste par DPAPI : recopier leur dossier ne suffit pas à démontrer une sauvegarde restaurable ailleurs. Ce point, les droits d’accès et la protection du poste doivent être traités avant l’usage professionnel.

Le fonctionnement local n’annule pas les obligations sur les données de santé. La [CNIL](https://www.cnil.fr/fr/rgpd-et-professionnels-de-sante-liberaux-ce-que-vous-devez-savoir) rappelle le cadre applicable aux professionnels libéraux. Le cabinet et un référent compétent doivent revoir la finalité, les responsabilités, la sécurité, la conservation et les exigences liées aux fonctions réellement revendiquées. Le [cadrage du projet](donnees-et-usage.md) précise les points ouverts. La première évaluation avec le médecin reste fictive ; le passage à des données réelles demande une décision distincte et documentée.

Pour chaque spécialité supplémentaire, reprendre la même boucle avec un relecteur du domaine, ses types de notes et ses confusions. Un succès en médecine générale ne qualifie ni l’oncologie, ni la génétique, ni les différentes chirurgies.

## 8. Ordre de travail et suivi compréhensible

| Ordre | Livrable à préparer | Décision de passage |
| --- | --- | --- |
| 1 | Mode d’essai guidé, 20 scénarios et première séance de 15–20 min | Les problèmes sont enregistrés et reproductibles. |
| 2 | Revue avec le généraliste, corpus élargi et réserve indépendante | Les références sont fiables et les erreurs prioritaires identifiées. |
| 3 | Comparaisons ciblées capture/découpage/décodeur/lexique | Garder seulement les gains reproductibles, sans nouvelle régression critique. |
| 4 | Essais simples au micro sur les deux PC Windows | Compromis matériel, précision et délai acceptable démontré ou explicitement révisé. |
| 5, si nécessaire | Petit entraînement ciblé et contrôle après export | Le gain justifie le coût ; sinon, retour au modèle témoin. |
| 6 | Relecture assistée et tâches simulées avec le médecin | La note validée est correcte et le travail est réellement facilité. |
| 7 | Confirmation gelée, exploitation et revue du pilote | Décision documentée avant toute donnée patient réelle. |

Capture, préparation du lexique, interface et documentation peuvent avancer en parallèle. Les mesures de vitesse lourdes se font l’une après l’autre sur un même poste. Le développement et la vérification du code doivent être relus séparément ; les agents de test ne remplacent pas la relecture métier.

Chaque boucle fournit une fiche courte : **ce qui a changé, mêmes audios rejoués, erreurs corrigées, nouvelles erreurs, temps et mémoire, décision garder/rejeter, prochaine action**. Le détail technique et les empreintes restent disponibles dans le rapport. Les données de voix et les résultats individuels restent locaux ; le dépôt public reçoit le code, la documentation et les agrégats autorisés.

Les étapes sont ordonnées par preuves plutôt que par une date de sortie inventée. Sans médecin disponible, nous pouvons avancer sur les outils, les données fictives et le diagnostic. Sans PC Windows accessible, nous ne pouvons pas conclure sur sa performance. Sans matériel d’entraînement adapté, nous pouvons préparer un essai mais pas annoncer son résultat.

**Première action recommandée : préparer F1 et les 20 scénarios, puis recueillir le premier lot reproductible avant de changer de moteur.** Hakan n’aura aucun réglage technique à choisir pour cet essai.

## Sources et cadre de travail

Les mesures proviennent des rapports du dépôt liés dans ce document. Les capacités amont et licences citées ont été consultées le 14 novembre 2026 ; elles devront être figées par révision pour une expérience exécutable. Les nombres de séances et volumes de collecte proposés ne sont pas des résultats mesurés.

Le cadre Dev Toolkit Orchestrator sert à organiser le travail. Les capacités documentées de [Ponytail](https://github.com/DietrichGebert/ponytail) et [i-have-adhd](https://github.com/ayghri/i-have-adhd) concernent l’assistance au développement et la présentation des réponses ; elles n’améliorent pas directement la reconnaissance médicale. Aucun nouvel outil externe n’a été installé pour ce plan. Les outils du dépôt et les connecteurs existants suffisent à cette phase de cadrage.
