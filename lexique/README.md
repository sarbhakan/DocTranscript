# Catalogue médical local · NoteVive

Ce catalogue d’ingénierie indexe des libellés de référence français pour préparer la relecture et, si les essais le justifient, de petites sélections de vocabulaire par spécialité. Il conserve le code, le texte original, la catégorie et la provenance de chaque entrée. Pour Orphanet, il distingue le libellé principal des synonymes. Les accents, ligatures et élisions sont traités dans l’index de recherche ; l’affichage restitue les libellés de la source.

Le catalogue ne reçoit aucune note, aucun enregistrement et aucun identifiant patient. Les notes de l’application sont stockées séparément. Ce catalogue ne constitue ni un outil de diagnostic, de prescription ou de facturation, ni un modèle entraîné, ni une preuve de couverture clinique d’une spécialité. Un même terme peut avoir plusieurs codes ou provenances ; les statistiques comptent les libellés indexés et conservent ces distinctions.

L’essai Mac utilise un pack distinct de [14 profils médicaux français](PROFILS.md), avec un index consultable hors ligne et une présélection limitée de termes pour tester l’aide à la dictée. Le guide détaille la couverture, la génération et la provenance par libellé.

## Catalogue Windows enrichi 0.4.1

Le catalogue préparé pour le paquet **0.4.1** contient **100 175 entrées**, soit **99 192 libellés littéralement distincts**. Il apporte **28 785 libellés distincts absents de l’ancien catalogue**. La date de revue des nouvelles sources est le 15 novembre 2026. L’état de publication et le lien du ZIP effectivement disponible sont indiqués dans le [guide d’essai Windows](../docs/guide-essai-windows.md) ; les instructions historiques ci-dessous restent disponibles pour reproduire les anciennes éditions.

| Complément officiel | Entrées ajoutées | Édition |
| --- | ---: | --- |
| RUIM ANSM : noms complets de spécialités pharmaceutiques actives | 13 834 | 2026-10-01 |
| RUIM ANSM : substances et synonymes français | 5 201, pour 3 461 codes de substances | 2026-10-01 |
| RUIM ANSM : formes pharmaceutiques | 360 | 2026-10-01 |
| RUIM ANSM : voies d’administration | 86 | 2026-10-01 |
| ADICAP : anatomopathologie et topographie | 9 472 | 2024-10 |
| LAHN DGOS : actes de biologie hors nomenclature | 705 | 2026-04, FHIR history 10 |

