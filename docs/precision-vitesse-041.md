# Précision médicale et vitesse — expérience du 15 novembre 2026

Ce lot poursuit l'amélioration de NoteVive à partir de la version 0.4.0. Un essai d'entraînement, un contrôle de fidélité et un benchmark Windows sont trois preuves distinctes. Aucun score d'entraînement ne suffit à remplacer le modèle distribué.

## Questions testées et limites fixées avant les résultats

1. **Limiter les nouvelles erreurs pendant l'adaptation.** Comparer deux adaptateurs LoRA initialisés à neuf, avec les mêmes 200 clips d'entraînement et 50 mises à jour : l'objectif historique de prédiction des mots, puis ce même objectif auquel s'ajoute une pénalité KL de 0,35 vers le modèle d'origine gelé. Les paramètres, l'ordre des exemples et la graine sont identiques. La pénalité est une hypothèse à tester, pas une garantie de conservation des doses.
2. **Mesurer les pertes autant que les gains.** Réévaluer les 32 extraits historiques séparément de 64 autres extraits de validation choisis de façon déterministe avant leurs prédictions. Ces 64 extraits utilisent les mêmes huit voix de validation : ils élargissent le développement, mais ne sont pas une confirmation indépendante. Aucun réglage supplémentaire ne sera choisi après lecture de leurs résultats dans ce lot.
3. **Mesurer un changement de moteur sur un même Windows.** Comparer whisper.cpp 1.8.5 avec son correctif RNG à whisper.cpp 1.9.5, avec les mêmes poids Turbo Q5_0, Silero, pause de 576 ms, contexte complet et quatre fils CPU. La construction, les empreintes, le chargement, le calcul préchauffé et la mémoire doivent être distingués. Les trois prescriptions publiques sont un contrôle de régression restreint ; elles ne suffisent pas à qualifier la négation clinique.

Les 85 WAV déjà utilisés par le projet ne servent pas à choisir les réglages de ce nouvel entraînement. Les références de validation, les prédictions privées et les enregistrements ne sont jamais ajoutés au contexte du décodeur. Les résultats des variantes sont comparés sur exactement les mêmes fichiers.

## Conditions d'adoption

Le rapport doit compter les médicaments reconnus, les nouvelles pertes de noms, les doses, les fractions, les unités, les associations médicament–dose et les négations. Un total amélioré ne compense pas une nouvelle erreur critique. Un contrôle absent du corpus est signalé comme non couvert, sans être présenté comme une réussite.

Pour l'adaptation, il faut au minimum un gain sur les médicaments, une baisse des erreurs de mots, aucune nouvelle erreur critique suivie et aucun ralentissement dépassant le seuil exploratoire de 10 %. Même si ces conditions de développement passent, il reste à convertir les poids, à les tester dans le moteur Windows et à confirmer les résultats sur des voix et des phrases gardées à part. Un résultat Mac FP16 ne qualifie pas le paquet Windows Q5_0.

Pour le moteur, une amélioration de vitesse doit être observée sur le même hôte et sans perte des contrôles de fidélité. Le démarrage du processus n'est pas le délai entre une pause au microphone et l'apparition du texte. Le serveur GitHub n'est pas le PC de cabinet à 8 Go sans GPU dédié.

## Sources techniques réutilisées

- [Whisper.cpp 1.9.5 et ses changements officiels](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5).
- [PEFT 0.18.0 : adaptateurs et désactivation temporaire](https://huggingface.co/docs/peft/v0.18.0/en/package_reference/peft_model).
- [PyTorch 2.9 : divergence KL](https://docs.pytorch.org/docs/2.9/generated/torch.nn.functional.kl_div.html). Le calcul doit exclure les jetons masqués et conserver une normalisation par jeton valide.
- [Protocole, données et refus de la première adaptation](entrainement-local.md).

Dev Toolkit Orchestrator coordonne ici trois responsabilités séparées : entraînement, benchmark Windows et audit des contrôles. Les README de Ponytail et d'i-have-adhd ont été revérifiés ; leur rôle reste celui décrit dans [l'outillage du projet](toolkit-040.md). Aucun de leurs scripts n'est installé ni exécuté pour la reconnaissance vocale.
