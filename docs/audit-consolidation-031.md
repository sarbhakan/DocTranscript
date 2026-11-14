# Audit et consolidation de NoteVive 0.3.1

Travaux du 14 novembre 2026, à partir de la préversion Windows 0.3.0. Cette page distingue les correctifs de fonctionnement, les mesures de reconnaissance et la préparation d’un entraînement. Les poids du modèle distribué ne sont pas entraînés par ce lot.

## Ce qui est consolidé

Le produit reste une seule application Windows : Whisper Large-v3 Turbo Q5_0, quatre fils de calcul CPU, Silero et une pause de 576 ms. Les notes, dossiers, sous-dossiers, recherche, tris et sauvegarde locale sont conservés. Les comparateurs du banc ne deviennent pas des éditions supplémentaires de NoteVive.

| Problème vérifié | Correction | Vérification et limite |
| --- | --- | --- |
| Un état aléatoire du décodeur pouvait dépendre des dictées précédentes | Rétroport ciblé du correctif officiel Whisper ; sources avant/après verrouillées et provenance dans le paquet | Contrôle de répétition reproduit sur Mac, puis comparaison avec les paramètres habituels. Pas de promesse d’identité entre processeurs. |
| L’état « micro coupé » attendait le retour du calcul ASR | La capture signale directement l’ouverture et la fermeture confirmées ; les écritures du protocole restent sérialisées | Scénarios de fermeture après arrêt, annulation et arrêt automatique. La capture physique sur Windows reste à essayer. |
| Un résultat complet déjà dans le canal pouvait être perdu à l’expiration du délai | Lecture limitée aux octets disponibles à cette échéance ; les arrivées suivantes ne prolongent pas l’attente | Tests de trame complète, trame tronquée et moteur bloqué. Le délai reste borné. |
| Un texte invalide ou une insertion tronquée pouvait atteindre la sauvegarde | Validation UTF-16, vérification du texte réellement inséré, restauration du texte précédent si possible | Les tests du protocole couvrent les caractères invalides. Le cas de manque de mémoire dans le contrôle EDIT reste à tester en interface. |
| Une file de messages Windows saturée pouvait retarder le traitement d’un événement | Réveil regroupé et surveillance périodique pendant la dictée | Compilation et recette d’interface automatisée ; aucun nouveau service réseau. |
| Certains contrôles de doses pouvaient afficher un faux succès | Contrôles des signes, unités, concentrations, durées, fractions et négations ajoutées ; mesure d’association médicament–dose distincte | Cas adversariaux automatisés. Il s’agit de contrôles ciblés du banc, pas d’un validateur clinique du texte saisi par les médecins. |

Si un passage ne tient pas dans l’éditeur, il reste affiché à part et **n’est pas considéré comme enregistré**. Une fermeture déjà demandée est suspendue. L’application avertit avant une action qui effacerait ce passage. Cette récupération demeure en mémoire : elle n’est pas une sauvegarde résistante à une coupure de courant. Une insertion partielle suivie d’une restauration ne peut plus être réintroduite par l’opération Annuler. Si la restauration échoue, la sauvegarde et le classement de la note sont suspendus jusqu’à correction du corps du texte.

La bibliothèque continue d’utiliser DPAPI. Les notes restent liées au compte et au poste Windows ; cette évolution n’ajoute pas une sauvegarde portable vers un autre PC.

## Réemploi de technologies existantes

