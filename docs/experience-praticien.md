# NoteVive : expérience du praticien

**Proposition à éprouver en situation simulée.** Un praticien termine une consultation, dicte sa note, vérifie ce qui s’affiche, corrige puis retrouve ou transfère le texte. Il doit pouvoir reprendre après une interruption sans se demander si le micro écoute encore, si son texte a été sauvegardé ou dans quel dossier il risque d’écrire. Le scénario vient du besoin exprimé ; aucun entretien ni essai avec un praticien n’est revendiqué à ce stade.

Une seule application Windows et un seul parcours. La médecine générale en français est la première référence de validation. Les spécialités utilisent les mêmes écrans et les mêmes garanties, avec un profil de vocabulaire ou de mise en forme lorsqu’il est qualifié. Les lots P1 à P4 de la [feuille de route](feuille-de-route.md) organisent le travail et la vérification ; ils ne constituent pas des éditions différentes du produit.

## Les situations à couvrir

| Situation | Ce que la personne doit pouvoir faire | Vérification attendue |
| --- | --- | --- |
| Le patient est parti ; le prochain rendez-vous approche | Ouvrir une nouvelle note et dicter immédiatement. Commencer via un bouton ou un raccourci configurable. Aucun titre, profil ou classement imposé avant de parler. | En application ouverte et moteur prêt, la dictée démarre par une seule action depuis l’éditeur vide. À froid, « Préparation du moteur » est distinct de « Micro ouvert » ; aucune parole n’est présentée comme capturée avant l’ouverture réelle. Le focus reste prévisible et un second déclenchement accidentel ne crée pas une seconde session. |
| Le praticien voit un mot incorrect pendant qu’il parle | Lire le texte au fil de la dictée, repérer ce qui peut encore changer et corriger un passage déjà stabilisé. | Lors d’une correction à la souris ou au clavier, les révisions ne déplacent pas le curseur, ne changent pas la sélection et n’écrasent pas la modification. Le défilement automatique suit la fin seulement tant que l’utilisateur y reste. Retour explicite au direct en un geste. |
| Un collègue entre, un téléphone sonne ou le patient revient | Couper le micro et, si nécessaire, masquer la note sans devoir terminer la relecture. Revenir au même brouillon ensuite. | Depuis toute vue de NoteVive, un bouton clairement identifié arrête ; le raccourci d’arrêt fonctionne lorsque le panneau n’a pas le focus. Après verrouillage, veille, arrêt de capture ou action « Masquer », aucun redémarrage automatique et aucune reprise du transfert en attente. |
| Un microphone est débranché, le moteur est lent ou s’arrête | Savoir si la dictée est complète et retrouver ce qui a été sauvegardé. | Afficher la cause sous une forme utile (« Micro déconnecté », « Texte en retard », « Passage à redicter »). Garder le dernier texte stable sauvegardé, distinguer le fragment incomplet, et demander une reprise explicite. Ni trou audio, ni perte de texte présentés comme succès. |
| Les notes s’accumulent pendant la journée | Renommer ou classer après la dictée ; retrouver les brouillons et les notes relues, y compris deux notes portant le même titre. | La bibliothèque affiche par défaut titre, date et état sans extrait du contenu. Recherche locale, filtres par état/date/profil ou dossier, ordre récent. Renommer ou déplacer ne modifie ni le contenu ni la date de création ; le titre et la date ne servent pas de preuve d’identité patient. |
| Le praticien prépare une note pour le logiciel métier | Contrôler les passages à risque, relire la version exacte, puis décider d’un transfert vers une destination qualifiée. | Au moindre changement de dossier, d’onglet, de champ ou de session depuis la confirmation, conserver la note et annuler l’action. Aucune insertion des hypothèses provisoires ; aucun envoi ni validation dans le logiciel tiers. Une écriture incomplète n’est jamais rejouée automatiquement. |

## Écran et états

Maquette de discussion, en français. La commande primaire change avec l’état ; le libellé du micro reste présent dans l’éditeur et le panneau compact. La bibliothèque peut se replier sur petit écran. Aucun état ou avertissement ne repose sur la couleur seule.

