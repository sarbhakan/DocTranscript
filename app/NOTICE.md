# Composants inclus dans le paquet d’essai

- Sherpa-ONNX v2.0.1, k2-fsa et contributeurs, [version et sources](https://github.com/k2-fsa/sherpa-onnx/releases/tag/v2.0.1), licence Apache 2.0 jointe. Le moteur embarque [ONNX Runtime v1.28.2](https://github.com/microsoft/onnxruntime/tree/v1.28.2), Microsoft et contributeurs, licence MIT et avis des tiers joints. Les textes des autres dépendances de Sherpa-ONNX figurent dans le dossier `Sherpa-Tiers` du paquet.
- Zipformer français pour Sherpa-ONNX, export de Shaojie Li, [révision et fiche Apache 2.0](https://huggingface.co/shaojieli/sherpa-onnx-streaming-zipformer-fr-2023-04-14/tree/3db9565d9633758d6b87b9a7b3dc09ebfb6b2c73). Les poids et les jetons sont copiés sans modification ; leurs noms de fichiers sont abrégés dans le paquet.
- [SQLite 3.54.1](https://sqlite.org/releaselog/3_54_1.html), [domaine public selon le projet](https://sqlite.org/copyright.html), compilé pour la consultation locale du catalogue. Les notes ne sont pas stockées dans ce fichier SQLite.
- Catalogue de libellés : l’attribution, l’édition, la licence et les transformations de chaque source figurent dans `Referentiels.json`. L’index de recherche est une dérivation technique ; les libellés affichés restent ceux des sources. Le paquet public exclut la BDPM. Ce catalogue est un instantané de test, sans statut de disponibilité, de facturation ou de validation clinique.

Zig, Python et les outils de construction ne sont pas livrés et ne sont pas nécessaires au lancement.
