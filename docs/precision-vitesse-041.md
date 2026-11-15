# Précision médicale et vitesse — expérience du 15 novembre 2026

**Résultat du lot : conserver le modèle et le moteur distribués dans NoteVive 0.4.0.** L'adaptation terminée réduit les erreurs globales mais introduit de nouvelles erreurs de médicaments et de doses. La variante avec rétention est interrompue pour calcul non fini. Le passage à whisper.cpp 1.9.5 apporte **5,2 % puis 2,6 % de gain préchauffé** dans les deux exécutions Windows, en dessous du seuil exploratoire de 20 % ; il ne résout pas la latence.

Ce lot améliore le contrôle des erreurs, la traçabilité des entraînements et la comparaison Windows. Un essai d'entraînement, un contrôle de fidélité et un benchmark Windows sont trois preuves distinctes. Aucun modèle expérimental n'a été exporté, ni ajouté au ZIP. La Release 0.4.0 reste l'unique paquet proposé pour les essais Windows.

## Résultat de l'adaptation

Le bras CE50 a terminé **50 mises à jour sur 200 enregistrements d'entraînement**, en 225,16 secondes sur le Mac M1 Pro. L'évaluation libre compare la base et l'adaptateur sur 96 autres clips de développement, répartis entre huit voix. Les grilles, leurs amendements issus de contre-exemples synthétiques et leurs sélections ont été figés avant toute prédiction de cette expérience.

| Contrôle | 32 clips historiques : base → CE50 | 64 clips supplémentaires : base → CE50 |
| --- | ---: | ---: |
| Erreurs de mots | 80/371 → 73/371 | 172/738 → 158/738 |
| Noms de médicaments reconnus | 8/24 → 8/24 | 16/49 → 18/49 |
| Doses reconnues | 42/46 → 41/46 | 82/97 → 83/97 |
| Fractions reconnues | 3/3 → 3/3 | 7/8 → 8/8 |
| Associations nom–dosage explicite reconnues | 5/16 → 5/16 | 9/25 → 10/25 |

Sur l'ensemble des deux fenêtres, le nombre d'erreurs de mots baisse de **252 à 231 sur 1 109 mots**. Mais quatre occurrences de noms sont récupérées et deux autres sont perdues ; trois passages de dose sont récupérés et trois autres sont perdus. Au moins un contrôle critique régresse dans **cinq dictées distinctes**. Ces cinq dictées et les nombres de contrôles ne s'additionnent pas : plusieurs contrôles peuvent concerner la même erreur. L'adaptateur est refusé.

La variante CE+KL de 0,35 s'arrête après deux mises à jour, sans checkpoint utilisable. Les diagnostics reproduisent des sorties étudiant non finies alors que les sorties enseignant sont finies, y compris avec un décodeur enseignant séparé. Ils n'établissent pas la cause interne. La comparaison des deux méthodes d'entraînement est donc **incomplète** ; aucun bénéfice de la rétention n'est revendiqué. Le chemin KL reste expérimental et désactivé par défaut.

Le code refuse désormais des poids LoRA non finis après une mise à jour et avant toute sauvegarde. **Ce garde-fou a été ajouté après les essais ci-dessus** : il ne faut pas lui attribuer la validation du CE50 déjà entraîné. Le rechargement exact de CE50, l'absence de changement des poids de base et les résultats de génération ont leurs propres contrôles. Le [code exact exécuté pour les deux entraînements](https://github.com/sarbhakan/DocTranscript/blob/7bdba347204872a5a92db86aa69488144b408801/p0/training/train_lora.py) est conservé dans l'historique ; ses empreintes et les traces privées sont archivées localement.

Le [rapport agrégé](../p0/training/retention_report.json), la [note technique](../p0/training/retention_notes.md) et le [plan figé](../p0/training/retention_experiment_plan.json) détaillent les compteurs et les limites. Les temps de génération sur Mac restent proches de la base ; ce n'est pas une mesure du paquet Windows quantifié.

## Comparaison Windows réellement exécutée

