# Évaluation médicale critique v2

Ce protocole accompagne `score_validation.py` et le [panel fictif](critical_scenarios_v2.json). Il renforce les contrôles de transcription ; il ne valide ni une prescription, ni un diagnostic, ni un usage en cabinet. Aucun résultat ASR n’est attribué au panel tant que ses phrases n’ont pas été enregistrées puis transcrites dans un essai documenté.

## Pourquoi changer le contrôle

Le lot de développement historique contient 32 dictées, 24 occurrences de noms de médicaments, 46 doses et 16 associations nom–force. Ses trois fractions sont dans une seule dictée ; sa seule négation est une consigne d’administration. Il ne couvre pas la négation de symptômes ni la latéralité. Un résultat de 32/32 sur une garde de négation ne représente donc pas 32 négations cliniques correctement reconnues.

Les rapports historiques restent inchangés. Le profil `medical-screens-v2` et le schéma 2 distinguent explicitement cette nouvelle mesure. La commande `score` refuse une grille ancienne ou un code de normalisation modifié : reproduire un rapport v1 demande son code historique, pas une réinterprétation silencieuse.

## Ce qui est contrôlé

1. **Nom complet du médicament.** Les accents et la casse sont tolérés, mais aucune correspondance approximative ne transforme un nom proche en succès. Les formes telles que `LP` font partie du nom annoté. Chaque occurrence compte ; la séquence des noms connus doit être conservée. Un nom ajouté hors du vocabulaire de la référence entraîne aussi une demande de revue, par le contrôle des nouveaux mots de contenu.
2. **Valeurs, unités et fractions.** Les notations prises en charge sont normalisées de manière déterministe : nombres français, unités abrégées et fractions usuelles. La suite des valeurs, la multiplicité des unités, les signes et les alternatives sont contrôlés. Les horaires restent liés à la fraction correspondante. Une forme inconnue n’est pas corrigée à partir d’une connaissance médicale.
3. **Association médicament–force.** La force doit suivre l’occurrence précise du nom, avec un lien local explicite. Plusieurs médicaments et plusieurs occurrences d’un même nom peuvent être contrôlés séparément. Une quantité présente ailleurs ne sauve pas l’association. Les concentrations, dénominateurs, signes, alternatives et zones contenant plusieurs quantités ambiguës sont refusés par ce contrôle. Les forces annotées sans association suffisamment explicite sont comptées comme `unlinked_source_strengths`, jamais comme réussies.
4. **Négation et contexte.** Le contrôle historique des marqueurs est complété par la comparaison des propositions qui portent la négation. Déplacer « pas » vers un autre symptôme ne conserve pas le sens attendu. Les marqueurs postposés, comme « absent » ou « exclu », sont également repérés. La catégorie `clinical_negation` est annotée explicitement dans le panel fictif ; elle n’est pas déduite des annotations BIO de prescriptions PxSLU.
5. **Latéralité.** Les propositions contenant gauche, droite, bilatéral, unilatéral, ipsilatéral ou controlatéral sont comparées avec leur contenu. Retrouver les deux mots « gauche » et « droite » dans le texte ne suffit pas si leurs symptômes ont été intervertis.
6. **Concentrations.** La présence globale d’une concentration ne suffit pas : les propositions qui la contiennent sont comparées. Intervertir les dénominateurs `mg par kg` et `mg par ml` entre deux médicaments est signalé même si toutes les valeurs et unités subsistent. Ce contrôle littéral n’effectue aucune conversion thérapeutique ou équivalence de dose.

Les propositions sont séparées par une ponctuation forte, une virgule hors décimale, ou un connecteur adversatif pris en charge. La comparaison est volontairement littérale après normalisation : une reformulation médicalement équivalente peut être signalée. Le scoreur ne connaît pas le sens de toutes les formulations françaises. Une revue humaine tranche ces alertes ; elle ne doit pas être remplacée par une correction automatique du texte reconnu.

Les ajouts de mots de contenu font l’objet d’un contrôle conservateur distinct. Ce contrôle peut signaler une simple reformulation et ne constitue pas un système de reconnaissance d’entités médicales. Le résultat global est un **filtre d’erreurs à examiner**, jamais une certification de fidélité clinique.

## Figer les deux fenêtres avant la génération

La nouvelle comparaison utilise la même partition de validation locale et la sélection déterministe du runner : 32 extraits historiques, puis les 64 suivants. Les 64 suivants n’ont pas été consultés en génération lors de l’expérience précédente ; leur perte de validation et leurs voix appartiennent toutefois à la partition déjà utilisée. Ils ne sont donc pas un test clinique indépendant. Le lot réservé de 85 WAV reste hors de cette sélection.

```bash
python -m p0.training.score_validation prepare \
  --corpus /CHEMIN/PRIVE/corpus \
  --px-archive /CHEMIN/PRIVE/PxCorpus.zip \
  --count 32 --offset 0 \
  --output /CHEMIN/PRIVE/grille-historique-32.json

python -m p0.training.score_validation prepare \
  --corpus /CHEMIN/PRIVE/corpus \
  --px-archive /CHEMIN/PRIVE/PxCorpus.zip \
  --count 64 --offset 32 \
  --output /CHEMIN/PRIVE/grille-suivante-64.json
```

Les sorties doivent être nouvelles et privées, hors dépôt. La préparation revérifie le corpus contre l’archive verrouillée et garde les références source exactes. Elle conserve les identifiants, les empreintes PCM, la sélection, la couverture et les empreintes du scoreur ainsi que de ses normaliseurs. Ce gel assure la cohérence de l’expérience locale ; le fichier SHA voisin n’est pas une signature d’un tiers.

