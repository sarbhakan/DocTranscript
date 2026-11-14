# NoteVive · paquet Windows d’essai

**Paquet d’essai : [NoteVive 0.3.0 pour Windows](https://github.com/sarbhakan/DocTranscript/releases/tag/v0.3.0-essai).** Extraire le ZIP en entier puis ouvrir `NoteVive.exe` en laissant le dossier `runtime` à côté. NoteVive transcrit en français sur Windows 11 x64, sans réseau. **Dicter** ou **F9** ouvre le microphone par défaut. Le texte rejoint la note éditable après une pause ; **Arrêter** coupe le micro et termine le décodage du dernier passage. La barre latérale permet de créer des notes et des dossiers imbriqués, de rechercher dans les titres et le texte et de choisir l’ordre de tri. Les notes sont sauvegardées localement avec leur titre, leur date de création et leur dernière modification.

Le [guide d’essai](../docs/guide-essai-windows.md) explique le lancement, les gestes utiles et le dépannage. Le paquet est prévu pour des **notes fictives uniquement** : il est non signé, les deux postes physiques restent à qualifier et la transcription peut se tromper sur les valeurs, les unités et le sens d’une négation.

## Composants

- **Win32 et C++17**, compilés pour x64 avec [Zig 0.15.2](https://ziglang.org/download/). La capture WinMM utilise le micro par défaut. F9 s’applique dans la fenêtre NoteVive. La capture audio et le décodage tournent indépendamment ; un processus enfant supervisé isole une panne native du moteur de l’éditeur. Aucun audio du microphone n’est sauvegardé.
- **whisper.cpp 1.8.5, Whisper Large-v3 Turbo Q5_0, OpenBLAS 0.3.34 et Silero VAD GGML 6.2.0**, sur le processeur. Le moteur commence le traitement après une pause de **576 ms** ; le rendu à l’écran inclut le temps de calcul. La dictée exige la prise en charge d’AVX/AVX2 par Windows et par le processeur, ainsi que FMA, F16C, BMI1, BMI2, LZCNT, SSE4.2 et POPCNT. Sur un poste incompatible, le modèle ne se charge pas et le micro ne s’ouvre pas ; les notes restent accessibles. Le moteur lie ggml et le runtime C/C++ statiquement (`/MT`). Aucun redistribuable Visual C++, Python ou .NET n’est à installer pour l’essai.
- **Bibliothèque locale chiffrée par DPAPI** dans `%LOCALAPPDATA%\NoteVive-Pilote\notes`. Elle préserve les notes historiques du même compte Windows. La [notice de stockage](windows/notes.md) décrit les formats, la compatibilité et la gestion des conflits.
- **Catalogue SQLite 3.54.1**, lu séparément et vérifié avant ouverture, avec 70 517 libellés provenant de six référentiels. Il ne contient pas de données BDPM et sert uniquement à la consultation. Le bouton **Vocabulaire** n’applique aucune correction au texte et ne modifie pas le décodage.

Les sources et empreintes du paquet sont dans [inputs.lock.json](inputs.lock.json) et les attributions dans [NOTICE.md](NOTICE.md). Le [verrou historique Zipformer](../p0/zipformer.inputs.lock.json) est réservé à la comparaison de l’ancien moteur, écarté de ce paquet. Les empreintes contrôlent l’identité des octets ; elles ne remplacent pas la signature d’une distribution.

## Refaire et valider la compilation

Sur la machine de construction Windows x64 seulement, utiliser Python 3.12, CMake et la chaîne C++ Visual Studio. La procédure de référence est le [workflow Windows](../.github/workflows/windows.yml) ; la [notice de construction du moteur](windows/whisper-build.md) décrit les contrôles de PE, d’imports et de CRT statique.

```powershell
python app/prepare_windows.py
python app/build_whisper_windows.py --toolset clangcl --source app/private/downloads/whisper-v1.8.5-source.tar.gz --openblas-source app/private/downloads/openblas-v0.3.34-source.tar.gz --output app/private/whisper-build
python app/build_windows.py --zig app/private/toolchain/zig-x86_64-windows-0.15.2/zig.exe
```

La préparation acquiert des entrées officielles et vérifie leurs empreintes. La compilation produit `dist/NoteVive-Windows-x64-Essai.zip` et son fichier `.sha256`. Le [job Windows de validation](https://github.com/sarbhakan/DocTranscript/actions/runs/43620136119/job/132523751821) passe les contrôles natifs : bibliothèque, DPAPI, compatibilité CPU, protocole, découpage et récupération après une panne du moteur. Le moteur passe le silence généré et les contrôles chiffrés des trois [enregistrements fictifs français](../p0/fixtures/README.md). Ces contrôles ne valident pas l’association clinique des médicaments aux doses. Voir les [mesures](../docs/p0-choix-moteur.md).

Le même job passe le parcours d’interface automatisé, sans microphone : dossiers et sous-dossiers, deux notes, trois tris, recherche, renommage, classement et réouverture. La voie Zig de compilation croisée reste disponible pour les tests sur Mac. CTranslate2 reste un comparateur du banc, sans worker ni dépendance Python dans le paquet produit.

SSE2 reste un diagnostic d’ingénierie. Pour le rejouer explicitement, utiliser `python -m app.test_windows --compiler msvc --output <nouveau-dossier> --package <dossier-NoteVive-extrait> --engine-only --include-unsupported-baseline`. Ce diagnostic garde la limite de 90 s et peut échouer. NoteVive.exe ne permet pas d’activer un mode de dictée SSE2.

Appliquer ensuite la [recette Windows 0.3.0](../docs/windows-recette-030.md) au **même ZIP** sur deux PC physiques compatibles, dont un à 8 Go sans GPU dédié. Les résultats en CI ou sur Mac ne qualifient ni cette configuration matérielle ni la précision clinique.
