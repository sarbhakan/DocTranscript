# Contexte audio Whisper : variante courte écartée

Sur les 32 dictées du lot de développement, réduire le contexte audio a accéléré l’encodeur, mais a dégradé la transcription de doses, de fractions et de négations. Le décodage complet s’est aussi allongé sur les fragments les plus lents. NoteVive conserve le contexte complet de Whisper. Les chiffres et les empreintes figurent dans le [rapport agrégé JSON](audio_context_ablation.json).

## Méthode

Rejeu local des 32 WAV du [lot stress](lexicon_macos.md), déjà utilisés en développement : 28 fichiers de parole et quatre contrôles de silence ou de bruit, pour 9 min 24,5 s d’audio. Aucun enregistrement Corti. Le manifeste, les WAV et les poids ont été vérifiés par SHA-256 avant rejeu. Machine : MacBook Pro M1 Pro, 16 Gio, macOS 27.2 (26B123), CPU avec Accelerate. Les chiffres sont une comparaison relative sur cette machine, sans mesure sur Windows ni validation indépendante de la fidélité médicale.

Deux copies temporaires du [pont natif](../app/native/WhisperBridge.cpp), compilées avec les mêmes options Apple Clang C++17 `-O2`, ont chargé le même runtime Whisper.cpp 1.8.5, les mêmes poids Turbo Q5_0 et le même Silero GGML 6.2.0. Paramètres communs : français, décodage greedy et replis par défaut, Flash Attention actif, pas de reprise du texte précédent, quatre fils ASR et un fil VAD. Le banc injecte des paquets de 100 ms ; le pont ferme un fragment après les mêmes 576 ms de pause. Les deux contextes sont restés résidents et ont chacun reçu un préchauffage sur `dev-17` avant une passe mesurée par WAV. Les bras se sont exécutés en série dans le même processus, en inversant leur ordre à chaque fichier.

La référence laisse `params.audio_ctx = 0`, soit les 1 500 positions audio du modèle (30 s). La variante applique uniquement la règle suivante au nombre `count` d’échantillons du fragment à 16 kHz. Elle ajoute l’équivalent d’une seconde (50 positions) avant d’arrondir au multiple supérieur de 64, avec un minimum de 256 et un maximum de 1 500 positions. Les 72 fragments mesurés couvraient 256 à 832 positions pour cette variante.

```cpp
const size_t frames = (count + 319) / 320;
const size_t requested = ((frames + 50 + 63) / 64) * 64;
params.audio_ctx = static_cast<int>(std::min<size_t>(1500, std::max<size_t>(256, requested)));
```

Les 72 limites de fragments et nombres d’échantillons concordent entre les bras. Les 32 sorties du bras de référence sont identiques au précédent rejeu Turbo à 576 ms. Le [barème du banc](asr_compare.py) rapproche avec les mêmes règles, dans les deux bras, les termes et les éléments critiques annotés avant le rejeu. Le rapprochement automatique ne détecte pas tous les changements de sens ni les ajouts : les sorties qui changent ont aussi été relues.

## Fidélité

| Mesure | Contexte complet | Contexte court |
| --- | ---: | ---: |
| Doses et unités attendues | 22/26 | 13/26 |
| Fractions attendues | 8/8 | 3/8 |
| Négations attendues | 15/22 | 11/22 |
| Latéralités attendues | 4/4 | 3/4 |
| Autres quantités attendues | 0/2 | 0/2 |
| Délais attendus | 1/2 | 0/2 |
| Mentions de termes rares retrouvées | 25/66 | 13/66 |
| Contrôles sans parole avec texte émis | 0/4 | 0/4 |

Vingt éléments critiques auparavant corrects sont perdus, sans correction d’un élément critique auparavant manqué. Pour les termes rares, une mention est gagnée et treize sont perdues. Le texte généré change sur 26 fichiers. La correction d’une valeur de `0,75 mL` vers `0,075 mL` est rendue à tort comme une répétition de `0,75 mL`. Dans un autre cas, les trois fractions ½, ¼ et ¾ d’un comprimé disparaissent. Une négation de paresthésie disparaît aussi dans la variante alors que son orthographe était déjà imparfaite avec la référence ; ce changement de polarité ne figure pas parmi les vingt pertes comptées par le barème strict.

Dans deux fichiers de contrôle à parole courante, la variante réinsère une phrase prononcée dans un autre fichier, mais absente du signal et de la référence du fichier courant. Le contexte complet ne montre pas cet ajout sur les mêmes fichiers. Une cause plausible est le comportement décrit dans la [proposition de correction amont Whisper.cpp nº 3941](https://github.com/ggml-org/whisper.cpp/pull/3941) : lorsque la longueur du contexte varie, certaines positions de remplissage des caches lues par Flash Attention peuvent contenir des données d’un appel antérieur. L’essai observe l’ajout de texte ; il n’isole pas sa cause en modifiant Flash Attention ou en changeant l’ordre des fichiers.

## Délai à chaud

| Mesure | Contexte complet P50/P95 | Contexte court P50/P95 |
| --- | ---: | ---: |
| Encodage Whisper par fragment (72) | 3,015 / 3,175 s | 0,579 / 1,208 s |
| Décodage et échantillonnage internes par fragment (72) | 0,120 / 0,296 s | 0,195 / 9,450 s |
| Traitement d’un fragment par le pont après découpage (72) | 3,157 / 3,360 s | 1,079 / 10,099 s |
| Délai estimé de rendu aux pauses synthétiques, avec file série (32) | 3,903 / 4,129 s | 2,107 / 11,918 s |
| Rapport temps de calcul / durée d’audio (28 fichiers avec parole) | 0,443 / 0,792 | 0,157 / 0,881 |

Les percentiles sont calculés par rang sur les observations triées. Les compteurs internes de repli pour seuil de probabilité / entropie passent de 1 / 0 à 65 / 14. Sept fichiers parlés sur 28 sont plus lents avec le contexte court, et le temps de calcul total pour les fichiers parlés baisse d’environ 17 %. Le délai aux pauses est une estimation faite à partir des fins de parole synthétiques et de la file du décodeur : il exclut le micro et l’affichage. L’essai ne justifie ni de réduire la fenêtre audio du produit ni de revoir les [objectifs sur les PC Windows](asr_benchmark.md#rejouer-hors-ligne-sur-les-deux-pc).
