# Essai P0/P3 : effet d’un lexique sur un seul moteur de dictée

Statut : protocole prêt pour une future campagne ; les modes lexicaux ne sont pas exécutables avec l’adaptateur P0 de base. Voir [ce qui est documenté pour chaque moteur](../docs/adaptation-lexicale.md). Aucun résultat de reconnaissance ni seuil clinique n’est revendiqué.

## 1. Figer les entrées

1. Partir des conventions du [corpus de dictée](corpus/README.md) et du [banc ASR](bench/README.md). Préparer des voix humaines sur des notes fictives. Utiliser des locuteurs et des scripts disjoints entre développement et confirmation. Une prise est rejouée sans modification dans chaque bras. Transcrire ce qui a été prononcé, y compris les autocorrections, et annoter les bornes de parole pour chaque fichier.
2. Former un corpus de développement médecine générale + une spécialité à tester. Point de départ d’ingénierie : au moins 25 occasions de termes ciblés et 25 occasions de leurres proches dans chaque domaine, 20 prises sans terme cible dont du français non médical, et les contrôles de silence/bruit. Ventiler les occasions sur plusieurs voix et plusieurs termes. Prévoir une confirmation plus large pour le réglage retenu ; ces nombres ne valident pas un taux très faible de défaut critique.
3. Figer un lexique admissible **avant** d’écrire les scripts de confirmation. Le fichier global peut légitimement contenir les termes attendus ; la sélection ne consulte jamais la référence, les termes annotés par cas ou un résultat du test. La personne qui fixe les réglages travaille sur le développement ; le dépositaire de la confirmation garde les WAV et annotations hors de la vue du réglage.
4. Sceller les mêmes entrées dans chaque bras : archives et révisions des modèles, tokenizer, runtime et build Windows, sélection de termes, code de sélection, paramètres, CSV/WAV, ordre des prises. Utiliser le même poste, le même nombre de threads, la même quantification et le même VAD s’il existe. Consigner charge et alimentation ; campagne principale CPU seul. Choisir un WAV d’échauffement hors confirmation.

| Famille de cas | Construction | Contrôle attendu |
| --- | --- | --- |
| Cible présente | Terme rare dans une note plausible, en position et débit variés. | Reconnaissance exacte ou variante préapprouvée, sans changer les mots proches ni les attributs. |
| Cible absente, leurre prononcé | Dire un mot courant ou un autre terme médical proche phonétiquement de la cible. | Reconnaître le mot dit. Une substitution vers la cible compte comme faux positif. |
| Cible absente, note réaliste | Notes pertinentes sans cible du pack actif, plus français ordinaire. | Aucun ajout clinique ni copie de liste ; mesurer le WER hors jargon. |
| Mauvais contexte | Rejouer avec le pack d’une autre spécialité de taille voisine. | Quantifier le risque en cas de mauvais choix du contexte. |
| Silence ou bruit seul | Silence, clavier, bruit de pièce réel, sans parole intelligible. | Aucun contenu clinique provisoire ou final. Le banc conserve le drapeau « hypothèse non vide » ; une capture locale contrôlée permet de qualifier ce contenu. |
| Éléments critiques voisins | Terme cible près d’une négation, unité, dose, fréquence ou latéralité. | Le mot-clé ne modifie pas les informations adjacentes. Relecture de leur portée et des ajouts. |

Ajouter aux cas et attributs existants un fichier d’annotation lexical local `lexical-targets.csv` : `case_id,mention_id,term_id,status,expected_surface,alternatives,critical,notes`. Une ligne par occurrence attendue (`present`) ou leurre ciblé (`absent`) ; `alternatives` est un tableau JSON de formes autorisées, `critical` vaut `0` ou `1`. Pour une cible absente, `expected_surface` peut préciser la forme du leurre réellement dite ; le `term_id` désigne la cible qui ne doit pas apparaître. Aligner chaque mention dans sa phrase, pas par simple recherche de sous-chaîne. Classer aussi les ajouts qui n’ont pas de ligne de leurre. Le worker ne reçoit jamais ce fichier.

## 2. Instrumenter une comparaison appariée

Compléter l’adaptateur avec une configuration de test explicite sans changer le protocole audio NDJSON. Ce n’est pas une API livrée. Une exécution correspond à un bras statique : l’adaptateur peut charger l’instantané de test au démarrage et réutiliser les mêmes termes pour chaque flux. Plus tard, l’application construit le contexte à partir du pack choisi pour la session. Les entrées brutes ne passent ni dans les arguments de commande, ni dans le manifeste du banc, ni dans les traces par défaut. Les champs `ready.details` contiennent uniquement paramètres et empreintes : configuration, tokenizer, variante du moteur, mode de recherche, nombre de chemins, score, compteurs sélectionnés/acceptés/rejetés et empreinte de la sélection. Réserver le détail des rejets aux lexiques fictifs ou publiables.

