# Construire Whisper 1.8.5 pour Windows x64

La construction utilise les [sources officielles de whisper.cpp 1.8.5](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.8.5) sous [licence MIT](https://github.com/ggml-org/whisper.cpp/blob/v1.8.5/LICENSE). Le paquet Windows contient deux variantes internes de `whisper.dll`, chacune regroupant GGML, son moteur CPU et le runtime C/C++ MSVC. L’application charge une seule variante et les deux lisent les mêmes poids. Le paquet Windows n’a pas besoin d’OpenMP, d’un GPU ni d’installer le redistribuable Visual C++. Le paquet binaire x64 officiel de Whisper importe des DLL du redistribuable et d’OpenMP ; il n’est pas utilisé pour cette construction.

Préparation : récupérer [l’archive officielle de sources](https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/refs/tags/v1.8.5) et la placer localement. SHA-256 attendu : `cd702189cb5e608c8bc487f4b151db593c4455925b37cc06ef76b44861911db1`.

Depuis la racine du dépôt, sur Windows x64 avec Python 3.12+, CMake 3.21+, Visual Studio 2022 (C++ v143, composants Clang/LLVM et SDK Windows) :

```powershell
python app/build_whisper_windows.py --toolset clangcl --source app/private/downloads/whisper-v1.8.5-source.tar.gz --output app/private/whisper-build
```

`clangcl` (outil Visual Studio `ClangCL`) est le défaut pour cet essai de performance. Pour reproduire la construction de référence, passer `--toolset msvc` et choisir une autre destination. Les poids, le nombre de fils de calcul et les réglages de reconnaissance sont les mêmes. Les deux constructions ciblent SSE2 et AVX2 ; pour sa variante AVX2, ClangCL désactive FSGSBASE, MOVBE, PCLMUL et XSAVEOPT, car le superviseur ne vérifie pas ces instructions supplémentaires activées par ce compilateur. Seul le compilateur retenu après mesure sera utilisé pour l’essai distribué. Les deux constructions utilisent l’ABI et le runtime statique de Visual C++ ; les tests du paquet lancent les véritables binaires de la distribution.

Cette étape ne télécharge rien. L’[image GitHub Actions `windows-2022`](https://github.com/actions/runner-images/blob/main/images/windows/Windows2022-Readme.md#workloads-components-and-extensions) liste les composants Visual Studio `VC.Llvm.Clang` et `VC.Llvm.ClangToolset`. Le dossier de destination doit être nouveau. Il contient `bin/whisper.dll` (SSE2), `bin/cpu-avx2/whisper.dll` (AVX2), `lib/whisper.lib` pour la liaison de l’ABI commune, `include/` pour la compilation, le `LICENSE` amont et `attestation.json`.

Le script vérifie l’archive avant de l’extraire. Il modifie un seul fichier amont, `CMakeLists.txt` : active `CMP0091=NEW` avant le premier `project()` pour respecter le choix du CRT, puis active `BUILD_SHARED_LIBS` uniquement autour de `add_subdirectory(src)` pour créer la DLL Whisper. Les sources C/C++ ne changent pas.

| Fichier | SHA-256 |
|---|---|
| `CMakeLists.txt` sans modification | `14b57729cec1bf09635ea23f551112f51220ad2f22214b42c1f1689b96480d7b` |
| `CMakeLists.txt` après ces deux modifications | `3d65c6bbe3f6e4f3033fa047e92c6754132a2f385a1e77b126f10a27dc3be74d` |

Le script vérifie le choix du compilateur auprès de CMake pour C et C++, ainsi que le toolset Visual Studio, le CRT statique `/MT` et les options d’architecture des quatre projets de chaque variante. Il contrôle la structure PE x64 et les imports des deux DLL, y compris les imports différés. Il vérifie que l’export C `whisper_version()` renvoie `1.8.5` pour la DLL de base et, si la machine de construction signale AVX2, pour la DLL optimisée. L’attestation JSON (schéma 3) consigne ces contrôles, les noms et versions des compilateurs, les options CMake et les empreintes des fichiers livrés. Il faut garder le fichier de licence MIT avec le moteur distribué. Les licences et empreintes des poids de reconnaissance et de détection sont traitées séparément.

Le superviseur vérifie les empreintes avant de lancer le moteur. Sur Windows, il utilise le sous-dossier `runtime/cpu-avx2/` uniquement si le système confirme qu’AVX2 est utilisable et que le processeur prend en charge FMA, F16C et les extensions associées à [`/arch:AVX2` sous MSVC](https://learn.microsoft.com/en-us/cpp/build/reference/arch-x64?view=msvc-170). Sur les autres postes, il utilise la variante x64 de base. Les deux utilisent le même dossier `runtime/` pour les poids.

Pour la recette, affecter `$env:NOTEVIVE_CPU = 'baseline'` dans PowerShell avant d’ouvrir NoteVive pour imposer la variante de base. Retirer cette variable (`Remove-Item Env:NOTEVIVE_CPU`) puis relancer NoteVive pour rétablir le choix automatique. Aucune valeur ne permet de forcer AVX2. Le débit et la mémoire doivent être mesurés avec les DLL produites, notamment sur le poste Windows à 8 Go.
