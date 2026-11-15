# 33 dictées fictives pour vérifier les erreurs critiques

Ces phrases servent à tester NoteVive. Ce sont des scripts artificiels, pas des prescriptions à appliquer. Ils n'ont pas encore été relus par un médecin ni enregistrés pour une comparaison des moteurs. Les noms « médicament Alpha » et « médicament Bêta » sont des noms fictifs utilisés pour tester les nombres.

## Faire un premier essai

1. Créer une note intitulée « Test fictif — date — moteur/version ». Choisir quelques phrases ci-dessous.
2. Dicter à un débit naturel, en prononçant les nombres et les unités en toutes lettres. Marquer une courte pause aux points-virgules.
3. Arrêter la dictée et comparer le texte mot à mot avec la phrase réellement prononcée. Vérifier d'abord le médicament, la valeur, l'unité, la fraction, le moment de prise et la négation.
4. Garder le texte initial et noter les corrections séparément. Si un mot a été lu différemment du script, le signaler : le modèle doit être évalué sur ce qui a été dit.
5. Fermer puis rouvrir NoteVive pour vérifier la sauvegarde. Pour comparer deux moteurs, il faudra leur faire lire le même enregistrement local ; répéter une phrase au micro produit un autre son et ne constitue pas une comparaison contrôlée.

Le [protocole technique](../p0/training/critical_protocol_v2.md) distingue les tests du scoreur, les enregistrements et les mesures ASR. Le [panel source](../p0/training/critical_scenarios_v2.json) contient les annotations et des erreurs volontairement injectées pour vérifier les contrôles.

## Fractions et horaires

- **fraction-01** — 1 quart de comprimé matin et 1 demi de comprimé soir.
- **fraction-02** — 1 demi de comprimé matin et 1 quart de comprimé soir.
- **fraction-03** — 3 quarts de comprimé midi et 1 demi de comprimé soir.
- **fraction-04** — 1 demi de comprimé midi et 3 quarts de comprimé soir.
- **fraction-05** — 1 quart de comprimé matin et 3 quarts de comprimé midi.
- **fraction-06** — 3 quarts de comprimé matin et 1 quart de comprimé soir.
- **fraction-07** — 1 demi de comprimé soir et 1 quart de comprimé matin.
- **fraction-08** — 1 quart de comprimé soir et 1 demi de comprimé midi.
## Négations et concepts médicaux

- **negation-01** — pas de fièvre ; toux présente.
- **negation-02** — absence de dyspnée ; douleur thoracique présente.
- **negation-03** — aucun déficit moteur à droite ; paresthésie à gauche.
- **negation-04** — pas d'hémoptysie ; épistaxis rapportée.
- **negation-05** — ne présente pas d'aphasie ; dysarthrie décrite.
- **negation-06** — syndrome de Guillain-Barré exclu ; myasthénie suspectée.
- **negation-07** — pneumothorax absent ; épanchement pleural présent.
- **negation-08** — pas de récidive de purpura thrombotique thrombocytopénique ; fatigue présente.
## Côté et localisation

- **lateralite-01** — douleur à la cheville gauche ; œdème à la cheville droite.
- **lateralite-02** — paresthésie à gauche ; parésie à droite.
- **lateralite-03** — hypoacousie droite ; acouphène gauche.
- **lateralite-04** — ventricule gauche dilaté ; ventricule droit normal.
- **lateralite-05** — veine jugulaire interne gauche thrombosée ; veine jugulaire interne droite perméable.
- **lateralite-06** — lombosciatalgie droite ; cruralgie gauche.
- **lateralite-07** — ptosis unilatéral ; strabisme bilatéral.
- **lateralite-08** — déficit ipsilatéral ; atteinte controlatérale.
## Association entre médicament et dose

- **association-01** — médicament Alpha 20 mg ; médicament Bêta 40 mg.
- **association-02** — médicament Alpha 20 mg puis médicament Alpha 40 mg.
- **association-03** — médicament Alpha LP 600 mg.
## Médicaments proches à distinguer

- **lexique-01** — amiodarone et dronédarone.
- **lexique-02** — hydroxyzine puis hydralazine.
- **lexique-03** — lévétiracétam et lamotrigine.
## Unités

- **unite-01** — médicament Alpha 20 microgrammes.
## Valeur simple — contrôle des concentrations ajoutées

- **denominateur-01** — médicament Alpha 20 mg.

## Concentrations et dénominateurs

- **concentration-01** — médicament Alpha 20 mg par kg ; médicament Bêta 40 mg par ml.

Les références ci-dessus sont publiques. Elles aident à trouver des erreurs, mais ne constituent pas un jeu secret démontrant la généralisation à de nouveaux médecins ou à des données de patients.

