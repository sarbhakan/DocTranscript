# Lexique médical local — enrichissement 0.4.1

Ce lot porte le catalogue de **70 517 à 100 175 entrées**. Il ajoute des médicaments, leurs substances, les formes pharmaceutiques, les voies d’administration, des termes d’anatomopathologie et des actes de biologie. Il rattache aussi les maladies rares déjà présentes aux classifications officielles Orphanet. Le catalogue sert à **chercher et vérifier un terme**. Sa présence ne réentraîne pas le modèle et ne prouve pas une amélioration de la dictée.

Dans le glossaire, une recherche peut être limitée à un domaine et à un type de terme. La source, le code et l’édition permettent de retrouver l’origine du résultat. Les filtres ne montrent que les domaines réellement présents dans le catalogue. Un même terme peut appartenir à plusieurs domaines ; les nombres par domaine ne doivent donc pas être additionnés.

## Ce qui a été ajouté

Les comptes ci-dessous proviennent des fichiers effectivement téléchargés et vérifiés le **15 novembre 2026**, puis du catalogue reconstruit. Une entrée est un triplet `(source, code, libellé)`, pas un mot unique. Après comparaison littérale avec l’ancien catalogue, ce lot apporte **28 785 libellés distincts supplémentaires**. Le catalogue final contient **99 192 libellés littéralement distincts**, avant toute normalisation de casse ou d’accents. Le détail reproductible figure dans [coverage-041.json](../lexique/coverage-041.json).

