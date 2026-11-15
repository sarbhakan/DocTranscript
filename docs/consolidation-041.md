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

Le catalogue complet reste un outil de consultation. Une expérience distincte teste un contexte très court, composé uniquement de substances sélectionnées dans les données d’entraînement et le RUIM. Elle ne sélectionne pas les termes à partir du texte attendu des dictées testées. Les doses, fractions, négations, latéralités, associations médicament–dose et le silence sont des critères de refus, même si le taux global d’erreur baisse. Le premier rejeu HF/MPS est non concluant : le témoin ne termine pas correctement et les deux bras produisent du texte sur les silences envoyés directement au moteur. Il a été interrompu et conservé comme échec du banc, sans servir à sélectionner un modèle.

Un [contrôle mécanique en FP32 sur Metal](../p0/training/mps_precision_probe_041.md) a ensuite reconnu les neuf mots d’une même phrase fictive non médicale et atteint la fin de transcription, alors que les deux essais FP16 historiques répétaient un jeton. La route de précision est donc une piste concrète pour réparer ce banc, avec un coût mémoire à surveiller. Ce seul cas ne qualifie pas les dictées médicales et ne réhabilite aucune des comparaisons invalides.

Un [second essai avec whisper.cpp](../p0/lexical_cpp_041.md), le moteur du produit, mesure le même contexte sur Mac. Sur 48 dictées ne contenant aucun des 11 noms de la liste, il modifie 29 textes et introduit des pertes critiques dans cinq dictées. Le contrôle positif synthétique prononce ensuite chacun des 11 noms : leur reconnaissance passe de **2/11 à 9/11**, mais les doses baissent de **22/22 à 20/22**, les fractions de **11/11 à 9/11** et les clauses négatives de **7/11 à 5/11**. Le contexte est donc **refusé**, y compris sur ce lot favorable aux médicaments. Les gains d’orthographe ne compensent pas ces régressions.

Les sons et réglages sont appariés, les protocoles figés avant chaque décodage, et les résultats recalculés par un autre agent. Le bloc positif reste une contre-épreuve conçue après le premier lot, sur une seule voix synthétique ; il n’est pas une confirmation indépendante. Le coût total du contexte augmente de 2,3 à 2,9 % selon le lot sur ce Mac. Ces mesures ne prouvent ni une vitesse Windows ni une fidélité clinique. Silero conserve des sorties vides sur les deux silences de contrôle ; contourner ce filtre produit du texte non médical dans les deux bras.

## Décision pour le paquet

Les améliorations livrables sont le carnet simplifié, le catalogue consultable et les protections de destination de la dictée externe. Les correctifs d’entraînement et les bancs d’essai sont publiés pour poursuivre la recherche. **Les poids et le contexte de reconnaissance du produit restent inchangés.** Aucun remplacement automatique de médicament, de dose ou de négation n’est ajouté.

La validation Windows du nouveau carnet est encore en cours. Les contrôles de stockage, de compilation, de moteur audio et de dictée externe ont passé ; la recette de navigation doit être corrigée ou confirmée avant publication.