Les **12 déclarations de sources** comprennent les six historiques et six nouvelles extractions provenant de **trois référentiels**, RUIM étant scindé en quatre ensembles. Les dosages contenus dans les noms officiels des médicaments sont conservés ; aucune posologie n’est inventée. Un statut actif dans RUIM ne garantit pas la disponibilité en pharmacie. RUIM, ADICAP et LAHN sont sous Licence Ouverte 2.0, avec attribution et date dans le catalogue. Le [MeSH français](https://mesh.inserm.fr/telecharger-le-fichier-mesh/), sous CC BY-NC 4.0, n’est pas intégré à ce paquet.

Les classifications officielles Orphanet ajoutent **33 domaines** à **7 492 des 7 493 codes** de maladies rares ou sous-types déjà présents. Elles ne créent aucun nouveau libellé. Avec les domaines RUIM, LAHN, ADICAP et médecine générale, le catalogue assemblé possède **75 domaines effectifs**. Les appartenances se recouvrent : leurs nombres ne s’additionnent pas en maladies distinctes. Il n’y a pas de quota artificiel de 5 000 ou 10 000 mots par spécialité, ni de promesse de couverture de toute la médecine.

Dans le glossaire de l’application, rechercher un mot puis choisir, si utile, un domaine et un type de terme. La consultation fonctionne hors ligne. Le code, la source et l’édition permettent de vérifier l’origine d’un résultat. Le catalogue n’injecte pas automatiquement ses milliers de termes dans la dictée et ne remplace aucun mot silencieusement. Un [essai séparé de contexte court](../docs/lexique-041.md#expérience-de-contexte-court-séparée-du-catalogue), choisi dans les seuls textes d’entraînement, est évalué avant toute éventuelle adoption.

Les [détails de provenance, transformations et reconstruction](../docs/lexique-041.md) expliquent les limites des éditions et les contrôles. Le [manifeste complet 0.4.1](manifest-essai-041.json), le [manifeste des seules additions](manifest-additions-041.json), le [verrou des téléchargements](sources-041.lock.json), les [rattachements Orphanet](orphanet-domains.lock.json) et le [rapport de couverture](coverage-041.json) sont conservés dans Git. Les archives, les CSV et les SQLite générés restent hors Git.

Pour le développement uniquement, reconstruire les additions depuis les fichiers officiels déjà téléchargés :

```text
python -m lexique.prepare_041 --downloads lexique/private/041-sources --output lexique/private/additions-041.sqlite
python -m lexique.orphanet_domains --archive lexique/private/sources/Orphanet_Nomenclature_Pack_FR.zip --output lexique/private/orphanet-domains-041.json
python -m unittest lexique.test_catalogue lexique.test_prepare_041 lexique.test_orphanet_domains lexique.test_short_context
```

L’option explicite `--fetch` de `prepare_041` acquiert les trois fichiers ANS si nécessaire. Sans elle, le préparateur ne fait aucun appel réseau. Les sorties doivent être neuves. L’assemblage du catalogue historique, des additions et des domaines est réalisé par [la préparation Windows](../app/prepare_windows.py). Les personnes qui utilisent le ZIP n’ont aucune de ces commandes à exécuter.

## Catalogue public historique, jusqu’à l’essai Windows 0.4.0

Le paquet historique embarque **70 517 libellés provenant de six référentiels**. Il exclut les dénominations et substances de la BDPM : les conditions de réutilisation demandent de suivre aussi les corrections entre publications, comme l’indique le [portail BDPM](https://base-donnees-publique.medicaments.gouv.fr/telechargement). Les six référentiels du [manifeste public historique](manifest-essai-public.json) restent inchangés dans le complément 0.4.1. Ce dernier ajoute les médicaments par RUIM, avec sa propre provenance. Le contenu du catalogue historique ne modifie pas les résultats de dictée.

Préparer les six sources selon les étapes ci-dessous, en sautant le téléchargement des deux fichiers BDPM. Compiler ensuite uniquement le manifeste public :

```text
python -m lexique build --manifest lexique/manifest-essai-public.json --db lexique/private/catalogue-essai-public.sqlite
python -m lexique stats --db lexique/private/catalogue-essai-public.sqlite
```

## Instantané interne vérifié le 13 novembre 2026

| Référentiel | Entrées indexées | Sélection |
| --- | ---: | --- |
| BDPM | 19 749 | 15 799 dénominations de spécialités pharmaceutiques et 3 950 libellés de substances actives. Des médicaments retirés, suspendus ou non commercialisés peuvent figurer dans le fichier. |
| Orphanet FR 2026 | 19 240 | Libellés principaux et synonymes français de 7 493 pathologies rares ou sous-types actifs. |
| CCAM v84.00 | 8 558 | Libellés d’actes, dont gestes, interventions et techniques d’imagerie, sans règles ni validité de facturation acte par acte. |
| NABM V105 | 987 | Libellés d’actes de biologie, sans résultats ni valeurs de référence. |
| CISP-2 2019-05 | 686 | 320 motifs ou plaintes et 366 libellés de la composante diagnostics de soins primaires. |
| EMDN FR v1.2 | 8 149 | Types de dispositifs, sans marques. Édition française dont le contenu est daté de 2022 ; elle ne représente pas l’édition européenne 2026. |
| LPP 00909 | 32 897 | Noms courts de produits et prestations (dont dispositifs) valides selon l’archive au 9 novembre 2026. |
| **Total** | **90 266** | Triplets source, code et libellé ; les recouvrements entre sources sont conservés. |

## Reproduire l’instantané local

Depuis la racine de DocTranscript, utiliser Python 3.12 avec SQLite FTS5 (même version de Python que le [banc P0](../p0/README.md)). `lexique/private/` est ignoré par Git : y ranger les fichiers téléchargés et la base produite. Les opérations ci-dessous s’exécutent sans réseau après l’acquisition. Sur Windows, travailler dans un dossier **NTFS local** : le compilateur publie la base terminée par lien physique dans le même volume, sans écraser une base existante. Employer `python` ou le chemin vers le Python 3.12 sélectionné si la commande diffère selon le poste.

1. Depuis les producteurs, enregistrer les deux fichiers de la [BDPM](https://base-donnees-publique.medicaments.gouv.fr/telechargement) (`CIS_bdpm.txt` et `CIS_COMPO_bdpm.txt`) et l’[archive française Orphanet 2026](https://www.orphacode.org/data/packs/Orphanet_Nomenclature_Pack_FR.zip) dans `lexique/private/sources/`.
2. Enregistrer dans `lexique/private/` les exports FHIR versionnés de la [CCAM](https://smt.esante.gouv.fr/fhir/CodeSystem/terminologie-ccam/_history/11?_format=json) (`ccam-v84.00.fhir.json`), de l’[EMDN](https://smt.esante.gouv.fr/fhir/CodeSystem/terminologie-emdn/_history/3?_format=json) (`emdn-v1.2.fhir.json`), de la [NABM](https://smt.esante.gouv.fr/fhir/CodeSystem/terminologie-nabm/_history/19?_format=json) (`nabm-v105.fhir.json`) et de la [CISP-2](https://smt.esante.gouv.fr/fhir/CodeSystem/terminologie-cisp/_history/3?_format=json) (`cisp2-2019-05.fhir.json`). Suivre le [protocole LPP](../docs/referentiels-medicaux.md#import-lpp-vérifié-localement) pour acquérir l’archive CNAM 00909 et générer le CSV, en conservant sa date de sélection. Les notices et limites sont dans l’[inventaire des sources](../docs/referentiels-medicaux.md).
3. Préparer les formats d’import, compiler et interroger la base :

```text
python -m lexique.orphanet --source lexique/private/sources/Orphanet_Nomenclature_Pack_FR.zip --output lexique/private/sources/ORPHAnomenclature_fr_2026.xml
python -m lexique.ccam --source lexique/private/ccam-v84.00.fhir.json --output lexique/private/ccam-v84.00.csv
python -m lexique.cisp --source lexique/private/cisp2-2019-05.fhir.json --output lexique/private/cisp2-2019-05.csv
python -m lexique.smt emdn --source lexique/private/emdn-v1.2.fhir.json --output lexique/private/emdn-v1.2.csv
python -m lexique.smt nabm --source lexique/private/nabm-v105.fhir.json --output lexique/private/nabm-v105.csv
python -m lexique build --manifest lexique/manifest-2026-11-13.json --db lexique/private/catalogue-2026-11-13.sqlite
python -m lexique stats --db lexique/private/catalogue-2026-11-13.sqlite
python -m lexique search --db lexique/private/catalogue-2026-11-13.sqlite --categorie examen hemoglobine
python -m unittest lexique.test_catalogue
```

Les sources à URL fixe peuvent être remplacées par le diffuseur. Le [manifeste](manifest-2026-11-13.json) épingle les octets effectivement testés. Si une empreinte diffère, examiner la nouvelle édition, sa notice et ses différences de schéma et de contenu ; ne pas remplacer silencieusement l’empreinte. Les empreintes sont des contrôles d’identité entre les fichiers revus et transférés. Elles ne remplacent ni la vérification des droits ni la signature d’un pack. `search` ouvre en lecture seule un catalogue préparé localement et de provenance connue ; avant d’accepter un pack de production, vérifier sa signature hors ligne et prévoir un retour à l’édition précédente. Le JSON de sortie encode les caractères Unicode en séquences échappées pour fonctionner aussi sous redirection Windows ; en PowerShell, `| ConvertFrom-Json` restitue les caractères.

## Ajouter une source ou une spécialité

Un export CSV déclaré et revu peut utiliser les colonnes `code,libelle,categorie,specialites` dans cet ordre, avec des identifiants de spécialité minuscules séparés par `|`. Laisser la spécialité vide si elle n’est pas établie. Une classification anatomique ou tarifaire ne justifie pas à elle seule de l’inférer. Une source entre dans le manifeste avec son édition, son URL, sa notice, son attribution, sa date qualifiée, son format et son SHA-256. Une extraction de libellés ne transfère pas automatiquement les droits des alignements, variantes ou autres contenus du producteur. Conserver et relire les variantes orales séparément des libellés officiels. Le filtre de spécialité renvoie seulement les entrées explicitement étiquetées ; chercher sans filtre pour parcourir le référentiel entier. La recherche initiale ne rapproche pas les graphies de sigles ponctués (`E.C.G.`) et continus (`ECG`).

La prochaine étape est de relever les erreurs sur les dictées fictives, puis de mesurer [avec et sans un petit lexique](../p0/lexical_experiment.md), sur le même moteur et les mêmes WAV. L’élargissement du catalogue et la validation de la reconnaissance sont deux mesures distinctes. Aucun terme n’est activé dans le décodeur par cette commande.
