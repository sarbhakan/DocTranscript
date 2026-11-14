# Profils médicaux français pour NoteVive Mac

Le pack local contient **14 profils de 6 222 à 10 000 libellés**. Au total : 128 053 entrées dans les profils, **41 178 libellés distincts après dédoublonnage des graphies** à l’échelle du pack. Plusieurs disciplines peuvent rencontrer la même maladie, employer le même dispositif ou demander le même examen. Ces nombres décrivent la taille d’un catalogue, sans établir une couverture complète de la pratique de chaque spécialité.

| Profil | Consultables | Rattachement direct | Domaines voisins | Transversaux | Présélection pour la dictée |
| --- | ---: | ---: | ---: | ---: | ---: |
| Médecine générale | 10 000 | 6 934 | 0 | 3 066 | 121 |
| Cardiologie | 10 000 | 5 348 | 2 061 | 2 591 | 206 |
| Hématologie | 8 424 | 2 859 | 2 365 | 3 200 | 198 |
| Neurologie | 10 000 | 10 000 | 0 | 0 | 207 |
| Infectiologie | 8 813 | 3 315 | 2 298 | 3 200 | 185 |
| Oncologie | 8 619 | 3 828 | 1 591 | 3 200 | 191 |
| Ophtalmologie | 10 000 | 5 762 | 2 151 | 2 087 | 206 |
| Pédiatrie | 10 000 | 10 000 | 0 | 0 | 142 |
| Néphrologie | 8 114 | 2 615 | 2 299 | 3 200 | 198 |
| Médecine interne | 9 158 | 4 207 | 1 751 | 3 200 | 170 |
| Génétique médicale | 10 000 | 10 000 | 0 | 0 | 109 |
| Pneumologie | 6 222 | 1 709 | 1 313 | 3 200 | 207 |
| Dermatologie | 9 869 | 4 692 | 1 977 | 3 200 | 206 |
| Gastro-entérologie | 8 834 | 3 527 | 2 107 | 3 200 | 216 |

Le rattachement direct résulte d’une classification de maladies Orphanet, d’une branche de manifestations HPO, d’une association concentrée entre une manifestation et des maladies du domaine (hors fréquences explicitement nulles), ou d’une sélection d’actes, d’examens, de dispositifs et de produits par groupes documentés dans le générateur. Les domaines voisins incluent les manifestations observées dans ces maladies ou les classifications cliniques connexes. Le vocabulaire transversal comprend notamment des libellés issus des soins primaires et d’actes de biologie, ainsi que des manifestations rencontrées dans plusieurs maladies. Des regroupements par préfixes et mots clés ont été appliqués ; ils ne constituent pas une attribution officielle d’un acte ou d’un médicament à une spécialité. Un libellé peut compter dans plusieurs profils, et des synonymes d’un même concept peuvent chacun être consultables.

Cette édition privilégie les maladies rares et leurs manifestations, en particulier dans les profils Neurologie, Pédiatrie et Génétique médicale. Le profil de médecine générale est surtout constitué de libellés pharmaceutiques issus de Medic’AM (6 248), de manifestations HPO (3 066) et de plaintes ou diagnostics CISP-2 (686). Les noms de médicaments issus de Medic’AM couvrent la dispensation remboursée en officine de ville en 2025 ; les médicaments hospitaliers, non remboursés ou les introductions plus récentes peuvent manquer. Les libellés ne renseignent aucune indication ni posologie.

La présélection est bornée à 216 termes dans l’instantané. Elle est générée à partir des seules sources, sans lire de transcription ou de texte de référence du banc d’essai. Elle privilégie les formes courtes en choisissant parmi les libellés principaux de maladies, les manifestations observées dans les classifications, les actes et dispositifs courts, et parmi les libellés Cnam les plus courants pour la spécialité par classe ATC. Une forme contenant un nombre, des mots usuels de fraction, des unités, des négations ou de la latéralité ne peut pas entrer dans cette présélection. La liste totale reste consultable. Cette présélection intervient pendant le décodage lorsque l’aide est activée ; le modèle n’est ni entraîné ni réécrit. L’intérêt de l’activer se juge sur un essai à audio identique, en regardant aussi les erreurs critiques et la latence.

## Reproduction hors ligne

