# Dépendances du moteur Sherpa-ONNX v2.0.1

Cette notice accompagne la bibliothèque du moteur redistribuée par NoteVive. Les versions ci-dessous sont celles utilisées par les scripts de construction de [Sherpa-ONNX v2.0.1](https://github.com/k2-fsa/sherpa-onnx/tree/v2.0.1). Les textes de licence et de copyright qui accompagnent ce fichier sont repris des dépôts amont aux révisions indiquées. La licence de Sherpa-ONNX et les notices ONNX Runtime sont jointes séparément.

| Composant | Source de la version indiquée | Licence |
| --- | --- | --- |
| kaldi-native-fbank v1.22.4 | [Code source](https://github.com/csukuangfj/kaldi-native-fbank/tree/v1.22.4) | Apache 2.0 |
| kaldi-decoder v0.3.0 | [Code source](https://github.com/k2-fsa/kaldi-decoder/tree/v0.3.0) | Apache 2.0 |
| kaldifst v1.8.0 | [Code source](https://github.com/k2-fsa/kaldifst/tree/v1.8.0) | Apache 2.0 |
| OpenFst v1.8.5-2026-04-10 | [Code source](https://github.com/csukuangfj/openfst/tree/v1.8.5-2026-04-10) | Apache 2.0 ; voir aussi le texte Apache joint à Sherpa-ONNX |
| Eigen 3.4.0 | [Archive complète du code source correspondant](https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.tar.gz) | MPL 2.0 ; voir les notices propres aux fichiers dans les sources |
| Kiss FFT `febd4ca` | [Code source](https://github.com/mborgerding/kissfft/tree/febd4caeed32e33ad8b2e0bb5ea77542c40f18ec) | BSD 3-Clause |
| utf8proc v2.12.0 | [Code source](https://github.com/JuliaStrings/utf8proc/tree/v2.12.0) | MIT et licence des données Unicode, dans le texte joint |
| simple-sentencepiece v0.7 | [Code source](https://github.com/pkufool/simple-sentencepiece/tree/v0.7) | Apache 2.0 |
| nlohmann/json v3.12.0 | [Code source](https://github.com/nlohmann/json/tree/v3.12.0) | MIT |

Le code source d’Eigen reste disponible sous sa propre licence via le lien ci-dessus. Les conditions de cette licence s’appliquent aux parties couvertes d’Eigen et ne sont pas restreintes par la distribution de NoteVive.
