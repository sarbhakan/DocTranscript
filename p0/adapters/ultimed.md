# Comparateur P0 : Parakeet UltiMed INT8

Ce comparateur utilise l’[export ONNX d’Olicorne](https://huggingface.co/Olicorne/parakeet-tdt-0.6b-v3-ultra-UltiMed-onnx) (CC BY 4.0). Il ne modifie pas l’application. Il décode les WAV français en une passe après `end`, sur CPU, sans texte provisoire, liste de mots ni correction automatique. Le détecteur de parole est désactivé par défaut. Garder un lot de phrases de 30 s au plus, silence compris. Les sorties sur silence et bruit sont à comptabiliser.

Sur le poste de préparation connecté, télécharger les quatre fichiers de la [révision figée](https://huggingface.co/Olicorne/parakeet-tdt-0.6b-v3-ultra-UltiMed-onnx/tree/ed3164a5aa5b0cd8a3e5627126109cc2483b0449) listés dans [le verrou](../packs/ultimed-int8.lock.json). Placer les deux fichiers d’`int8/` au même niveau que `config.json` et `vocab.txt`, sous leur nom exact. Garder aussi la fiche du modèle et les mentions d’attribution. Le prétraitement CPU NumPy est fourni par `onnx-asr` ; le fichier `nemo128.onnx` du dépôt de poids n’est pas requis.

Préparer un environnement Python 3.12 propre et les roues propres à chaque plateforme sur un poste connecté. Le comparateur a été vérifié avec [`onnx-asr` 0.12.0](https://pypi.org/project/onnx-asr/0.12.0/), [`onnxruntime` 1.32.0](https://pypi.org/project/onnxruntime/1.32.0/) et NumPy 2.5.4. Pour préparer les roues :

```sh
python3 -m pip download --only-binary=:all: --dest /chemin/wheelhouse \
  onnx-asr==0.12.0 onnxruntime==1.32.0 numpy==2.5.4
```

Consigner et vérifier les empreintes des roues et utiliser `pip install --no-index --find-links /chemin/wheelhouse` avec les mêmes versions sur le poste de mesure. Ne pas installer l’extra `hub` : l’adaptateur exige le dossier local, vérifie les empreintes, et le moteur ne télécharge rien. Vérifier les poids sans avoir besoin du moteur :

```sh
python3 -m p0.adapters.ultimed --model-dir /chemin/ultimed --verify-only
```

Depuis la racine du projet, avec l’interpréteur de cet environnement :

```sh
python3 -m p0.bench --cases /chemin/cas-courts.csv --wav-dir /chemin/wav \
  --output /chemin/resultats-ultimed --mode accelerated --startup-timeout-s 60 \
  --timeout-s 30 --include-text -- \
  python3 -m p0.adapters.ultimed --model-dir /chemin/ultimed --threads 4
```

Utiliser `--include-text` uniquement sur les jeux de test autorisés et conserver les sorties individuelles hors Git. Pour comparer le temps de traitement, utiliser `final_from_end_request_ms` après préchauffage. Le temps jusqu’à `ready` du comparateur inclut la vérification des poids ; ne pas le comparer directement à un worker qui les vérifie avant son lancement. Ce test ne mesure pas l’affichage dans l’application.

Pour le bras avec détection de parole, préparer séparément [`silero_vad.onnx`, version 6.2](https://huggingface.co/istupakov/silero-vad-onnx/tree/b3e3ee3cce4c11ceb63b1a0b229d916069c1ddf6), avec la licence MIT et l’empreinte de `optional_speech_gate` dans le verrou. Ajouter `--speech-gate-dir /chemin/silero` à la commande du worker ou à `--verify-only`. Le détecteur tourne sur un fil CPU. Il refuse un fichier lorsqu’aucun segment de parole n’est détecté (seuil 0,5 et durée minimale 90 ms), sinon UltiMed reçoit tous les échantillons d’origine. Cette option évite le découpage de la dictée, mais une parole trop brève ou faible peut être rejetée entièrement. Le manifeste indique `vad_mode: whole-clip-gate` pour distinguer cette mesure du découpage Silero du comparateur Whisper.
