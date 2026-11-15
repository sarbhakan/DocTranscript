# Consolidation NoteVive 0.4.1 — carnet, vocabulaire et reconnaissance

Ce lot traite trois besoins : rendre le carnet plus simple, rendre le vocabulaire de référence consultable par domaine et corriger l’échec numérique de l’entraînement avant d’en mesurer la fidélité. Les outils d’apprentissage ne sont jamais installés chez l’utilisateur de l’application. Le catalogue reste local et consultatif.

## Carnet simplifié

Quatre commandes visibles : **Nouvelle note**, **Dicter / Arrêter**, **Copier** et **Actions**. Les dossiers, notes et recherches sont à gauche ; le titre, les dates et le texte modifiable à droite. Le menu Actions contient le classement, les sous-dossiers, les tris et le vocabulaire. La sauvegarde reste automatique et son état visible. Le [guide du carnet](ui-041.md) et le [guide débutant](guide-essai-windows.md) suivent les libellés réellement affichés.

La dictée externe garde **Ctrl+Alt+Espace** ; **F9** sert dans NoteVive. La compatibilité dépend du champ : ce mécanisme ne prouve pas que Word, Excel ou tous les navigateurs sont compatibles. Les passages confirmés sont sauvegardés dans la note locale avant leur tentative d’envoi.

## Vocabulaire enrichi

Le catalogue passe de **70 517 à 100 175 entrées**, soit **29 658 ajouts**. Le catalogue final contient **99 192 libellés distincts** : un même libellé peut appartenir à plusieurs codes ou sources. Les nouvelles entrées couvrent les noms de médicaments, substances, formes et voies du RUIM de l’ANSM, l’anatomopathologie ADICAP et la biologie spécialisée LAHN. Les [sources et limites](lexique-041.md) précisent les éditions, les licences, les sélections et les transformations.

Les **33 classifications Orphanet** rattachent 7 492 des 7 493 codes actifs déjà présents à des domaines officiels ; le code non rattaché reste accessible dans la recherche générale. Les synonymes d’un code conservent ces rattachements sans augmenter le nombre de libellés. Les 75 filtres présents dans le catalogue comprennent des domaines et sous-domaines qui se recouvrent, et ne correspondent pas à 75 spécialités médicales entièrement couvertes.

Les archives officielles et les extractions sont épinglées par SHA-256. La préparation vérifie le schéma autorisé, le contenu relationnel, l’intégrité et l’index de recherche. Le fichier distribué est reconstruit à partir des seuls champs validés ; les octets ajoutés en fin de fichier et les anciennes pages libres de la source ne sont pas recopiés. Le hash des octets SQLite distribués est ensuite intégré à l’EXE et au fichier `Build/catalogue.json`. Les notes restent dans leur stockage distinct ; la préparation du vocabulaire n’y accède jamais.

## Entraînement et comparaison

L’échec de l’objectif de rétention a été reproduit : huit pertes de calcul finies, puis refus de poids LoRA non finis après le deuxième pas AdamW natif sur MPS. Le chemin de recherche corrigé conserve le modèle et les gradients sur MPS et effectue le pas AdamW, avec ses moments, sur des copies FP32 CPU des seuls paramètres LoRA. Les transferts sont synchronisés et contrôlés ; la primitive sous-jacente responsable de l’échec n’est pas identifiée.

Les trois bras préenregistrés ont terminé leurs 24 étapes sur les mêmes 96 exemples d’entraînement, avec base gelée inchangée et rechargement exact de l’adaptateur : objectif habituel, pénalité de rétention et pondération des seuls jetons médicament sûrs. Cette stabilité ne démontre pas une amélioration de la transcription. Le [protocole figé](../p0/training/retention_stability_plan.json) définit les comparaisons et les critères de refus.

Sur **96 enregistrements de développement**, aucune des trois méthodes ne conserve tous les éléments critiques que la base reconnaissait déjà. La pondération des médicaments gagne un nom sur le premier groupe de 32 extraits, mais perd une unité ailleurs. Sur les 64 autres, chaque variante gagne une dose et en perd une : un total identique cacherait cette régression. Les 576 sorties comparées se terminent correctement et les trois témoins donnent exactement les mêmes textes. Le [rapport de l’expérience](../p0/training/retention_stability_notes.md) détaille les scores et les motifs de refus. **Aucun de ces adaptateurs ne remplace les poids du paquet Windows.**

Le catalogue complet reste un outil de consultation. Une expérience distincte teste un contexte très court, composé uniquement de substances sélectionnées dans les données d’entraînement et le RUIM. Elle ne sélectionne pas les termes à partir du texte attendu des dictées testées. Les doses, fractions, négations, latéralités, associations médicament–dose et le silence sont des critères de refus, même si le taux global d’erreur baisse. Les résultats du rejeu et la validation Windows sont consignés après leur revue indépendante.
