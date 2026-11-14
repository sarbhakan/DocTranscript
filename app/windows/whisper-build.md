# Construire Whisper 1.8.5 pour Windows x64

La construction utilise les [sources officielles de whisper.cpp 1.8.5](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.8.5) sous [licence MIT](https://github.com/ggml-org/whisper.cpp/blob/v1.8.5/LICENSE). Le paquet Windows contient deux variantes internes de `whisper.dll`, chacune regroupant GGML, son moteur CPU et le runtime C/C++ MSVC. L’application charge une seule variante et les deux lisent les mêmes poids. Le paquet Windows n’a pas besoin d’OpenMP, d’un GPU ni d’installer le redistribuable Visual C++. Le paquet binaire x64 officiel de Whisper importe des DLL du redistribuable et d’OpenMP ; il n’est pas utilisé pour cette construction.

Préparation : récupérer [l’archive officielle de sources](https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/refs/tags/v1.8.5) et la placer localement. SHA-256 attendu : `cd702189cb5e608c8bc487f4b151db593c4455925b37cc06ef76b44861911db1`.

Depuis la racine du dépôt, sur Windows x64 avec Python 3.12+, CMake 3.21+, Visual Studio 2022 (C++ v143) et le SDK Windows installés :

```powershell
python app/build_whisper_windows.py --source app/private/downloads/whisper-v1.8.5-source.tar.gz --output app/private/whisper-build
```

Cette étape ne télécharge rien. `windows-2025` dans [GitHub Actions](https://github.com/actions/runner-images/blob/main/images/windows/Windows2025-Readme.md#visual-studio-enterprise-2022) contient les outils requis. Le dossier de destination doit être nouveau. Il contient `bin/whisper.dll` (SSE2), `bin/cpu-avx2/whisper.dll` (AVX2), `lib/whisper.lib` pour la liaison de l’ABI commune, `include/` pour la compilation, le `LICENSE` amont et `attestation.json`.

Le script vérifie l’archive avant de l’extraire. Il modifie un seul fichier amont, `CMakeLists.txt` : active `CMP0091=NEW` avant le premier `project()` pour respecter le choix du CRT, puis active `BUILD_SHARED_LIBS` uniquement autour de `add_subdirectory(src)` pour créer la DLL Whisper. Les sources C/C++ ne changent pas.

| Fichier | SHA-256 |
|---|---|
| `CMakeLists.txt` sans modification | `14b57729cec1bf09635ea23f551112f51220ad2f22214b42c1f1689b96480d7b` |
| `CMakeLists.txt` après ces deux modifications | `3d65c6bbe3f6e4f3033fa047e92c6754132a2f385a1e77b126f10a27dc3be74d` |

La recette vérifie le CRT statique `/MT` et les options d’architecture dans les quatre projets de compilation de chaque variante, la structure PE x64 et la liste des imports Windows des deux DLL, y compris les imports différés. Elle vérifie que l’export C `whisper_version()` renvoie `1.8.5` pour la DLL de base et, si la machine de construction signale AVX2, pour la DLL optimisée. L’attestation JSON (schéma 2) associe ces contrôles, les options CMake et les empreintes de tous les fichiers livrés ; ce fichier rend la construction traçable, il ne s’agit pas d’une signature. Il faut garder le fichier de licence MIT avec le moteur distribué. Les licences et empreintes des poids de reconnaissance et de détection sont traitées séparément.

Le superviseur vérifie les empreintes avant de lancer le moteur. Sur Windows, il utilise le sous-dossier `runtime/cpu-avx2/` uniquement si le système confirme qu’AVX2 est utilisable et que le processeur prend en charge FMA, F16C et les extensions associées à [`/arch:AVX2` sous MSVC](https://learn.microsoft.com/en-us/cpp/build/reference/arch-x64?view=msvc-170). Sur les autres postes, il utilise la variante x64 de base. Les deux utilisent le même dossier `runtime/` pour les poids.

Pour la recette, affecter `$env:NOTEVIVE_CPU = 'baseline'` dans PowerShell avant d’ouvrir NoteVive pour imposer la variante de base. Retirer cette variable (`Remove-Item Env:NOTEVIVE_CPU`) puis relancer NoteVive pour rétablir le choix automatique. Aucune valeur ne permet de forcer AVX2. Le débit et la mémoire doivent être mesurés avec les DLL produites, notamment sur le poste Windows à 8 Go.
