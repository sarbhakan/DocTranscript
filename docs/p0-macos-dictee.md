# P0 · Dictée médicale sur Mac

Voir aussi le [comparatif direct Whisper–UltiMed et la décision d’intégration](p0-choix-moteur.md). Cette page conserve les résultats du premier essai Mac.

## Essai au microphone

Sur NoteVive 0.1.3, une dictée fictive a été lue dans le microphone du Mac. Des mots provisoires sont apparus pendant la parole. Après « Arrêter », le brouillon a été enregistré. Après avoir quitté complètement l’application, l’avoir rouverte et avoir rouvert la note, le texte était identique au brouillon final, erreurs comprises.

| Élément | Texte |
| --- | --- |
| Référence | Pas de douleur à la cheville droite. La gêne concerne la cheville gauche depuis cinq jours. |
| Brouillon enregistré | PAS DE DOULEUR LA CHEVILLE DROITE LA GÊNE CONCERNE LA CHEVILLE GAUCHE DEPUIS CINQ JOURS |

Le moteur a omis « à » et n’a pas produit la ponctuation. La négation, les deux côtés et la durée ont été conservés dans cet essai. Le parcours micro → aperçu → sauvegarde → réouverture est vérifié pour cette note. La latence n’a pas été chronométrée. Un seul exemple ne permet pas de conclure sur la fidélité médicale. Les erreurs signalées lors d’un autre essai ne sont pas évaluables sans connaître la phrase prononcée.

