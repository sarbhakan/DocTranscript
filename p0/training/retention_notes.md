# Adaptation LoRA courte : essai de rétention

Le plan versionné dans `retention_experiment_plan.json` compare deux entraînements de 50 mises à jour sur les mêmes 200 clips de PxCorpus : entropie croisée (CE), puis CE avec une pénalité KL de 0,35 vers les distributions du modèle de base gelé. La pénalité compare les distributions sur les jetons lexicaux et le marqueur de fin, sans inclure le préfixe forcé ni le remplissage. Elle utilise les références d’entraînement pendant l’apprentissage ; aucune référence n’est fournie à la génération d’évaluation. Aucun clip de la réserve de 85 n’a servi à choisir ou à évaluer un réglage.

Le bras CE s’est terminé. Le bras KL a été interrompu par une perte non finie, après deux mises à jour, sur le Mac de l’essai (PyTorch 2.9.1, MPS, FP16). Aucun point de reprise KL n’a été produit ni utilisé. Des répétitions courtes ont reproduit des sorties non finies côté étudiant, alors que les sorties enseignant étaient finies. Cela se reproduit avec un décodeur enseignant séparé et figé. L’observation ne suffit pas à attribuer l’erreur à un noyau d’optimisation, à une précision particulière ou à MPS en général. Le chemin de recherche reste désactivé par défaut (`--retention-weight 0`) et le script refuse désormais d’enregistrer des poids d’adaptateur non finis.

L’évaluation du seul bras terminé compare base et CE sur les mêmes clips : 32 clips historiques et 64 autres clips de validation. Les deux fenêtres sont disjointes, mais viennent du développement et des mêmes huit voix. La grille et les sélections ont été figées avant toute génération de cet essai. La dernière révision de la grille a ajouté un test de concentrations après un contre-exemple synthétique, toujours avant génération et sans changer les clips ni leurs références. L’interruption empêche de conclure sur l’efficacité relative de la rétention KL. Un résultat CE descriptif ne rend pas son adaptateur éligible à la livraison.

| Mesure appariée | 32 historiques : base → CE | 64 supplémentaires : base → CE |
| --- | ---: | ---: |
| Erreurs de mots | 80/371 → 73/371 | 172/738 → 158/738 |
| Noms de médicaments reconnus | 8/24 → 8/24 | 16/49 → 18/49 |
| Doses reconnues | 42/46 → 41/46 | 82/97 → 83/97 |
| Fractions reconnues | 3/3 → 3/3 | 7/8 → 8/8 |
| Associations médicament–dosage reconnues | 5/16 → 5/16 | 9/25 → 10/25 |
| Temps cumulé de génération MPS | 42,55 s → 42,47 s | 85,94 s → 86,30 s |

CE perd au moins un contrôle critique sur 3 clips historiques et 2 clips supplémentaires. Sur les 64, il gagne trois noms de médicaments et en perd un ; le total seul masque cette perte. Aucun candidat n’est retenu. Les 96 sorties de chaque méthode comportent un jeton de fin. Les temps mesurent une génération appariée sur Mac avec le modèle de recherche, pas la latence de dictée de NoteVive sur Windows.

La comparaison ne qualifie ni les voix nouvelles, ni les négations cliniques (absentes de ces deux fenêtres), ni le paquet Windows quantifié. Il n’y a ni conversion, ni export, ni changement du modèle distribué. Les poids, prédictions, grilles et traces par clip restent dans l’archive locale ignorée par Git. Le rapport agrégé ne contient aucune transcription, seulement des comptes, des mesures et des empreintes d’intégrité.
