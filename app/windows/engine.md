# Moteur local du paquet d’essai

NoteVive charge le runtime [sherpa-onnx 2.0.1](https://github.com/k2-fsa/sherpa-onnx/releases/tag/v2.0.1) et le transducteur Zipformer français épinglés dans [`inputs.lock.json`](../inputs.lock.json). Le moteur fonctionne sur CPU et ne contacte aucun service. Il vérifie les empreintes des fichiers avant le premier chargement, conserve le reconnaisseur en mémoire, puis crée un flux neuf à chaque dictée. Les chemins des poids sont transmis en UTF-8 à Sherpa, dont [les fonctions de fichier utilisent les chemins larges sous Windows](https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.1/sherpa-onnx/csrc/file-utils.cc). Les DLL sont chargées depuis le répertoire d’exécution vérifié avec une recherche de dépendances limitée à ce dossier et à System32.

La capture WinMM ouvre le microphone par défaut au format PCM signé 16 bits, mono, 16 kHz. Un fil capture par blocs de 20 ms, un autre décode ; la file entre les deux contient au plus 32 blocs (640 ms). Les pertes détectées, blocage et débordement interrompent la dictée avec une erreur. À l’arrêt demandé, le fil de capture coupe l’entrée, récupère le dernier bloc et ferme le périphérique avant que le moteur termine le texte. [WinMM documente le traitement du dernier tampon par `waveInStop`.](https://learn.microsoft.com/en-us/windows/win32/api/mmeapi/nf-mmeapi-waveinstop) À l’annulation, l’audio restant et le provisoire sont écartés ; le texte déjà finalisé reste dans la note. Aucun fichier audio n’est créé par la capture.

Le transducteur reçoit l’audio au fil de l’eau et publie l’hypothèse courante lorsqu’elle change. Le décodeur utilise la recherche gloutonne sur deux fils CPU, avec des règles de fin de segment à 2,4 s de silence sans texte, 1,2 s après texte et 20 s par segment. À la fin de la dictée, il ajoute 300 ms de zéros comme dans [l’exemple officiel Zipformer](https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.1/c-api-examples/streaming-zipformer-c-api.c), puis vide le flux. Le silence numérique exact ne produit pas de texte ; la robustesse au bruit, aux pauses naturelles et aux accents reste à mesurer. Le catalogue local sert à la consultation ; il n’est pas injecté dans le décodage.

Le moteur et le micro restent dans le processus de l’interface. Un pilote bloqué ou un appel natif bloqué ne peut pas être interrompu au milieu de cet appel. Une fermeture micro non confirmée interdit une nouvelle capture et demande de quitter l’application. Ce paquet ne démontre ni la compatibilité avec tous les microphones, ni des objectifs de délai ou de précision médicale.

Le programme de vérification séparé n’ouvre pas le microphone et ne publie que le nombre d’événements non vides. Depuis la racine, compiler avec le Zig de la recette de construction, puis exécuter sur Windows avec le dossier `runtime` du paquet et des WAV PCM16 mono 16 kHz de test, de 60 secondes au plus :

```text
zig c++ -target x86_64-windows-gnu -std=c++17 -O2 -DUNICODE -D_UNICODE -municode app/windows/engine.cpp app/windows/engine_smoke.cpp app/windows/integrity.cpp -lwinmm -lbcrypt -o engine-smoke.exe
engine-smoke.exe <dossier-runtime> <parole-fictive.wav> --speech
engine-smoke.exe <dossier-runtime> <dev-silence-08s.wav> --silence
```

Le premier test demande un segment final non vide ; le second échoue si le moteur publie du texte. Le contrôle silence est généré par `python p0/corpus/generer_controles.py --wav-dir <nouveau-dossier>`. Le binaire console a été compilé et lié pour Windows x64 depuis macOS. Il doit encore être exécuté sur Windows, puis suivi d’un essai avec un microphone physique.
