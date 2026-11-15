# Contexte lexical court : essai apparié dans Whisper.cpp

Le catalogue médical sert à rechercher des termes. Cet essai séparé vérifie ce qui se passe si l’on donne aussi **11 noms de médicaments** au moteur comme contexte de reconnaissance. Les noms sont ceux de la sélection déjà figée à partir de Px `train` et des formes officielles RUIM, sans chiffres, doses, négations ni latéralité. Le lot d’écoute ne sert à choisir aucun des noms. Cette expérience ne modifie ni les poids ni l’application.

## Résultats

**Le contexte global n’est pas retenu.** Dans les 48 dictées de non-régression, il modifie 29 sorties et fait échouer au moins un contrôle critique jusque-là réussi sur 5 dictées. Il ne réémet aucun des 11 noms à tort sur ce petit lot, dont **0 sur 28 mentions annotées de médicaments** correspondent à la liste du contexte. La contre-épreuve positive ne peut pas effacer les régressions observées dans les dictées ordinaires.

| Contrôle | 32 dictées Px, sans → avec contexte | 16 dictées TTS, sans → avec contexte |
| --- | ---: | ---: |
| Erreurs de mots, total | 86/371 → 88/371 | 53/115 → 53/115 |
| Omissions de mots, alignement WER | 4 → 5 | 5 → 7 |
| Médicaments exacts, grille | 9/24 → 9/24 (1 récupéré, 1 perdu) | 4/4 → 4/4 |
| Associations médicament–dose | 5/16 → 5/16 (1 récupérée, 1 perdue) | 4/4 → 4/4 |
| Doses annotées | 42/46 → 43/46 | 8/8 → 8/8 |
| Fractions annotées | 3/3 → 3/3 | 4/4 → 4/4 |
| Ordre et nombre des valeurs attendues | 26/32 → 28/32 | 16/16 → 15/16 |
| Clauses exactes : négations et latéralités | aucune latéralité annotée ; 0/1 → 0/1 clause négative | 3/8 → 3/8 négations ; 1/10 → 1/10 latéralités |
| Délai médian par dictée, Mac | 3,15 s → 3,25 s | 3,16 s → 3,22 s |
| Délai P95 par dictée, Mac | 9,20 s → 9,43 s | 3,32 s → 3,71 s |

Dans le lot Px, le score des délais médicaux passe de 2/2 à 0/2 sur une seule dictée. Dans le lot TTS, deux sorties supplémentaires échouent au contrôle des marqueurs de négation, même si le nombre de clauses littéralement exactes reste stable. Les seuils littéraux demandent une relecture avant interprétation clinique. La durée totale de calcul augmente de 2,7 % sur Px et de 2,3 % sur TTS ; une passe par bras sur un Mac ne permet pas de généraliser ce petit écart de vitesse. Le P95 est le maximum observé quand il n’y a que 16 dictées.

Sur 1 s et 3 s de silence numérique, Silero ne déclenche aucun décodage dans les deux bras. En contournant volontairement Silero, le moteur produit un texte non médical identique dans chaque paire, sans aucun des noms suggérés. Ce dernier résultat confirme l’utilité de conserver le filtre vocal dans la chaîne mesurée ; il ne qualifie pas la tenue au bruit réel.

Sur les **11 phrases positives fictives**, chacune prononce l’un des noms fournis. Le contexte récupère 7 noms (2/11 → 9/11) et améliore le total des associations médicament–dose (2/11 → 7/11 : 6 gains et 1 perte). Il ne réémet pas de nom inattendu. Dans le même temps, les fractions passent de 11/11 à 9/11, les doses de 22/22 à 20/22, les clauses de négation de 7/11 à 5/11 et les latéralités de 3/6 à 2/6. Il y a 5 omissions de mots supplémentaires et au moins une perte critique sur 3 des 11 dictées. Plusieurs contrôles peuvent concerner la même erreur ; il ne faut pas additionner ces nombres pour estimer un nombre d’incidents. Le temps total augmente de 2,9 % (35,1 s → 36,1 s). Le gain de reconnaissance des noms est réel dans ce montage synthétique, mais il ne suffit pas à justifier son intégration.

Les compteurs complets, l’appariement des pertes et gains, les durées et les empreintes sont disponibles dans [l’agrégat du banc](lexical_cpp_041_result.json). Le catalogue reste disponible pour rechercher un terme ; aucune injection de ces noms n’est activée à la dictée.

## Méthode