```text
┌ NoteVive ────────────────────────────────────────────────────────────────┐
│ Nouvelle note      Bibliothèque                          Masquer la note │
├───────────────────────────┬───────────────────────────────────────────────┤
│ Rechercher les notes      │ Brouillon sans titre                         │
│ Aujourd’hui · Brouillons  │ Profil : Médecine générale                   │
│ 14:12  Brouillon          │ Micro ouvert · Micro du casque   [ Arrêter ] │
│ 13:58  Relue              │                                               │
│                           │ Texte stable, que je peux corriger…           │
│                           │ En cours : « ce passage peut changer… »      │
│                           │                                               │
│                           │ Brouillon sauvegardé à 14:12                   │
│                           │ [ Relire après l’arrêt ]                      │
└───────────────────────────┴───────────────────────────────────────────────┘

Panneau compact — Micro ouvert · Dossier externe non autorisé
Texte en cours…                             [ Arrêter ] [ Ouvrir la note ]
```

| État | Entrée et sortie autorisées |
| --- | --- |
| **Prêt · micro coupé** | Nouvelle note ou reprise explicite → `Préparation` si le moteur n’est pas prêt, sinon `En écoute` après ouverture réussie du périphérique. Aucun déclenchement par simple focus, ouverture de note ou démarrage du système. |
| **Préparation · micro coupé** | Modèle et audio prêts → `En écoute` si l’intention initiale est toujours valide. Annulation, masquage, verrouillage, changement de session ou erreur → `Prêt` ou `Interrompu`, sans démarrage retardé. |
| **En écoute · micro ouvert** | `Arrêter` coupe la capture puis ouvre `Finalisation`. Interruption, masquage ou verrouillage coupe le micro et désarme le transfert ; un passage incomplet est signalé. L’état correspond à la capture réelle, y compris si le moteur est en retard. |
| **Finalisation · micro coupé** | Le texte restant peut se stabiliser ; aucun nouveau son n’est capturé. En cas d’échec, afficher `Interrompu`. Un changement de note ne redirige jamais les résultats en attente vers la nouvelle note. |
| **À relire · micro coupé** | Correction, classement, reprise explicite de la dictée, ou `Marquer comme relue`. La mise en forme propose un résultat distinct comparé à la source ; elle ne modifie pas le brouillon seule. |
| **Relue · micro coupé** | Version de travail relue et sauvegardée. Une modification ou une nouvelle dictée crée une révision à relire, et invalide toute confirmation de transfert précédente. Un transfert réussi ne signifie pas que le dossier métier a été validé. |
| **Interrompu · micro coupé** | Afficher ce qui est disponible et, si connu, où la capture s’est arrêtée. Laisser éditer, redicter dans cette note ou créer une nouvelle note par action explicite. Aucun rattrapage caché de l’audio perdu. |

