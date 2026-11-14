# Construire Whisper 1.8.5 pour Windows x64

La construction utilise les [sources officielles de whisper.cpp 1.8.5](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.8.5) sous [licence MIT](https://github.com/ggml-org/whisper.cpp/blob/v1.8.5/LICENSE). Deux DLL sont construites avec GGML et le runtime C/C++ statique. La dictée dans NoteVive utilise uniquement la DLL AVX2 ; la DLL SSE2 sert au diagnostic. Les deux lisent les mêmes poids. Le paquet Windows n’a pas besoin d’OpenMP, d’un GPU ni d’installer le redistribuable Visual C++.

Préparation : `python app/prepare_windows.py` vérifie les archives officielles [Whisper](https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/refs/tags/v1.8.5) et [OpenBLAS 0.3.34](https://github.com/OpenMathLib/OpenBLAS/releases/tag/v0.3.34) selon [le verrou](../inputs.lock.json). SHA-256 de l’archive Whisper : `cd702189cb5e608c8bc487f4b151db593c4455925b37cc06ef76b44861911db1`.

Depuis la racine du dépôt, sur Windows x64 avec Python 3.12+, CMake 3.21+, Visual Studio 2022 (C++ v143, composants Clang/LLVM et SDK Windows) :

```powershell
python app/build_whisper_windows.py --toolset clangcl --source app/private/downloads/whisper-v1.8.5-source.tar.gz --openblas-source app/private/downloads/openblas-v0.3.34-source.tar.gz --output app/private/whisper-build
```

OpenBLAS requiert `clangcl` (outil Visual Studio `ClangCL`) et Ninja. Pour reproduire la construction de référence MSVC, retirer `--openblas-source`, passer `--toolset msvc` et utiliser une autre destination. Les poids, le nombre de fils de calcul et les réglages de reconnaissance sont les mêmes. Pour AVX2, ClangCL désactive FSGSBASE, MOVBE, PCLMUL et XSAVEOPT, que le superviseur ne vérifie pas. Les constructions utilisent l’ABI et le runtime statique de Visual C++. La construction et les mesures avec OpenBLAS restent à confirmer ; aucun gain n’est établi.

Cette étape ne télécharge rien. L’[image GitHub Actions `windows-2022`](https://github.com/actions/runner-images/blob/main/images/windows/Windows2022-Readme.md#workloads-components-and-extensions) liste les composants Visual Studio `VC.Llvm.Clang` et `VC.Llvm.ClangToolset`. Le dossier de destination doit être nouveau. Il contient `bin/whisper.dll` (SSE2), `bin/cpu-avx2/whisper.dll` (AVX2), `lib/whisper.lib` pour la liaison de l’ABI commune, `include/` pour la compilation, le `LICENSE` amont et `attestation.json`.

Le script vérifie l’archive avant de l’extraire. Dans `CMakeLists.txt`, il active `CMP0091=NEW` avant le premier `project()` pour respecter le choix du CRT, puis `BUILD_SHARED_LIBS` uniquement autour de `add_subdirectory(src)` pour créer la DLL Whisper. Pour OpenBLAS, un second correctif cible `ggml/src/ggml-blas/CMakeLists.txt` pour lier la bibliothèque statique préparée. Les sources C/C++ restent inchangées.

La construction AVX2 sans OpenBLAS active `GGML_LLAMAFILE` pour certaines multiplications matricielles de GGML. L’essai OpenBLAS désactive ce noyau et active `GGML_BLAS` avec OpenBLAS statique, cible Haswell, sans OpenMP. Les poids et le contexte audio complet restent inchangés. Les différences de sommation flottante appellent une vérification de fidélité sur les mêmes dictées.

| Fichier | SHA-256 |
|---|---|
| `CMakeLists.txt` sans modification | `14b57729cec1bf09635ea23f551112f51220ad2f22214b42c1f1689b96480d7b` |
| `CMakeLists.txt` après ces deux modifications | `3d65c6bbe3f6e4f3033fa047e92c6754132a2f385a1e77b126f10a27dc3be74d` |

Le script vérifie les compilateurs C et C++, le toolset Visual Studio, le CRT statique `/MT` et les options d’architecture. Il contrôle la structure PE x64 et les imports des deux DLL, imports différés compris. Il vérifie que l’export C `whisper_version()` renvoie `1.8.5` pour la DLL de base et, si la machine de construction signale AVX2, pour la DLL AVX2. L’attestation JSON (schéma 3, ou 4 avec OpenBLAS) consigne ces contrôles, les compilateurs, les options CMake et les empreintes.

Le superviseur vérifie les empreintes avant de lancer le moteur. La dictée exige que Windows confirme AVX/AVX2 et que le CPU prenne en charge FMA, F16C, BMI1, BMI2, LZCNT, SSE4.2 et POPCNT. Sur un poste incompatible, NoteVive laisse les notes accessibles et n’ouvre pas le micro. Il n’existe pas de repli SSE2 dans l’interface.

Le diagnostic SSE2 se lance via `app.test_windows --include-unsupported-baseline`, détaillé dans [la procédure](../README.md), avec la même limite de 90 s qu’auparavant. Le débit et la mémoire restent à mesurer sur les deux postes physiques avec le paquet retenu, notamment sur le PC compatible à 8 Go sans GPU dédié. Les tests des deux extraits de régression vérifient des nombres et des fractions annotés, sans établir la fidélité de la dictée en pratique.
