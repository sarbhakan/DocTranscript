# Composants de NoteVive pour macOS

- [Sherpa-ONNX v2.0.1](https://github.com/k2-fsa/sherpa-onnx/releases/tag/v2.0.1), distribution macOS arm64 dynamique sans TTS, licence Apache 2.0. Les notices des composants liés à Sherpa sont sous `Sherpa-et-dependances`.
- [ONNX Runtime v1.28.2](https://github.com/microsoft/onnxruntime/tree/v1.28.2) inclus dans la distribution Sherpa : licence MIT et avis des composants tiers joints. Les poids sont chargés par le fournisseur CPU.
- [Zipformer français](https://huggingface.co/shaojieli/sherpa-onnx-streaming-zipformer-fr-2023-04-14/tree/3db9565d9633758d6b87b9a7b3dc09ebfb6b2c73), export ONNX de shaojieli, licence Apache 2.0 selon la carte du modèle. Fichiers non modifiés ; les empreintes sont dans [le verrou du projet](../inputs.lock.json).

L’application ne contient ni catalogue BDPM, ni enregistrement de test. Le logiciel et le modèle servent ici à évaluer la dictée sur des exemples fictifs.