**Masqué ou verrouillé** est un état de confidentialité distinct. Le contenu, le titre de note et les aperçus disparaissent ; la dernière version stable reste dans le stockage autorisé. Après déverrouillage Windows, ouvrir la note exige une action locale ; micro et transfert restent coupés. Les notifications, aperçus, icônes et diagnostics ne montrent aucun contenu médical. Vérifier les miniatures de la barre des tâches et Alt+Tab ; un masquage d’application ne garantit pas la protection contre une photo ou un autre logiciel de capture. Le verrouillage de session et la configuration du poste restent des contrôles du cabinet. [Guide CNIL, sécurisation des postes](https://www.cnil.fr/fr/securite-securiser-les-postes-de-travail).

**Transfert** est une autorisation ponctuelle distincte : `Indisponible` → `Destination à confirmer` → tentative sur la version relue → `Transféré`, `Annulé` ou `À vérifier`. Afficher un libellé intelligible de la destination lorsque l’intégration sait la vérifier, dans la fenêtre ouverte par le praticien seulement. Si l’identité du dossier est indéterminée, `Indisponible` s’applique même si le champ paraît éditable. Un champ et une fenêtre Windows ne prouvent pas l’identité du dossier ; le produit ne crée pas de registre d’identités. [Architecture Windows et focus](architecture-windows.md), [référentiel national d’identitovigilance de l’ANS](https://esante.gouv.fr/identite-nationale-de-sante/referentiel-national-d-identitovigilance) pour le contexte métier, sans revendication de conformité de NoteVive.

## Clavier, voix et relecture

- **Clavier et souris.** Parcours complet au clavier, focus visible, ordre logique, raccourci visible et reconfigurable, retour à l’éditeur depuis le panneau. Afficher un conflit plutôt que remplacer une commande Windows ou métier. La fermeture du panneau par `Échap` ne doit jamais laisser le micro actif et invisible. Vérifier AZERTY, AltGr, zoom Windows, Narrateur, contraste et deux écrans. Les transitions de micro et erreurs sont annoncées ; les fragments provisoires n’interrompent pas la lecture à chaque mot. [Microsoft, vérifications d’accessibilité Windows](https://learn.microsoft.com/en-us/windows/apps/design/accessibility/accessibility-testing).
- **Voix.** La parole remplit le texte après une action physique. Évaluer des commandes documentaires bornées, par exemple retour à la ligne, dans un mode explicite avec retour visuel et annulation. En dictée ordinaire, prononcer « nouveau paragraphe », « arrêtez » ou « envoyer » doit conserver les mots si le mode commande est inactif. La voix ne démarre pas le micro, ne valide pas une note, ne supprime pas et ne transfère pas. Les commandes restent facultatives ; le parcours clavier est toujours disponible.
- **Relecture.** Distinguer trois signaux : hypothèse encore révisable, texte stable mais non relu, et texte relu par son auteur. Un éventuel repère « À vérifier » aide à retrouver une zone incertaine, sans donner l’impression que les passages non marqués sont fiables. Relire les noms et attributions, négations, valeurs, unités, fréquences et latéralité, en contexte. Les termes « pas de… » ou les passages entre guillemets ne peuvent déclencher des actions. Une mise en forme se compare à la source et se rejette en une action ; elle ne complète pas les valeurs manquantes. Par défaut, pas de réécoute persistante : redicter ou corriger si besoin. Voir [qualité médicale](qualite-medicale.md) et [données](donnees-et-usage.md).

## Les profils d’une application unique

| Sélection | Rôle | Règle d’interface et recette |
| --- | --- | --- |
| **Profil de pratique** | Choisit le vocabulaire proposé pour la dictée et, si qualifié, un gabarit documentaire local. | Choix visible sans étape imposée ; sélection explicite avant capture, mémorisée selon la préférence locale à valider. Pas de changement automatique selon les mots dictés ou le logiciel en avant-plan. Un changement s’applique à la prochaine session, jamais aux passages déjà relus. |
| **Gabarit de note** | Propose une présentation, par exemple texte libre ou rubriques non remplies. | Le gabarit ne remplit pas les absences, ne propose pas de diagnostic et ne change aucun chiffre. L’utilisateur peut passer en texte libre et revoir le résultat comparé à sa source. |

Une spécialité ajoutée réutilise installation, bibliothèque, raccourcis et règle de transfert ; elle a son propre lot lexical versionné et ses propres cas de validation. Un profil non qualifié est absent du parcours clinique. L’interface ne qualifie pas automatiquement une spécialité du seul fait qu’un terme est connu du modèle.

Le compromis entre délai, mémoire et fidélité se règle pendant les essais P0. À la livraison, le praticien dispose de la configuration de transcription qualifiée ; l’application explique une incompatibilité ou un retard sans changer de moteur pendant la dictée.

## Recette praticien proposée

Faire deux boucles courtes avec des praticiens et des cas fictifs. Première boucle sur maquette pour valider le vocabulaire d’écran, la visibilité du micro et l’ordre des gestes. Seconde boucle sur un poste qualifié, sans tutoriel sur les scénarios critiques. Faire rejouer ensuite les corrections par quelqu’un qui n’a pas conçu l’écran. Prévoir des profils clavier/souris et des praticiens avec et sans habitude de la dictée. Lorsque possible, reproduire la disposition et les interruptions du cabinet dans une session de démonstration autorisée. Ne collecter ni écran clinique, ni contenu patient ; une observation distingue ce qui a été vu de l’interprétation. [Méthode d’observation contextuelle, Service Manual](https://www.gov.uk/service-manual/user-research/contextual-research-and-observation).

**Démonstration de bout en bout, fictive et hors ligne.** Sur un compte de démonstration, ouvrir une note vide, dicter une vignette fictive, observer le provisoire, arrêter et corriger un mot. Enregistrer sous « Démo — note A », masquer, puis retrouver la note dans la bibliothèque. Depuis une version relue, présenter un éventuel transfert vers un formulaire local de démonstration et interrompre la confirmation en changeant de dossier. Si l’intégration n’est pas disponible, montrer son état indisponible ; le scénario principal aboutit quand même à une note relue et retrouvable. Aucun logiciel métier en production, compte patient, service réseau ou données réelles dans cette démonstration.

**Trois consignes, sans donner le chemin :** « Terminez cette note et retrouvez-la pour la prochaine visite fictive » (E1, E2, E4) ; « Interrompez-vous, puis reprenez ce qui était sauvegardé » (E3, E6) ; « Placez le texte relu dans le dossier de démonstration convenu » (E5, avec changement de contexte provoqué). En cas de blocage, laisser la personne expliquer ce qu’elle pense avoir fait avant de lui montrer le contrôle.

| Essai | Observer et consigner |
| --- | --- |
| **E1 — Première note sans aide** | Donner une consigne fictive, sans désigner le bouton. Mesurer temps jusqu’à micro ouvert, nombre de gestes, demandes d’aide et démarrages involontaires. À trois moments, demander « Le micro écoute-t-il ? » et comparer la réponse à l’état réel. |
| **E2 — Correction en cours de dictée** | Faire modifier une négation dans le texte stable pendant la révision du passage suivant. Observer si la correction et le curseur restent intacts et si la personne peut revenir au direct sans perdre son repère. |
| **E3 — Interruption inattendue** | Déclencher un appel fictif puis verrouiller la session, ou débrancher le micro. Vérifier coupure, masquage et absence de reprise automatique ; mesurer le temps pour retrouver la bonne note et demander ce qui a été conservé. Ajouter veille et plantage dans la recette technique. |
| **E4 — Relecture et classement** | Injecter dans une note fictive un chiffre, une latéralité ou une négation erronés. Observer si l’erreur est trouvée et corrigée ; compter reprises et erreurs résiduelles. Renommer, classer, fermer puis retrouver la bonne note parmi deux titres proches. |
| **E5 — Contexte externe ambigu** | Armer un transfert fictif vers un dossier A, puis afficher B dans le même champ du même logiciel, ou basculer d’onglet. Vérifier qu’aucun caractère n’est écrit, que le motif est compréhensible et que la note est récupérable sans redicter. Inclure un champ secret, un destinataire non local et une insertion partielle simulée. |
| **E6 — Profil, clavier et confidentialité** | Sélectionner un profil avant une dictée, revenir à la bibliothèque et fermer/masquer au clavier. Vérifier l’accès à toutes les commandes au Narrateur et à 200 % de mise à l’échelle, la distinction profil/réglage CPU et l’absence de texte dans les aperçus. |

Bloquer le passage en bêta pour tout micro ouvert sans indicateur, capture après un arrêt effectif, écrasement de correction, perte non signalée, mauvais dossier, transfert automatique ou erreur clinique critique reproductible sans mitigation. Pour le confort, comparer au même scénario fictif au clavier : temps entre fin de consultation simulée et note relue, part de tâches terminées sans aide et nombre de reprises. Alterner l’ordre des deux parcours pour limiter l’effet d’apprentissage. Fixer les cibles de confort après une première mesure de référence ; rapporter les effectifs et les échecs au lieu de déduire une efficacité clinique d’une petite session. Les seuils techniques de latence et de fidélité restent ceux de la [feuille de route](feuille-de-route.md).

Les premiers entretiens doivent éclairer quatre décisions : à quel moment le praticien dicte et devant qui ; comment il reconnaît et reprend la bonne note ; quel raccourci ou dispositif de bureau lui convient ; quels champs et formats de son logiciel métier justifient une intégration dédiée. Le cabinet décide des politiques de masquage, de conservation et de destination. Consigner les réponses dans le [registre](suivi.md) avant de figer les choix d’interface.