Le [benchmark Windows](https://github.com/sarbhakan/DocTranscript/actions/runs/43667755235) a comparé les deux moteurs sur une VM AMD EPYC 7763, deux cœurs et quatre processeurs logiques, environ 16 Gio de mémoire. Deux répétitions ont inversé l'ordre des moteurs. Les mêmes poids, le même OpenBLAS et le même pont ont traité trois prescriptions publiques et un silence ; la taille de paquet audio correspond aux 20 ms du moteur Windows.

| Mesure sur ce serveur | whisper.cpp 1.8.5 corrigé | whisper.cpp 1.9.5 |
| --- | ---: | ---: |
| Médiane du rejeu préchauffé d'une dictée | 45,60 s | 43,50 s |
| Médiane de calcul d'une portion détectée par Silero | 15,10 s | 14,38 s |
| Processus neuf sur la courte dictée, médiane | 15,50 s | 16,22 s |

Le rapport médian des temps appariés vaut **0,948**, soit environ **5,2 % de gain préchauffé**. Les sorties texte, les portions audio et les pauses sont identiques entre les deux moteurs sur tous les contrôles de ce lot. Les trois doses et les trois fractions attendues passent ; les noms de médicaments restent à deux sur trois. Cela confirme la même limite lexicale sur ces trois exemples, pas une amélioration de précision.

Le seuil exploratoire de 20 % n'est pas atteint et, dans cette première exécution, le passage par un processus neuf n'est pas accéléré. Le calcul par portion reste de l'ordre de 14 à 15 secondes sur cet hôte. Les [mesures complètes](../p0/windows_runtime_ab_report.json) et la [procédure reproductible](../p0/windows_runtime_ab.md) distinguent mémoire échantillonnée, initialisation et calcul. Un processus neuf n'implique pas un cache disque froid. Ces tests ne couvrent ni un microphone, ni un PC physique de 8 Go, ni une négation clinique prononcée.

La [réplication sur le commit final](https://github.com/sarbhakan/DocTranscript/actions/runs/43669761750) utilise le même banc, les mêmes réglages et un inventaire de même profil EPYC 7763. Ses [mesures séparées](../p0/windows_runtime_ab_replication.json) donnent un rapport médian apparié de **0,974405**, soit **2,56 % de gain à chaud**. La tranche médiane passe de 15,050 à 14,845 secondes. Le processus neuf passe cette fois de 15,624 à 15,483 secondes : ce petit écart ne reproduit pas le ralentissement du premier passage. Aucun gain stable au démarrage n'est établi.

Dans chaque exécution, les dix paires de textes et de portions audio sont identiques entre versions. Les doses, fractions et suites numériques restent à 3/3 et les noms à 2/3 dans cette réplication. Les agrégats ne contiennent pas les textes bruts : ils ne permettent pas d'affirmer une égalité textuelle exacte **entre** les deux exécutions. Les résultats ne sont pas regroupés en un taux de précision clinique ; ils portent toujours sur les mêmes trois prescriptions et un silence. Les deux gains de temps sont sous le seuil fixé et la décision reste inchangée.

## Améliorations retenues dans le code et les outils

- Contrôles des noms complets, de leur ordre et de leurs occurrences ; aucune correction approximative d'un médicament.
- Association de chaque force à l'occurrence précise du médicament ; huit forces trop ambiguës dans les 64 clips sont signalées comme non associées, sans être comptées comme réussies.
- Contrôle des propositions portant une négation, un côté ou une concentration. Par exemple, intervertir `mg/kg` et `mg/ml` entre deux médicaments est détecté même si les mêmes nombres et unités restent présents.
- Comptage des gains **et** des régressions par contrôle et par dictée, conservation des catégories absentes, vérification des contrats de génération, des références, des empreintes et des paramètres réellement utilisés.
- Refus des poids non finis et rapports qui ne peuvent pas déclarer un comparatif complet lorsqu'un bras a échoué.

Les [33 scripts fictifs à lire](dictees-fiabilisation.md) donnent un support accessible pour la suite. Ils testent aussi des négations cliniques et des latéralités, **absentes des annotations des 96 enregistrements évalués**. Ce panel est pour l'instant textuel : aucun taux de reconnaissance ne lui est attribué. Le [protocole médical v2](../p0/training/critical_protocol_v2.md) décrit la relecture par le médecin volontaire, l'enregistrement et la séparation des futures voix de confirmation.

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