| Bras | Paramètres | Ce qu’il permet de conclure |
| --- | --- | --- |
| A · Référence du moteur | Réglage P0 sans lexique ; sherpa en `greedy_search`. | Point de comparaison produit. |
| B · Recherche seule | Pour sherpa : `modified_beam_search`, quatre chemins, liste vide. Pour Whisper : A suffit si tous les réglages hors prompt sont identiques. Pour le SDK NVIDIA : même mode de décodage sans contexte. | Isole le coût et l’effet de la recherche avant tout terme ajouté. |
| C · Liste courte correcte | Même configuration B, liste commune + spécialité. Plafond initial proposé : 16 entrées actives, variantes comprises. Pour sherpa, score global initial à 1,5 (défaut documenté), sans poids par terme ; SDK NVIDIA RNNT : point de départ à 2,0. Pour Whisper, un contexte à 32 jetons maximum, sans score par terme. | Mesure du gain spécifique des mots-clés face à B, puis du compromis complet face à A. |
| D · Mauvaise spécialité | Même B, même taille et réglages que C, autre sélection issue du catalogue. | Effet si le praticien se trompe de contexte. |
| E · Taille / poids, développement seul | Transducteurs : taille 16 puis 64 avec score constant ; ensuite score bas/initial/haut à taille constante (sherpa : 0,5/1,5/2,5 ; SDK RNNT : 1/2/3). Whisper : 32 puis 64 jetons, gabarit et politique de réapplication constants. Proposer un plafond de jetons transducteur (p. ex. 256 à 16 entrées, 512 à 64), mesurer la charge réelle. | Effet de la quantité et de la force du biais, avec une seule variable modifiée à la fois. Les scores ne sont pas comparables entre moteurs. |

Vérifier d’abord l’absence de récupération réseau, le tokenizer, le passage de `fr-FR` et l’encodage de termes fictifs avec apostrophes et accents. Pour sherpa, contrôler le nombre d’entrées réellement chargées et le mode de recherche. Pour Whisper, fixer la gestion de contexte de chaque fenêtre et vérifier que le prompt s’applique avec le binding exact et le réglage `no_context` retenu. Si un paramètre ne peut être vérifié, ne pas interpréter un résultat nul comme une absence de gain.

Pour chaque bras, utiliser les commandes du [guide P0](README.md) et le contrat du [banc](bench/README.md), avec un dossier de résultats distinct. Schéma PowerShell à réutiliser dès que l’adaptateur fournit les arguments du bras :

```powershell
# $Worker contient la commande locale exacte du bras sous forme de tableau.
& $Python -m p0.bench --cases $Cases --wav-dir $Audio --output $OutRealtime --partition dev --mode realtime --warmup-wav $Warmup --include-text -- @Worker
& $Python -m p0.bench --cases $Cases --wav-dir $Audio --output $OutAccel --partition dev --mode accelerated --warmup-wav $Warmup -- @Worker
```

Répéter les mesures de vitesse en alternant les bras (p. ex. A/B/C/D, D/C/B/A, B/A/D/C), à charges et températures documentées. Les répétitions ne créent ni nouveaux locuteurs, ni nouvelles occasions lexicales. Rattacher les résultats aux empreintes des entrées. Mesurer séparément la création du contexte, le premier mot correct, la finalisation, les révisions, le retard d’envoi, le facteur temps réel et la mémoire privée cumulée. La réception NDJSON mesure le worker ; ajouter la mesure jusqu’à l’affichage dans l’application avant qualification.

## 3. Lire les résultats et décider

Rapporter les données appariées de A/B/C/D (effectifs bruts et écarts). Sur les cibles présentes : exactes, manquées ou substituées. Sur les leurres : substitutions vers la cible, dénominateur des occasions négatives et notes concernées. Sur le reste : termes du pack ajoutés à tort, ajouts cliniques hors pack, contrôles non vides, WER hors jargon et relecture des attributs selon le [protocole qualité](../docs/qualite-medicale.md). Ventiler par spécialité, terme, locuteur, micro et bruit. Publier le nombre de prises améliorées et détériorées, et l’incertitude avec une méthode appariée tenant compte du locuteur. Pour mesurer le temps de correction, présenter des notes sans révéler leur bras, en contrebalançant l’ordre.

Préenregistrer la règle d’acceptation avant d’ouvrir la confirmation. Proposition d’ingénierie : amélioration du rappel ciblé d’au moins 5 points face à B, borne basse de l’intervalle apparié au-dessus de zéro pour revendiquer un gain établi, et temps de correction sans régression face à A selon une marge fixée avant l’essai. Une erreur critique supplémentaire bloque l’activation jusqu’à mitigation vérifiée. Exiger zéro ajout clinique sur les contrôles et une marge explicite de non-régression du français courant ; publier les effectifs pour éviter d’interpréter zéro observation comme zéro risque. Rejouer le test avec le pack final à la taille diffusée. Les [seuils de latence, de ressources et de fidélité](../docs/feuille-de-route.md#critères-mesurables-proposés) restent obligatoires, y compris avec la recherche et le contexte activés.

Après le développement, verrouiller **un seul** modèle, runtime, format d’export, réglage de recherche et règle de sélection. En confirmation, comparer cette configuration, sa référence sans biais et le contrôle de contexte erroné. Si le gain est incertain ou trop coûteux, garder le même moteur sans biais, avec suggestions distinctes de relecture si elles apportent de la valeur. Si aucun candidat ne valide le direct et la fidélité générale, revoir le périmètre ou le plancher matériel. Les variantes évaluées ne deviennent pas des éditions ou des modèles supplémentaires distribués avec le produit.
