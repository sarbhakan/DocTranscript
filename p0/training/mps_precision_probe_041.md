# Contrôle mécanique FP32 sur Metal

Sur une même phrase fictive hors grille, Whisper Large-v3 Turbo termine en FP32 sur le Mac M1 Pro et restitue les **9 mots normalisés**. Les deux essais FP16 historiques sans adaptateur répétaient chacun le même jeton 444 fois sans atteindre le marqueur de fin. Ce contrôle isole une différence entre les deux routes de précision sur un cas. Il n’identifie pas la primitive en cause.

Le [protocole et les mesures agrégées](mps_precision_probe_041.json) conservent les empreintes du gel, de l’audio et des résultats. Avec PyTorch 2.9.1 et Transformers 4.57.3, les deux expériences utilisent les mêmes poids d’origine, le même PCM de 3,09 s, la même extraction mel, le même masque de 309 trames, la même graine, le même préfixe français et les mêmes réglages de suppression de jetons et de cache. Aucun contexte lexical, adaptateur ou repli CPU. Le passage FP32 désactive l’autocast FP16 ; il n’y a eu qu’un seul nouveau décodage, dans un processus distinct des essais historiques.

| Observation | FP16/MPS historique, sans adaptateur | FP32/MPS, sans adaptateur |
| --- | --- | --- |
| Fin de transcription | 0/2 | 1/1 |
| Jetons générés | 444 répétitions du même identifiant par essai | 14 identifiants distincts, fin comprise |
| Mots reconnus sur la phrase fictive | Sorties répétitives inexploitables | 9/9 après normalisation |

Sur FP32, la génération prend **4,79 s**, et tout le contrôle **35,22 s**, chargement et vérifications compris. Le pilote déclare 5,03 Go alloués après le diagnostic ; cette valeur n’est pas un pic. Le minimum observé de mémoire système libre estimée est de 22 %, contre 58 % au départ. Un calcul séparé après la génération confirme que les **51 866 logits FP32** à la dernière position du préfixe sont finis. Il ne mesure pas tous les pas du décodage et aucun logit FP16 comparable n’a été enregistré. Les durées des deux routes ne sont pas comparables : la route FP16 épuisait le budget de jetons.

Ce résultat concerne une phrase synthétique non médicale. Il ne valide pas les dictées médicales ni les compléments précédemment invalides, ne change pas le classement des adaptateurs et ne mesure pas le moteur quantifié livré sur Windows. Aucun modèle, poids ou réglage du produit n’a changé.
