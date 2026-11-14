# Ajustement local de Whisper pour NoteVive

État au **14 novembre 2026 : l’entraînement est terminé et les trois sauvegardes évaluées sont refusées pour l’intégration**. Une passe complète a bien modifié les adaptateurs du modèle. Elle a réduit le nombre total d’erreurs sur le petit lot de développement, mais a aussi dégradé des noms de médicaments que la base reconnaissait correctement. **NoteVive conserve donc son modèle de base.** Aucun modèle adapté n’a été exporté ou ajouté à l’application.

Ce document explique ce qui a été exécuté, pourquoi le candidat n’est pas adopté et comment poursuivre avec un médecin volontaire. Les commandes et les contrôles techniques figurent dans le [guide d’entraînement](../p0/training/README.md). Le médecin n’a pas besoin d’installer cette chaîne pour utiliser ou tester NoteVive.

## Ce qui a réellement été entraîné

Le point de départ est [Whisper Large-v3 Turbo d’OpenAI, révision `41f01f3`](https://huggingface.co/openai/whisper-large-v3-turbo/tree/41f01f3fe87f28c78e2fbf8b568835947dd65ed9). L’essai a utilisé **1 081 prescriptions fictives, prononcées par 32 personnes**, issues de [PxCorpus v4](https://zenodo.org/records/10080490). Les 282 extraits de validation proviennent de huit autres voix. Les références et signaux audio identiques entre ces partitions ont été exclus. Les voix de médecins réservées par le banc n’ont pas participé à l’adaptation. Un éventuel recouvrement avec le préentraînement d’OpenAI reste inconnu.

La méthode existante **PEFT/LoRA** ajuste de petits adaptateurs ajoutés au décodeur, en gardant l’encodeur et les poids d’origine gelés. Ici, **327 680 paramètres** ont été ajustés sur 16 projections des quatre couches du décodeur. L’environnement est fixé à PyTorch 2.9.1, Transformers 4.57.3 et PEFT 0.18.0. La base est en FP16 et les adaptateurs en FP32. Les préfixes de transcription française, le jeton de fin et le masquage du remplissage ont été contrôlés ; le texte attendu n’est jamais fourni au modèle pendant la génération de validation.

Sur l’**Apple M1 Pro à 16 Gio de mémoire unifiée**, l’essai a réalisé **271 mises à jour effectives en 23 min 15 s**, avec accumulation de quatre clips, sauf le dernier groupe d’un clip. Ce temps comprend la validation finale de la perte, le chargement et les contrôles de sauvegarde, après la vérification initiale des fichiers. Les gradients étaient finis, la base est restée inchangée et les adaptateurs modifiés ont été rechargés à l’identique. Les maxima relevés sont 3,58 Go pour le compteur mémoire du pilote MPS et 1,03 Go de RSS du processus : ces compteurs ne s’additionnent pas pour mesurer la mémoire physique du Mac. Le [rapport d’exécution](../p0/training/lora_epoch_report.json) conserve les valeurs exactes et les empreintes du code exécuté.

La perte finale vaut **0,26592 sur 5 660 jetons des 282 extraits de validation**. C’est un indicateur d’entraînement calculé avec les mots précédents de la référence ; ce n’est pas un taux de transcription correcte. La génération libre ci-dessous mesure séparément la reconnaissance.

## Comparaison et décision

Les mêmes **32 extraits, huit voix et 371 mots de référence** ont été transcrits par la base et chaque adaptateur, sans recevoir les références. Leur choix est déterministe et équilibré entre les voix. La grille des éléments critiques et son code de mesure ont été figés avant toute prédiction. Après l’examen de la sauvegarde finale à 271 mises à jour, un plan borné a fixé l’examen de deux sauvegardes déjà produites, dans l’ordre 50 puis 150, avant de calculer leurs résultats. Aucun entraînement supplémentaire n’a été lancé.

Le tableau rapporte les correspondances avec les références source. Le WER compte les substitutions, omissions et ajouts de mots, rapportés aux 371 mots attendus. Les autres colonnes comptent les passages reconnus selon la grille figée ; elles ne constituent pas une validation médicale des prescriptions.

| État évalué | Erreurs de mots / 371 | WER | Noms de médicaments / 24 | Doses / 46 | Associations médicament–dosage / 16 | Décision |
|---|---:|---:|---:|---:|---:|---|
| Base sans adaptation | 80 | 21,56 % | 8 | 42 | 5 | Conservée dans l’application |
| Adaptateur à 50 mises à jour | 55 | 14,82 % | 10 | 41 | 7 | Refusé |
| Adaptateur à 150 mises à jour | 32 | 8,63 % | 10 | 45 | 7 | Refusé |
| Adaptateur à 271 mises à jour | 30 | 8,09 % | 11 | 45 | 7 | Refusé |

**Cette comparaison utilise Transformers sur le Mac, avec une base FP16 et des adaptateurs FP32. Elle ne mesure pas directement le modèle Q5_0 livré pour Windows.** Le [rapport agrégé de validation](../p0/training/lora_validation_report.json) contient les numérateurs, dénominateurs, gains et régressions appariés, temps et empreintes. Les sons, phrases, identifiants de cas et prédictions restent hors du dépôt.

Les trois sauvegardes échouent au critère fixé : au moins un gain sur les noms, moins d’erreurs de mots et **aucune nouvelle erreur critique**. Chaque adaptateur introduit **deux erreurs de nom de médicament et une erreur d’association médicament–dosage** là où la base passait le contrôle. Ces catégories peuvent concerner les mêmes cas ; leurs comptes ne doivent pas être additionnés comme un nombre de patients ou de prescriptions.

À 50 mises à jour, deux passages de dose auparavant reconnus échouent également. À 150 mises à jour, un cas supplémentaire échoue au contrôle de la séquence de nombres ; la présence d’un nombre ajouté ne permet pas, à elle seule, d’affirmer qu’une dose a été modifiée. À 271 mises à jour, les régressions observées concernent les noms et leur association au dosage. Le meilleur WER ne suffit donc pas à choisir cette dernière sauvegarde.

Le temps cumulé de génération reste voisin de 42 à 43 secondes pour 196,88 secondes d’audio par variante. Par rapport à leur base appariée, les variations du total sont −0,31 %, +0,22 % et +0,08 % pour 50, 150 et 271 mises à jour ; les variations de la médiane sont respectivement +1,58 %, +0,86 % et −1,86 %. Elles passent le seuil exploratoire de +10 %. Il s’agit d’un passage par sauvegarde sur ce Mac, sans estimation de variabilité, sans microphone et sans mesure sur Windows à 8 Go.

Un défaut du rapport initial faisait croire que le jeton de fin de génération manquait partout. [Transformers 4.57.3 retire ce jeton de son retour simplifié](https://github.com/huggingface/transformers/blob/v4.57.3/src/transformers/models/whisper/generation_whisper.py#L551). Le contrôle lit désormais les séquences complètes : le jeton est présent dans **32/32 sorties de chaque variante**. La répétition de l’évaluation finale retrouve 32/32 textes identiques pour la base et **31/32 pour l’adaptateur** ; un mot de médicament déjà incorrect varie, sans changer le WER ni les scores critiques. La cause de cette variation n’a pas été établie. Les réglages ASR sont inchangés et aucune reproductibilité exacte de toutes les sorties n’est revendiquée.

## Ce que ces résultats ne démontrent pas

Ce lot sert au développement et au choix d’un candidat. Il ne donne pas une estimation indépendante de la fiabilité en cabinet. Il contient des prescriptions simulées ; les maladies, examens et autres spécialités n’y sont pas représentés de manière suffisante. Les références `seq.in` sont préservées telles que fournies par les auteurs de PxCorpus ; le projet n’a pas refait leur relecture médicale à l’écoute.

Les fractions ne concernent qu’un extrait, avec trois passages. La négation annotée ne concerne qu’un extrait et une consigne ; aucune négation de symptôme n’est couverte. Le maintien de ces résultats ne prouve donc pas la maîtrise des fractions et négations en consultation. Les contrôles automatiques sont conservateurs et peuvent aussi signaler une reformulation acceptable : leur interprétation exige une relecture.

**Les 85 audios du banc de régression n’ont pas été utilisés pour cet entraînement ni pour cette sélection.** Aucune fusion HF, quantification Q5_0 ou qualification Windows du modèle adapté n’a été exécutée après le refus. Les outils d’export sont préparés pour un futur candidat admissible. Les 85 cas, déjà utilisés dans les travaux antérieurs du projet, restent un banc de régression ; ils ne deviennent pas une nouvelle confirmation clinique indépendante.

## Prochain travail réalisable avec un médecin volontaire

L’étape utile est d’améliorer les exemples et leur validation. Ajouter des milliers de mots écrits dans un dossier ne fournit pas au modèle leur prononciation. Un lexique sert à préparer des phrases et à choisir les situations à vérifier ; une adaptation acoustique exige les enregistrements et leur transcription exacte.

1. **Préparer ensemble des dictées fictives.** Le médecin choisit des situations courantes de sa pratique, puis vérifie les noms, dosages, fractions, horaires, négations et côtés droit/gauche. Inclure aussi des phrases simples et des mots proches pour vérifier qu’un terme rare n’est pas ajouté à tort. Commencer par quelques séances courtes, par exemple 10 à 15 minutes si cela lui convient. Aucun dossier de patient n’est nécessaire.
2. **Enregistrer avec une voix et un débit naturels.** Hakan ou le médecin utilise le micro du poste cible et conserve le son localement. Pour chaque extrait, le médecin réécoute et valide le texte réellement prononcé. Un passage ambigu reste signalé comme tel ; on ne devine pas un médicament à partir du contexte. La référence ne doit pas être copiée sans vérification depuis la sortie du moteur.
3. **Conserver les corrections de façon traçable.** Associer localement audio, texte vérifié, spécialité, conditions d’enregistrement et autorisation du volontaire. Les références approuvées sont distinctes des sorties automatiques. Une correction dans NoteVive ne réentraîne pas automatiquement le modèle. Le travail technique consiste ensuite à préparer un import contrôlé et un nouveau protocole, sans envoyer ces fichiers à un service distant.
4. **Mettre les futurs contrôles à part avant l’adaptation.** Réserver d’autres voix et d’autres phrases pour la confirmation, sans les utiliser pour régler le modèle. Avec un seul médecin, on peut préparer des exemples et trouver des erreurs, mais on ne peut pas démontrer une généralisation à plusieurs voix. Des volontaires supplémentaires permettront cette séparation. Une phrase ou une voix réservée ne doit pas repasser dans l’entraînement après lecture de son résultat.
5. **Faire une nouvelle expérience bornée, puis appliquer les mêmes critères.** Avant son lancement, fixer les données, les réglages, le nombre de candidats et les erreurs qui interdisent l’adoption. Seul un candidat admissible pourra être fusionné et converti avec le [convertisseur officiel whisper.cpp](https://github.com/ggml-org/whisper.cpp/blob/v1.8.5/models/convert-h5-to-ggml.py), avec une base témoin convertie de la même façon. Il faudra ensuite contrôler les régressions, le nouveau jeu gardé à part et l’usage réel sur les deux PC Windows prévus, dont celui à 8 Go sans GPU dédié : texte affiché, délais aux pauses, doses, sauvegarde, fermeture et réouverture.

Hakan et le médecin peuvent se concentrer sur les phrases, l’enregistrement et la relecture. La préparation des fichiers, les contrôles de séparation, l’exécution et le rapport relèvent du travail de développement. Ce parcours permet de mesurer les progrès et les nouvelles erreurs ; il ne garantit pas qu’une prochaine adaptation sera adoptable. La [méthode générale du banc](../p0/asr_benchmark.md) reste applicable.