1. Préparer les entrées épinglées du [manifeste de l’essai public](manifest-essai-public.json), comme dans le [guide du catalogue](README.md#reproduire-linstantané-local). La nomenclature et les classifications Orphanet proviennent du même [paquet FR 2026](https://www.orphacode.org/data/packs/Orphanet_Nomenclature_Pack_FR.zip). La BDPM et la compilation préalable d’une base SQLite ne sont pas nécessaires. Le générateur n’indexe pas les libellés LPP.
2. Enregistrer dans `lexique/private/` les trois entrées suivantes : [Orphadata signes et symptômes, archive officielle figée](https://media.githubusercontent.com/media/Orphanet/Orphadata_aggregated/c12ffdba7dd5b8ce0b325ac04e6bfec33cfe33ec/Rare%20diseases%20with%20associated%20phenotypes/fr_product4.xml) sous `fr_product4.xml`, [HPO v2026-09-01, OBO français](https://github.com/obophenotype/human-phenotype-ontology/releases/download/v2026-09-01/hp-fr.obo) sous `hp-fr.obo`, [Medic’AM par classe ATC, cumul 2025](https://www.assurance-maladie.ameli.fr/sites/default/files/2025_medic-am-par-classe-atc_cumul-annuel.zip) sous `2025_medic-am-par-classe-atc_cumul-annuel.zip`. Si le SHA‑256 diffère du [générateur](specialty_profiles.py), récupérer l’instantané attendu ou préparer une nouvelle édition à contrôler ; ne pas ignorer l’écart.
3. Depuis la racine du dépôt, avec Python 3.12 :

```sh
python3 -m lexique.specialty_profiles \
  --phenotypes lexique/private/fr_product4.xml \
  --hpo lexique/private/hp-fr.obo \
  --medicam lexique/private/2025_medic-am-par-classe-atc_cumul-annuel.zip \
  --with-provenance --output lexique/private/profils-fr
cp lexique/NOTICE-profils.md lexique/private/profils-fr/SOURCES.md
NOTEVIVE_PROFILES_DIR=lexique/private/profils-fr python3 -m unittest lexique.test_specialty_profiles
```

Les fichiers d’entrée sont vérifiés avant lecture. La sortie figée `profiles.json` a pour SHA‑256 `8929b965a9053972832c89ae1a13908525e251758ec9b0fda3d4ac95bb4cf18c`. Elle contient les libellés, l’ordre des présélections, les règles de regroupement et les sources. Pour l’audit, `--with-provenance` crée aussi `provenance.tsv` : chaque ligne donne le profil, le libellé, la source, le code d’origine, la catégorie, la portée et la présence dans la présélection. Pour un doublon délibérément rapproché (casse, accents, apostrophe), le TSV décrit le représentant retenu. Les classements se fondent sur les affiliations des sources, sans compte ni montant de remboursement dans la sortie. La [notice d’attribution](NOTICE-profils.md) accompagne le pack. La redistribution publique de cet instantané expérimental reste à vérifier, en particulier pour les conditions exactes de réutilisation du fichier Medic’AM par classe ATC.

## Compléter la couverture des médicaments hospitaliers

Le [Référentiel unique d’interopérabilité du médicament, RUIM](https://smt.esante.gouv.fr/terminologie-ref_interop_med/) est publié par l’ANS et l’ANSM sous Licence Ouverte 2.0. L’édition indiquée est 2026-10-01 en CSV et OWL. Il couvre les spécialités autorisées ou enregistrées en France, dont les médicaments en accès précoce ou compassionnel. La [fiche technique](https://smt.esante.gouv.fr/fiche-ruim-detail/) documente les noms de gamme, les libellés et synonymes de substances, le code CIS, le code ATC et les liens vers les unités communes de dispensation. Pour une intégration suivante, privilégier les noms de gamme et les libellés de substances tels qu’ils sont fournis ; ne pas découper les formes ou doses depuis les dénominations de présentation. Réserver les noms archivés à la recherche et faire vérifier les affectations par spécialité, notamment lorsque l’ATC ne reflète pas tous les usages.

Le [codage UCD de la Cnam](https://www.data.gouv.fr/datasets/codage-nomenclature-medicament-ucd) sous Licence Ouverte 2.0 complète cette source pour les listes hospitalières T2A et rétrocession. Il est distinct du [référentiel CIP–UCD du Club Inter Pharmaceutique](https://smt.esante.gouv.fr/terminologie-cip_ucd/), soumis à ses propres conditions. La [série Cnam Retroced’AM](https://www.assurance-maladie.ameli.fr/etudes-et-donnees/medicaments-retrocession-hospitaliere-retrocedam) associe UCD et ATC5 et peut fournir un signal de fréquence pour les médicaments délivrés aux patients ambulatoires par une pharmacie hospitalière. Elle ne recense pas l’ensemble des médicaments administrés aux patients hospitalisés. Ces trois sources n’ont pas été ajoutées au pack figé de l’essai.