- Moteur du même profil que NoteVive Windows : Whisper.cpp 1.8.5 avec le [correctif amont du générateur aléatoire](https://github.com/ggml-org/whisper.cpp/commit/6d0ed914991cac42ace012a05588880801831343), Large-v3 Turbo Q5_0, français, quatre fils CPU, recherche gloutonne avec repli amont, contexte audio complet et Silero GGML à la pause de 576 ms. L’exécution est sur Mac Apple M1 Pro, 16 Go, avec les bibliothèques GGML locales et les accélérations CPU du Mac ; les temps ne valent pas pour Windows.
- Une seule instance chaude. Les deux profils reçoivent le même PCM, vérifié par SHA-256 à la lecture des WAV et par longueur et empreinte FNV-1a des échantillons flottants de chaque tranche au décodage. Le seul réglage d’ASR différent est [`initial_prompt`](https://github.com/ggml-org/whisper.cpp/blob/v1.8.5/include/whisper.h) : 62 jetons fournis à l’API, sans ajout à l’historique entre tranches ; certains replis du moteur à haute température peuvent ignorer l’historique. Aucun nom réémis n’est retiré de la sortie. Les bras sont alternés d’une dictée à la suivante, une passe par bras. Le réglage reste le même pour toute la série.
- Deux lots distincts : 32 dictées Px de la fenêtre historique de développement, et 16 dictées fictives produites par une voix synthétique française. Aucun enregistrement patient, aucune réserve ni donnée Corti. Aucune référence de ces deux lots ne contient l’un des 11 noms du contexte selon le scoreur : ces 48 dictées permettent de mesurer les ajouts indus et les régressions sur les autres termes, mais pas un gain de reconnaissance des 11 noms lorsqu’ils sont prononcés. Les contrôles de 1 s et 3 s de zéro numérique sont passés par Silero, puis envoyés directement au moteur à titre de diagnostic. Ce deuxième chemin ne correspond pas à une dictée dans l’application.
- [Grille et scoreurs déjà établis](training/critical_protocol_v2.md) : médicaments et associations médicament–dose, chiffres, unités, fractions, délais, négations et latéralité quand annotées. Le WER décompose substitutions, omissions et ajouts textuels ; un contrôle littéral peut signaler une reformulation équivalente. Les noms exacts de la liste sont comptés par occurrence ; un nom faux ajouté reste compté même si un autre faux nom disparaît. Le garde-fou prévu impose de tenir compte des **pertes critiques par cas**, même si la moyenne ou la reconnaissance de plusieurs noms s’améliorent.

## Rejouer en local

Utiliser un dossier neuf et non synchronisé. Le [banc de consolidation](decoder_consolidation.md) décrit la préparation des dylibs MAC de Whisper/GGML à partir des sources verrouillées ; le [protocole Px](training/retention_stability_notes.md) décrit la fenêtre et la grille privées. Les chemins ci-dessous désignent les actifs préexistants de la recherche, pas des téléchargements effectués par cet essai. Garder les manifestes audio, les références et les résultats `*.local.json` hors de Git.

```sh
python3 -m p0.lexical_cpp_041 build \
  --frozen-decoder /local/build-decoder-consolidation \
  --runtime /local/dylibs-ggml \
  --build /local/banc-cpp-neuf

# À exécuter dans l’ordre pour geler le protocole, tester une phrase hors grille,
# puis seulement mesurer les paires après succès du contrôle.
unset NOTEVIVE_ASR_BENCH_METRICS
for phase in freeze smoke run; do
  python3 -m p0.lexical_cpp_041 "$phase" \
    --build /local/banc-cpp-neuf --output /local/sorties-privees-neuves \
    --model /local/ggml-large-v3-turbo-q5_0.bin --vad /local/ggml-silero-v6.2.0.bin \
    --context /local/short-context.frozen.json --grid /local/critical-v2-r2-32.json \
    --synthetic /local/tts16/manifest.json --corpus /local/px-prepared \
    --smoke-wav /local/hors-grille.wav || break
done
```

Le script vérifie l’empreinte du code, des poids, des bibliothèques et des entrées. Un contrôle hors grille stable et une estimation inférieure à 15 minutes sont requis avant la boucle ; la boucle elle-même est également bornée. Le rapport agrège les taux, les nombres de contrôles réussis et échoués et les délais. Il ne contient aucun extrait audio, aucune référence ou sortie textuelle et aucun identifiant individuel de dictée.

Après avoir constaté que le lot de non-régression ne contient aucun des noms de la liste, [le deuxième script](lexical_cpp_041_positive.py) crée une phrase fictive par nom, dans l’ordre déjà figé. Chaque phrase contient exactement un nom connu, une valeur de force, une fraction de comprimé et une négation ; six portent aussi une latéralité. Les chiffres ne sont que des exercices de lecture. Le script valide la grille contre chacune des références et fige l’audio des 11 phrases avant son propre décodage. Aucune phrase ne peut être remplacée ni écartée selon le résultat. Ce bloc renseigne l’effet acoustique dans ce scénario ; une seule voix synthétique et des noms connus de l’essayeur ne constituent pas une confirmation indépendante.

```sh
python3 -m p0.lexical_cpp_041_positive prepare \
  --main /local/sorties-privees-neuves --context /local/short-context.frozen.json \
  --output /local/cas-positifs-prives

python3 -m p0.lexical_cpp_041_positive run \
  --main /local/sorties-privees-neuves --context /local/short-context.frozen.json \
  --output /local/cas-positifs-prives --build /local/banc-cpp-neuf \
  --model /local/ggml-large-v3-turbo-q5_0.bin --vad /local/ggml-silero-v6.2.0.bin \
  --smoke-wav /local/hors-grille.wav
```

La génération des phrases utilise une voix française « Jacques » déjà disponible sous macOS et FFmpeg en local. Un autre système peut produire des octets audio différents : conserver les empreintes du manifeste de son propre essai et comparer les bras sur ces mêmes fichiers. Aucune voix ni sortie brute du comparatif n’est distribuée.