Le Mac utilise le [Zipformer français de Sherpa](https://huggingface.co/shaojieli/sherpa-onnx-streaming-zipformer-fr-2023-04-14), issu de Common Voice, avec un [décodage sans mots-clés](../app/macos/Recognition.swift). Le [catalogue de Windows](../lexique/README.md) est consultable dans une fenêtre séparée et n’alimente pas [son moteur](../app/windows/engine.cpp). Il n’est pas embarqué sur Mac. L’ajout de termes au catalogue seul ne changera donc pas le résultat actuel.

## Premier comparatif local sur voix synthétique

Neuf phrases de développement (`micro-cheville`, `dev-01`, `dev-02`, `dev-03`, `dev-10`, `dev-14`, `dev-15`, `dev-17`, `dev-20`) ont été lues par la voix française Jacques de macOS à 170 mots/min. Les WAV mono PCM16 à 16 kHz, précédés de 350 ms et suivis de 800 ms de silence, ont été rejoués à l’identique sur les deux moteurs. Le Zipformer de l’application a été appelé avec `--self-test`. Whisper a traité chaque WAV en une passe finale, en français, sur CPU avec quatre fils, sans contexte de la dictée précédente ni lexique. Les empreintes et paramètres du pack figurent dans le [banc](../p0/bench/README.md).

| Mesure exploratoire | Zipformer livré | Whisper large-v3-turbo Q5_0 |
| --- | ---: | ---: |
| Erreurs lexicales sur 205 mots de référence | 89 (43,4 %) | 24 (11,7 %) |
| Sorties finales non vides sur deux contrôles sans parole | 0/2 | 2/2, dont une phrase sur silence numérique et une ponctuation sur bruit |

Whisper a correctement produit « fibrillation atriale » et distingué « clonazépam » de « clorazépate », mais a encore déformé « amiodarone », « amlodipine », « amoxicilline » et « budésonide ». Une conversion typographique comme « cinq » → « 5 » compte dans le WER, sans erreur de sens. Ce criblage n’est ni un test de voix humaines ni un résultat clinique. Le décodage Whisper, modèle déjà chargé, a pris 3,44 s en médiane pour des fichiers de 6,5 à 11,6 s environ ; il ne mesure ni un aperçu en direct ni un temps d’affichage. L’ajout de texte sur silence bloque toute intégration de cette configuration sans contrôle de présence de parole validé, y compris sur les débuts et fins de mots.

## Contrôle sur des voix humaines

Même comparaison sur dix prises de dix médecins de [PxCorpus/PxSLU v4](https://zenodo.org/records/10080490) (Kocabiyikoglu et coll., CC BY 4.0, exercice de prescription simulée). Tirage à graine 6084 : une prise par médecin, entre 3 et 15 s, avec un médicament et une dose annotés. Indices dans `paths.txt`, en partant de zéro : `558, 241, 178, 574, 1667, 727, 813, 51, 785, 684`. Les WAV ont reçu un en-tête PCM standard sans changement des échantillons. Les deux moteurs ont reçu le même audio ; aucun lexique n’a été fourni et le détecteur de parole Whisper était désactivé. Résultats contre la transcription publiée : **62 écarts sur 125 mots (49,6 %) avec Zipformer ; 34 sur 125 (27,2 %) avec Whisper**. Ces taux incluent les hésitations et les différences de notation des nombres. Whisper retrouve « Tofranil » et « Amoxicilline » dans certaines prises, mais transcrit par exemple « Flagyl » en « Flagile ». Dix prescriptions simulées ne couvrent ni la dictée libre ni les différentes spécialités. Les voix et les sorties individuelles restent hors du dépôt.

## Détection de parole

Le [pack Whisper avec Silero 6.2.0](../p0/bench/README.md#candidat-whisper--décodage-en-fin-de-phrase) a été rejoué dans le banc NDJSON : **aucun texte sur quatre WAV de silence ou bruit artificiel**, et les trois phrases de synthèse ont toutes produit un résultat. Les deux contrôles exploratoires initiaux ont aussi donné une sortie vide avec Silero. Sur les dix prises humaines, aucune sortie n’était vide et le total est passé de 34 à 32 écarts sur 125 mots (25,6 %), avec une prise moins bien reconnue. Ce contrôle ne prouve pas la robustesse au bruit d’un cabinet ni la conservation des mots brefs, en particulier une négation à l’attaque d’une phrase.

## Configuration à qualifier

[Whisper large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo) avec [whisper.cpp](https://github.com/ggml-org/whisper.cpp) et les [poids Q5_0 épinglés](https://huggingface.co/ggerganov/whisper.cpp/commit/98aa99a0a9db05ae2342309f5096248665f7cba3), environ 547 Mio sur disque, est le premier candidat. Évaluer un seul modèle chargé, avec aperçu séparé et stabilisation à la pause ou à l’arrêt. Le temps de réponse réel et le pic de mémoire restent à mesurer sur le PC Windows de 8 Go sans GPU dédié ; le Whisper Small Q5_1 multilingue du [banc P0](../p0/README.md) sert de comparaison si Turbo dépasse le budget. Ce sont des comparateurs du banc : une seule configuration qualifiée sera distribuée.

[Parakeet UltiMed INT8](https://huggingface.co/Olicorne/parakeet-tdt-0.6b-v3-ultra-UltiMed-onnx) sert de référence médicale après la fin de la phrase, sans remplacement de mots. L’auteur rapporte un passage de 4,9 % à 2,3 % d’erreurs de caractères sur quinze enregistrements lus par une seule personne, à précision FP32 et sans indices ni substitutions. Le résultat justifie un essai indépendant, pas une promesse de gain sur les voix de cabinet ou sur l’export INT8. Les [limites documentées de Whisper](https://github.com/openai/whisper/blob/main/model-card.md) incluent l’ajout possible de mots jamais prononcés. La [dictée de ChatGPT](https://help.openai.com/en/articles/12168547-voice-dictation-faq) envoie quant à elle l’audio à un service distant ; son délai est une référence d’usage, pas une mesure de faisabilité hors ligne.

## Conditions pour changer de moteur

1. Rejouer les mêmes dictées fictives enregistrées par plusieurs personnes sur le moteur actuel et les candidats. Séparer le test du microphone de la comparaison des modèles. Inclure des phrases courtes et longues, du français courant, des pauses, du silence et du bruit.
2. Compter séparément les erreurs sur les médicaments, doses, unités, négations, latéralités et durées, y compris les ajouts. Mesurer le délai jusqu’au premier mot correct et jusqu’au texte stable, puis le pic mémoire sur les postes cibles. Si un mode par phrase s’avère plus fidèle, chiffrer son délai avant de modifier les [cibles P0](feuille-de-route.md#critères-mesurables-proposés).
3. Essayer ensuite un [lexique court par spécialité](adaptation-lexicale.md) sur le meilleur candidat, avec et sans indices sur les mêmes WAV. Garder le catalogue large pour la consultation et la préparation du corpus. Envisager un ajustement des poids si des erreurs récurrentes subsistent : il faut alors des voix volontaires, des phrases fictives et leurs transcriptions vérifiées, avec un test réservé à des locuteurs et des phrases absents de l’entraînement.