La veille a examiné les changements amont jusqu’à [whisper.cpp 1.9.5](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5). Le passage global à cette version changerait aussi GGML et les conditions de compilation. Aucun gain médical mesuré ne justifie ici de remplacer toute la chaîne. Le correctif directement pertinent est [6d0ed914](https://github.com/ggml-org/whisper.cpp/commit/6d0ed914991cac42ace012a05588880801831343), issu de la [reproduction amont #4025](https://github.com/ggml-org/whisper.cpp/pull/4025).

Ce correctif remet à zéro le générateur aléatoire du décodeur 0 à chaque appel. Il évite que le repli à température positive réutilise l’état d’un appel précédent. Le contexte textuel des notes reste désactivé. La [construction Windows](../app/windows/whisper-build.md) vérifie les empreintes et refuse les anciennes attestations sans ce correctif, même si la DLL annonce encore « 1.8.5 ».

Le contrôle ciblé local force temporairement ce chemin de repli : trois passages du même audio ont donné deux textes distincts avant correction et un seul texte répété après. Ce réglage forcé n’est pas celui de l’application. Le [rapport du comparatif](../p0/decoder_consolidation.md) décrit séparément les mesures de fidélité avec les paramètres habituels et les limites d’interprétation.

La comparaison de 85 mêmes enregistrements est terminée : le correctif retenu produit exactement les mêmes sorties que le profil baseline sur ces 85 fichiers. Le profil de décodage plus large est écarté : il gagne certains éléments mais perd aussi un nom de médicament et une association médicament–dosage. Les variantes sont comparées sur les mêmes audios, sans recevoir leur référence. Un changement qui crée une nouvelle erreur de dose, fraction ou négation ne peut pas être retenu au seul motif qu’il reconnaît davantage de termes rares.

Les grandes listes de corrections automatiques d’UltiMed n’ont pas été importées dans le produit. Leur [documentation](https://huggingface.co/Olicorne/parakeet-tdt-0.6b-v3-ultra-UltiMed-onnx/blob/main/regex-fixes/README.md) explique qu’elles ont été constituées à partir d’erreurs incluant les jeux de test. Elles ne fournissent pas une validation indépendante et une substitution silencieuse peut changer le sens médical.

## Préparation concrète de l’adaptation médicale

Le nouvel [outil de préparation PxCorpus](../p0/training/README.md) a réellement produit un corpus local à partir de l’archive v4 autorisée, puis une seconde vérification a comparé les lignes exportées à l’archive d’origine. L’export reprend les références `seq.in`, issues de transcriptions automatiques ensuite vérifiées humainement selon les auteurs ; aucune sortie de NoteVive n’est utilisée pour les fabriquer ou les corriger.

| Partition préparée | Enregistrements | Voix distinctes | Durée |
| --- | ---: | ---: | ---: |
| Entraînement, non exécuté | 1 081 | 32 | environ 2 h 15 |
| Validation de développement | 282 | 8 | environ 27 min |

Les partitions originales d’entraînement et de développement partageaient 39 locuteurs. L’outil refait la séparation par voix, retire les références communes et les doublons audio et protège les 570 prises de 14 voix de médecins déjà réservées au test source, dont les cas utilisés par notre banc. Le [rapport agrégé](../p0/training/pxcorpus_v4_report.json) donne les exclusions et les empreintes ; les WAV, transcriptions et références d’exclusion restent en local.

Ce corpus est limité aux prescriptions simulées. Les voix retenues pour l’adaptation proviennent des catégories « expert » et « non-expert » de la source ; les médecins sont dans la réserve. Il ne représente pas l’ensemble des consultations ni des spécialités. Le recouvrement éventuel avec le préentraînement des modèles est inconnu, et la validation de développement ne remplace pas un essai inédit avec un praticien.

[PxCorpus v4](https://zenodo.org/records/10080490) est distribué sous CC BY 4.0 ; l’export inclut l’attribution et décrit les transformations. Corti et PARROT ne sont pas utilisés dans cet outil. Aucun dictionnaire de milliers de mots n’est présenté comme un entraînement acoustique.

La [note sur l’entraînement local](entrainement-local.md) précise ce qui est techniquement plausible sur le M1 Pro et ce qui reste à démontrer. Il faut des poids entraînables, des essais de calcul des gradients, une adaptation limitée puis une réévaluation après export et quantification. Le modèle Q5_0 actuel demeure la référence tant que ce cycle ne prouve pas une amélioration.

## Vérification indépendante et limites restantes

Les rôles ont été répartis entre audit du décodage, corrections Windows, contrôles médicaux du banc et préparation des données. La seconde revue a notamment trouvé puis fait corriger trois chemins de récupération : classement d’une note au texte tronqué, fermeture différée avant relecture du passage rejeté, et annulation pouvant réintroduire le fragment.

Les 56 tests du banc et les 11 tests exécutés du catalogue passent localement (un test optionnel du catalogue n’est pas exécuté faute du répertoire de fixture configuré). Le [candidat Windows](https://github.com/sarbhakan/DocTranscript/actions/runs/43629555263) passe tous les contrôles obligatoires, notamment le parcours d’interface et les trois fixtures audio. Le nom exact « Imovane » reste manquant dans une fixture. Les tests locaux et la CI vérifient des propriétés déterminées ; ils ne certifient pas l’aptitude à dicter une note de soin. WinMM peut perdre des échantillons lorsqu’il manque de tampons disponibles, sans fournir de signal complet de discontinuité. Les contrôles existants interrompent certains cas détectés, sans établir « zéro perte » sur tout matériel. La [documentation WinMM](https://learn.microsoft.com/en-us/windows/win32/api/mmeapi/nf-mmeapi-waveinstart) explique cette limite. Un poste lent peut aussi accumuler plus de calcul que le budget de finalisation ne permet d’en traiter.

Les étapes qui demandent encore des preuves sont les essais au microphone sur les deux PC physiques, dont celui de 8 Go, les dictées inédites relues par un praticien, la restauration de sauvegarde sur un autre poste et la qualification de l’usage professionnel. Les essais publiés restent réservés aux données fictives. L’amélioration de robustesse, la reproductibilité du calcul et la précision médicale sont suivies séparément.

## Publication vérifiée

La [préversion 0.3.1](https://github.com/sarbhakan/DocTranscript/releases/tag/v0.3.1-essai) est publiée depuis `8e9693a`. Le [workflow final](https://github.com/sarbhakan/DocTranscript/actions/runs/43632194234) a reconstruit, extrait et testé ce ZIP avant envoi. Le fichier SHA-256 téléchargé correspond au digest de l’asset GitHub. Les [mesures du paquet](../p0/windows_consolidation.json) sont ajoutées sous `release_validation`, sans remplacer celles du candidat. Les versions et leur portée sont rappelées dans le [guide pas à pas](guide-essai-windows.md).