L’auto-contrôle des références a révélé deux particularités du BIO source : « 1 demi » peut être découpé en deux valeurs contiguës, et une référence ne contenant qu’une condition pouvait être comptée une deuxième fois par le repli du scoreur. La v2 joint seulement des morceaux numériques adjacents dont le texte constitue un seul scalaire reconnu et déduplique ce repli exact. Les références et le BIO brut restent inchangés. Chaque référence doit passer sa propre grille avant que des prédictions puissent être évaluées.

Préparer les deux grilles et les faire relire **avant** de lancer la génération des candidats. Les références ne sont pas réécrites pour leur donner une meilleure orthographe ou faciliter le score. Les noms source non relus médicalement restent signalés comme une limite. Toute correction ultérieure des annotations ouvre une nouvelle version du protocole ; elle ne doit pas servir à effacer un échec après observation des résultats.

Pour chaque fenêtre, le runner doit produire des prédictions de base et de candidat sur les mêmes identifiants, voix et audios. La commande suivante vérifie le contrat de génération et l’ordre des cas avant de calculer les écrans critiques :

```bash
python -m p0.training.score_validation score \
  --grid /CHEMIN/PRIVE/grille-suivante-64.json \
  --predictions /CHEMIN/PRIVE/evaluation/predictions.local.jsonl \
  --output /CHEMIN/PRIVE/scores-suivants-64
```

Le rapport agrégé contient les numérateurs et dénominateurs, les améliorations et régressions appariées, ainsi que le nombre de dictées concernées. Plusieurs contrôles peuvent signaler la même erreur : leurs compteurs ne sont pas des événements indépendants. Les catégories sans occurrence figurent dans `unobserved_categories` ; elles ne prouvent aucune non-régression. Les détails par cas restent privés. Le scoreur n’adopte jamais automatiquement un modèle.

## Panel fictif élargi, sans audio ni score ASR

Les 33 scripts publics couvrent 16 fractions réparties sur huit scripts, huit propositions de négation de symptômes ou concepts, 18 propositions de latéralité sur neuf scripts, ainsi que des noms proches, des unités, des associations multiples et deux concentrations à dénominateurs distincts. La couverture exacte est stockée dans le JSON. Les médicaments réels figurent uniquement dans les listes lexicales, sans dosage prescrit. Les cas chiffrés utilisent les désignations explicites **médicament Alpha** et **médicament Bêta**, ou des fractions sans médicament réel : ce ne sont pas des conseils thérapeutiques.

Chaque script contient un texte volontairement altéré et le contrôle qui doit le rejeter. Ces altérations vérifient le code du scoreur, pas le modèle vocal. Le panel n’est ni enregistré, ni relu par un médecin à ce stade. Ses références et ses altérations sont publiques : il n’est pas un jeu secret permettant de prouver une généralisation clinique.

Pour passer à un essai utile avec le médecin volontaire :

1. Lui faire relire les scripts, la portée des négations, les côtés et les annotations. Noter les corrections avant tout essai de modèle.
2. Enregistrer quelques séances courtes avec des voix volontaires et uniquement ces situations fictives. Conserver localement le consentement, la version du script, le micro et le débit observé ; ne publier ni voix ni transcription individuelle.
3. Séparer par locuteur les futurs exemples d’adaptation et de confirmation. Garder aussi des textes nouveaux pour éviter de ne mesurer que la mémorisation des scripts. Ne jamais entraîner sur la confirmation ni utiliser ses références pour constituer les prompts.
4. Comparer les mêmes WAV avec le modèle de base et le candidat, paramètres identiques, puis relire toutes les régressions critiques en aveugle par rapport au nom du modèle. Garder les erreurs de médicament et d’association distinctes même si leur cause lexicale est commune.
5. Mesurer ensuite l’application au microphone sur les deux PC Windows, dont celui de 8 Go. Le temps d’inférence sur Mac, le résultat textuel d’un script et le délai après une pause dans l’application sont trois mesures différentes.

## Réemploi de travaux existants

Les travaux d’[Afonja et al., Interspeech 2024](https://www.isca-archive.org/interspeech_2024/afonja24_interspeech.pdf) mesurent les entités médicales séparément du WER global. Ils portent sur l’anglais clinique avec des accents africains : ils motivent une évaluation par entité, sans fournir une précision transférable à NoteVive en français.

[KG-Whisper, Interspeech 2024](https://www.isca-archive.org/interspeech_2024/shamsian24_interspeech.pdf) combine détection acoustique de mots-clés et adaptation du décodeur ou d’un préfixe appris. Il s’agit d’une méthode entraînée, pas de la simple injection d’un dictionnaire entier. C’est une piste à comparer ultérieurement avec des distracteurs et des mesures des ajouts indus ; aucune de ses performances n’est revendiquée ici.

Le travail de [Hou et al., Interspeech 2025](https://www.isca-archive.org/interspeech_2025/hou25_interspeech.pdf) étudie la sélection d’une petite liste parmi de nombreux mots de biais. Ses expériences sont notamment sur LibriSpeech et un Whisper contextualisé. La conséquence pour le protocole NoteVive est de mesurer les mots ciblés **et** les mots hors liste, avec une liste construite sans consulter les références du test. Le résultat ne justifie pas de fournir 10 000 termes au décodeur à chaque segment.

Le modèle conservé est [Whisper Large-v3 Turbo](https://huggingface.co/openai/whisper-large-v3-turbo), dont le décodeur compte quatre couches. Toute adaptation ou nouvelle technique de biais doit être comparée au paquet de base, avec les mêmes exigences de conservation des nombres et du sens ; aucun résultat de ce protocole ne vaut qualification médicale ou autorisation de changement du modèle distribué.
