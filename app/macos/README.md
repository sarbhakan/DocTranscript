# Essayer NoteVive sur Mac

**NoteVive 0.2.1, essai local sur Mac Apple Silicon (puce série M), macOS 15 ou ultérieur.** L’application contient UltiMed INT8 pour le français médical et Silero pour détecter les pauses. Elle n’a besoin ni d’un compte, ni d’un accès Internet, ni d’un téléchargement de modèle. Le paquet est signé localement, sans certificat Apple Developer ID ni notarisation.

**Utilisez des dictées fictives.** Le moteur peut changer une dose, une fraction ou une négation. Un exemple connu est « 400 mg » rendu comme « quatre milligrammes ». Le texte n’est pas corrigé automatiquement : le brouillon reste éditable.

1. Si NoteVive est déjà dans `~/Applications`, ouvrez cette copie depuis le Finder. Pour installer depuis le ZIP, quittez d’abord l’ancienne application avec `⌘Q`, extrayez le ZIP en entier hors des dossiers synchronisés, puis ouvrez `NoteVive.app`. Utilisez une seule copie pour conserver les mêmes repères et la même bibliothèque. Si les règles du poste refusent le lancement, demandez une version signée et approuvée.
2. Cliquez sur **+ Nouvelle transcription** (`⌘N`), donnez-lui un titre puis cliquez sur **Dicter** (`⌘D`). Au premier essai, autorisez le microphone lorsque macOS le demande. Si nécessaire : **Réglages Système → Confidentialité et sécurité → Microphone**.
3. Attendez **Micro ouvert**. Dites « Pas de douleur à la cheville droite », marquez une pause d’environ une seconde, puis dites « La gêne concerne la cheville gauche ». Après chaque pause, le texte rejoint **Brouillon à relire**. Cliquez sur **Arrêter** pour traiter la dernière phrase même sans pause. Relisez le brouillon, surtout les doses, unités, fractions et négations.
4. Les notes sont regroupées par date de dernière modification. Vous pouvez chercher par titre ou texte, créer des dossiers, puis y déplacer les notes par glisser-déposer, par le menu sous le titre ou par clic droit.
5. Attendez **Enregistré sur ce Mac** ou appuyez sur `⌘S`. Fermez et relancez l’application pour retrouver la note. **Exporter le texte…** produit une copie TXT.

**Aide lexicale (essai)** propose 14 profils par spécialité. **Consulter le lexique…** permet de chercher dans le catalogue complet même lorsque l’aide est coupée. Le profil actif propose au moteur une liste prioritaire de termes pendant la dictée. Dans ce profil, l’étoile donne la priorité à un terme du catalogue pour les prochaines dictées. Les favoris restent sur ce Mac. Le profil s’applique à la dictée qui démarre ; il est figé jusqu’à l’arrêt. La dictée démarre par défaut **Sans aide lexicale**. Voir [les contenus et les mesures avec et sans aide](../../docs/p0-recette-lexique-mac.md).

Réduire la fenêtre, passer à une autre application ou changer de périphérique interrompt la capture. Les passages terminés rejoignent la note ; le dernier passage inachevé peut être perdu. Le micro ne se rouvre que sur demande. L’audio n’est pas enregistré. Les notes et la copie de secours restent dans le conteneur local ; l’application ne chiffre pas elle-même ces fichiers. En cas d’échec de sauvegarde, gardez NoteVive ouvert et utilisez **Réessayer** ou exportez le brouillon. La version Mac n’intègre pas le catalogue médical de Windows.

## Refaire le paquet

Sur un Mac Apple Silicon avec Xcode et Python 3.11+, préparer ces fichiers sous `app/private/ultimed-macos/` (ou passer `--assets`). Le script contrôle toutes les empreintes avant de compiler et ne télécharge rien :

- `model/` : `config.json`, `vocab.txt` et `nemo128.onnx` à la racine de la révision UltiMed, et les deux poids `encoder-model.int8.onnx` et `decoder_joint-model.int8.onnx` dans son dossier `int8/`. Ajouter `silero_vad.onnx` depuis la révision Silero du [verrou P0](../../p0/packs/ultimed-int8.lock.json). L’empreinte du prétraitement `nemo128.onnx` est épinglée dans le script.
- `notices/` : les `README.md` des mêmes révisions sous les noms `UltiMed-README.md` et `Silero-README.md` ; le `LICENSE.txt` Silero sous le nom `Silero-LICENSE.txt` ; le [texte de la licence CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode.txt) sous le nom `CC-BY-4.0.txt`.
- À la racine des ressources : [onnxruntime-osx-arm64-1.32.0.tgz](https://github.com/microsoft/onnxruntime/releases/download/v1.32.0/onnxruntime-osx-arm64-1.32.0.tgz).

```sh
python3 app/macos/build_macos.py --lexicon /chemin/lexiques \
  --output /private/tmp/notevive-build/NoteVive.app --zip
```

Le script produit une `.app`, son ZIP et l’empreinte SHA-256 du ZIP au même endroit. Choisissez un chemin de sortie libre. Le script extrait le ZIP et contrôle la signature du paquet obtenu. `--lexicon` attend `profiles.json` et `SOURCES.md`, produits par [le générateur de profils](../../lexique/PROFILS.md#reproduction-hors-ligne), et les intègre dans le paquet. Sans cette option, le moteur fonctionne sans lexique. Voir [les composants et licences](NOTICE.md).

## Rejouer les contrôles

```sh
codesign --verify --deep --strict /chemin/NoteVive.app
/chemin/NoteVive.app/Contents/MacOS/NoteVive --self-test < /chemin/essai.wav
/chemin/NoteVive.app/Contents/MacOS/NoteVive --self-test-audio
```

Le premier test transmet un WAV fictif ou public (PCM 16 bits mono, 20 Mio et cinq minutes maximum) au traitement de l’application. Il sépare les résultats reçus pendant la dictée (`pause`) et à l’arrêt (`arret`). `audio_ms` est la position dans l’audio fourni en accéléré, pas un temps d’affichage. Le second test exerce les rappels Core Audio sans ouvrir le micro physique. Voir [les résultats du paquet 0.2.0](../../docs/p0-recette-mac-020.md).

```sh
xcrun swiftc -swift-version 6 -o /private/tmp/notevive-library-tests \
  app/macos/Library.swift app/macos/tests/LibraryTests.swift
/private/tmp/notevive-library-tests
```

Pour vérifier le démarrage graphique, ouvrez l’application dans le Finder puis contrôlez les dimensions de sa fenêtre. Répétez après relance :

```sh
xcrun swift -module-cache-path /private/tmp/notevive-geometry-cache app/macos/tests/CheckWindow.swift
```
