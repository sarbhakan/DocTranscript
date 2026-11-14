# NoteVive · paquet Windows d’essai

NoteVive transcrit en français sur Windows 11 x64, sans réseau. Extraire le ZIP en entier puis ouvrir `NoteVive.exe` en laissant le dossier `runtime` à côté. **Dicter** ou **F9** ouvre le microphone par défaut. Le texte rejoint la note éditable après une pause ; **Arrêter** coupe le micro et termine le décodage du dernier passage. La barre latérale permet de créer des notes et des dossiers imbriqués, de rechercher dans les titres et le texte et de choisir l’ordre de tri. Les notes sont sauvegardées localement avec leur titre, leur date de création et leur dernière modification.

Le [guide d’essai](../docs/guide-essai-windows.md) explique le lancement, les gestes utiles et le dépannage. Le paquet est prévu pour des **notes fictives uniquement** : il est non signé, les deux postes physiques restent à qualifier et la transcription peut se tromper sur les valeurs, les unités et le sens d’une négation.

## Composants

- **Win32 et C++17**, compilés pour x64 avec [Zig 0.15.2](https://ziglang.org/download/). La capture WinMM utilise le micro par défaut. F9 s’applique dans la fenêtre NoteVive. La capture audio et le décodage tournent indépendamment ; un processus enfant supervisé isole une panne native du moteur de l’éditeur. Aucun audio du microphone n’est sauvegardé.
- **whisper.cpp 1.8.5, Whisper Large v3 Turbo Q5_0 et Silero VAD GGML 6.2.0**, sur le processeur. Le réglage de pause par défaut est de **576 ms** ; le rendu à l’écran prend aussi le temps de décoder. Un seul paquet et un seul EXE à ouvrir. Le moteur choisit automatiquement son implantation CPU compatible, SSE2 de base ou AVX2 sur un poste compatible. La compilation de chaque DLL lie ggml et le runtime C/C++ statiquement (`/MT`). Aucun redistribuable Visual C++, Python ou .NET n’est à installer pour l’essai.
- **Bibliothèque locale chiffrée par DPAPI** dans `%LOCALAPPDATA%\NoteVive-Pilote\notes`. Elle préserve les notes historiques du même compte Windows. La [notice de stockage](windows/notes.md) décrit les formats, la compatibilité et la gestion des conflits.
- **Catalogue SQLite 3.54.1**, lu séparément et vérifié avant ouverture, avec 70 517 libellés provenant de six référentiels. Il ne contient pas de données BDPM et sert uniquement à la consultation. Le bouton **Vocabulaire** n’applique aucune correction au texte et ne modifie pas le décodage.

Les sources et empreintes du paquet sont dans [inputs.lock.json](inputs.lock.json) et les attributions dans [NOTICE.md](NOTICE.md). Le [verrou historique Zipformer](../p0/zipformer.inputs.lock.json) est réservé à la comparaison de l’ancien moteur, écarté de ce paquet. Les empreintes contrôlent l’identité des octets ; elles ne remplacent pas la signature d’une distribution.

## Refaire et valider la compilation

Sur la machine de construction Windows x64 seulement, utiliser Python 3.12, CMake et la chaîne C++ Visual Studio. La procédure de référence est le [workflow Windows](../.github/workflows/windows.yml) ; la [notice de construction du moteur](windows/whisper-build.md) décrit les contrôles de PE, d’imports et de CRT statique.

```powershell
python app/prepare_windows.py
python app/build_whisper_windows.py --source app/private/downloads/whisper-v1.8.5-source.tar.gz --output app/private/whisper-build
python app/build_windows.py --zig app/private/toolchain/zig-x86_64-windows-0.15.2/zig.exe
```

La préparation acquiert des entrées officielles et vérifie leurs empreintes. Les étapes de compilation empaquettent le modèle, l’EXE, le processus de dictée, le catalogue et les notices. La sortie est `dist/NoteVive-Windows-x64-Essai.zip` et son fichier `.sha256`. Les tests natifs du workflow sont compilés avec MSVC et couvrent les formats de la bibliothèque, DPAPI, le protocole du moteur et la récupération après échec. Ils lancent le véritable processus de dictée du ZIP sur un silence généré et une [prescription simulée française de 6,44 s](../p0/fixtures/README.md), en sélection CPU automatique puis en SSE2. Les journaux consignent le choix effectif, les temps des segments et la durée totale, sans texte reconnu. Ce contrôle prouve le chargement et le décodage, pas la précision médicale ni la vitesse sur les postes cibles. Le parcours de la fenêtre est ensuite testé sans microphone. La voie Zig de compilation croisée reste disponible pour les tests sur Mac.

Appliquer ensuite la [recette Windows 0.3.0](../docs/windows-recette-030.md) au **même ZIP** sur le PC à 8 Go sans GPU dédié et sur le second PC. Pour une comparaison d’ingénierie, lancer une passe distincte avec `NOTEVIVE_CPU=baseline` dans l’environnement du processus pour utiliser le moteur SSE2 de base ; le laisser non défini lors de l’essai utilisateur. Les résultats d’une compilation native, d’un test en CI ou d’une passe sur Mac ne qualifient ni cette configuration matérielle ni la précision clinique.