| Contenu ajouté | Édition et provenance | Entrées retenues | Traitement appliqué |
|---|---|---:|---|
| Noms de spécialités pharmaceutiques | [RUIM ANSM, diffusé par l’ANS](https://smt.esante.gouv.fr/terminologie-ref_interop_med/), 2026-10-01 | 13 834 | Uniquement `actif=true` ; libellé complet, dosage et forme conservés. Les 2 293 lignes historiques `actif=false` sont exclues. |
| Substances et synonymes français | Même RUIM, `Substances.csv` | 5 201 | 3 461 codes de substances ; libellé préféré et synonymes explicitement fournis par la source. Aucun nom inventé à partir d’un dosage. |
| Formes pharmaceutiques | Même RUIM, `Formes.csv` | 360 | Catégorie séparée ; code FT et orthographe de la source conservés. |
| Voies d’administration | Même RUIM, `Voies.csv` | 86 | Catégorie séparée ; aucune recommandation de voie. |
| Anatomopathologie et topographie | [ADICAP, ANS](https://smt.esante.gouv.fr/terminologie-adicap/), 2024-10 | 9 472 | 201 concepts avec une date de fin et 9 rubriques racines exclus ; 1 938 entrées d’anatomie et 7 534 termes d’anatomopathologie. |
| Actes de biologie hors nomenclature | [LAHN DGOS, ANS](https://smt.esante.gouv.fr/terminologie-lahn/), 2026-04, FHIR `history/10` | 705 | Seuls les concepts de type `code` ; 64 rubriques exclues. Aucun tarif ni coefficient importé. |

L’édition RUIM est datée du 1er octobre 2026 ; ses métadonnées ANS portent une publication au 29 septembre et l’archive une exportation au 9 novembre. La date ADICAP est le 2 octobre 2024. Pour LAHN, le manifeste indique explicitement la date de mise à jour FHIR du 6 août 2026, distincte de l’édition d’avril. Un statut actif dans un référentiel ne garantit ni commercialisation ni disponibilité en pharmacie à la date de consultation.

Les orthographes sont conservées, y compris les libellés composites ADICAP : un libellé contenant plusieurs expressions n’est pas découpé pour gonfler le compte. Les six libellés LAHN contenant un retour à la ligne sont représentés sur une seule ligne, sans changer leurs mots. ADICAP utilise le suffixe de l’URI de chaque concept comme code unique : son champ `skos:notation` peut être ambigu entre dictionnaires. La page descriptive ADICAP annonce 9 511 concepts ; le fichier RDF livré comporte 9 682 concepts typés avant les exclusions ci-dessus. Le chiffre affiché ici est celui de notre extraction contrôlée, pas celui de la page descriptive.

## Domaines et couverture réelle

Le [pack officiel Orphanet 2026](https://www.orphacode.org/pack-nomenclature/) fournit 33 classifications par domaine médical. Leur intersection avec les codes déjà sélectionnés dans le catalogue rattache **7 492 des 7 493 maladies ou sous-types actifs**, soit **19 239 des 19 240 libellés Orphanet**. Le code restant reste consultable sans domaine attribué. Les 23 166 rattachements correspondent à des appartenances multiples ; ils n’ajoutent aucun terme ni maladie.

Ces classifications couvrent notamment cardiologie, neurologie, génétique, maladies métaboliques, gastroentérologie, hépatologie, pneumologie, dermatologie, néphrologie, ophtalmologie, endocrinologie, hématologie, immunologie, rhumatologie, odontologie, ORL, infectiologie, oncologie, gynécologie et certaines chirurgies. Elles couvrent les **maladies rares de ces domaines**, pas l’ensemble du vocabulaire de chacune de ces spécialités. Les comptes exacts par classification, en codes et en libellés, figurent dans [le rapport de couverture](../lexique/coverage-041.json).

Pour les médicaments, les domaines suivent le premier caractère du code ATC fourni par RUIM. Les intitulés français du filtre traduisent les [14 groupes anatomiques principaux ATC](https://atcddd.fhi.no/atc_ddd_index/). Il s’agit de groupes pharmacologiques documentaires, pas d’indications déduites ni d’un rattachement exclusif à un médecin spécialiste. LAHN conserve ses chapitres officiels ; ADICAP conserve ses dictionnaires.

Il n’y a pas de quota artificiel de 5 000 ou 10 000 mots par spécialité. Par exemple, cette édition Orphanet donne 679 libellés en maladies cardiaques rares, 8 017 en maladies neurologiques rares et 14 648 en maladies génétiques rares. Les recouvrements sont conservés comme tels. Les anciens profils expérimentaux décrits dans [PROFILS.md](../lexique/PROFILS.md) utilisaient aussi des termes transversaux et apparentés ; leur taille ne doit pas être confondue avec une couverture officielle indépendante de chaque spécialité.

## Licences et provenance

RUIM, ADICAP et LAHN sont diffusés sous **Licence Ouverte 2.0**, qui autorise extraction et redistribution avec attribution et date. Les archives RUIM/ADICAP contiennent leur notice `leg/LO.md` ; l’endpoint de licence ANS indique que ces ressources ne sont pas protégées par un compte ou un accord de transfert. Aucun compte, aucune donnée personnelle ni aucun formulaire nominatif n’a été transmis pour l’acquisition. Orphanet est sous **CC BY 4.0**. Les attributions ANSM, ADICAP, DGOS, ANS et Orphanet/Inserm sont conservées dans les métadonnées et dans les résultats du catalogue. Aucune caution de ces organismes n’est revendiquée.

La BDPM avait été écartée du paquet historique. Ses [conditions actuelles](https://base-donnees-publique.medicaments.gouv.fr/telechargement) autorisent la réutilisation mais prévoient aussi des mises à jour, y compris entre deux publications ordinaires. Ce lot apporte les médicaments par **RUIM**, avec sa propre provenance et sa Licence Ouverte 2.0 ; il ne présente pas un instantané BDPM comme une base de disponibilité actualisée.

Le [MeSH français de l’Inserm](https://mesh.inserm.fr/telecharger-le-fichier-mesh/) est proposé sous **CC BY-NC 4.0** et sur demande. Il n’a pas été téléchargé ni intégré silencieusement à un paquet destiné à pouvoir être diffusé largement. Les six référentiels historiques, dont CCAM et NABM, restent inchangés. CIM, LOINC et SNOMED ne sont pas ajoutés dans ce lot. Le catalogue n’annonce donc pas une couverture exhaustive de toutes les terminologies de santé.

Les téléchargements et membres d’archives sont verrouillés par SHA-256 dans [sources-041.lock.json](../lexique/sources-041.lock.json) et [orphanet-domains.lock.json](../lexique/orphanet-domains.lock.json). Les deux nouveaux manifestes distinguent [les seules additions](../lexique/manifest-additions-041.json) du [catalogue complet](../lexique/manifest-essai-041.json). Le manifeste public historique n’a pas été réécrit. Les archives, CSV et SQLite générés ne sont pas stockés dans Git.

## Reconstruction pour le développement

L’utilisateur du ZIP Windows n’a aucune de ces commandes à exécuter : les données préparées accompagnent le logiciel et leur consultation fonctionne hors ligne. Pour reconstruire le complément, Python 3.11 ou plus récent suffit ; aucune bibliothèque d’IA n’est nécessaire.

```bash
python -m lexique.prepare_041 --downloads /chemin/sources --output /chemin/additions.sqlite --fetch
```

`--fetch` autorise explicitement l’acquisition des trois fichiers ANS, **26 398 989 octets au total**. Sans cette option, la commande ne fait aucun appel réseau et exige les fichiers déjà présents avec les empreintes attendues. Un téléchargement modifié, un membre ZIP dupliqué, un fichier tronqué ou une extraction CSV différente du manifeste sont refusés. La destination doit être neuve. Aucune extraction d’archive vers un chemin fourni par le ZIP n’est effectuée.

Les rattachements Orphanet se reconstruisent séparément depuis l’archive officielle de 8 758 578 octets déjà utilisée pour la nomenclature :

```bash
python -m lexique.orphanet_domains --archive /chemin/Orphanet_Nomenclature_Pack_FR.zip --output /chemin/orphanet-domains.json
```

Le JSON contient des triplets `source_id`, `code`, `domain`, ainsi que les attributions et empreintes. L’assemblage Windows les applique aux seuls termes existants de la source `orphanet-fr` ; l’identité des sources et les libellés sont préservés. Le manifeste complet décrit cet assemblage ; le préparateur des additions n’a pas besoin de reconstruire les six sources historiques.

Les contrôles ciblés sont exécutables sans télécharger de données :

```bash
python -m unittest lexique.test_catalogue lexique.test_prepare_041 lexique.test_orphanet_domains lexique.test_short_context
```

Le test facultatif des vraies sources est activé en définissant `NOTEVIVE_041_SOURCES` vers le dossier déjà téléchargé. Les contrôles portent notamment sur les noms et doses conservés, les statuts exclus, les domaines officiels, les doublons, les empreintes, les erreurs d’archive et l’absence d’écrasement d’une sortie existante.

## Expérience de contexte court, séparée du catalogue

Un essai distinct utilise [short_context.py](../lexique/short_context.py). Les candidats sont les libellés de substances RUIM retrouvés dans les **1 081 seuls textes d’entraînement**, par correspondance de phrase complète après normalisation des accents et de la casse. Aucun texte de validation, fichier audio ou résultat de transcription n’entre dans la sélection. Les termes sont classés par nombre de dictées d’entraînement où ils apparaissent, puis par ordre UTF-8.

Les nombres, unités, négations et marqueurs de latéralité sont exclus. Le préfixe de la liste s’arrête au premier dépassement de **64 `prompt_ids` Whisper**, avec un maximum de 16 termes ; il ne cherche pas un terme plus commode plus bas dans la liste. Le gel du 15 novembre contient **11 substances et 62 jetons**, parmi 89 candidats retrouvés. Le manifeste privé conserve le texte exact du contexte, ses empreintes, celles du tokenizer et les règles de sélection avant génération.

L’essai compare le même modèle de base, les mêmes audios et les mêmes réglages avec et sans ce contexte. Les résultats vérifient les noms, mais aussi les pertes de doses, fractions, négations, latéralités, associations et la durée de traitement. Le [rapport whisper.cpp](../p0/lexical_cpp_041.md) conserve les mesures et la décision : ce contexte est refusé, car le gain sur les médicaments du lot positif s’accompagne de régressions critiques. Aucune correction automatique après transcription ni injection de milliers de termes n’est mise en place.
