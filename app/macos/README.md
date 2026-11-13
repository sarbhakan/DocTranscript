# Essayer NoteVive sur Mac

**NoteVive 0.1.2 : Mac Apple Silicon (puce série M), macOS 15 ou ultérieur.** Le modèle français est inclus et fonctionne hors ligne. Cette version remet la fenêtre au premier plan quand on rouvre l’application et limite l’ouverture de plusieurs copies. Elle conserve la bibliothèque locale et le correctif du microphone de la version précédente. Le paquet est signé localement, sans certificat Apple Developer ID ni notarisation. Utilisez uniquement des phrases fictives pour l’essai.

1. Utilisez une seule copie. Dans le Finder, placez `NoteVive-Mac.zip` dans `~/Applications` ou un autre dossier local hors iCloud, extrayez l’archive, puis ouvrez `NoteVive-Mac.app`. Ne lancez pas une copie extraite dans le dossier du projet s’il est synchronisé. Si une ancienne copie tourne, quittez-la avec `⌘Q` avant de lancer la nouvelle. Si une règle du poste refuse le lancement, demandez une version signée et approuvée plutôt que de modifier les protections du poste.
2. Cliquez sur **+ Nouvelle transcription** (`⌘N`), puis saisissez un titre. Cliquez sur **Dicter** (`⌘D`). Au premier essai, macOS demande votre autorisation d’accès au micro. Attendez **Micro ouvert** puis dites : « Pas de douleur de la cheville droite. La gêne concerne la cheville gauche depuis cinq jours. » Si l’autorisation a été refusée, ouvrez **Réglages Système → Confidentialité et sécurité → Microphone**.
3. Pendant la dictée, le texte provisoire apparaît séparément. Les segments terminés rejoignent **Brouillon à relire** et sont sauvegardés. Cliquez sur **Arrêter**, attendez la fin du traitement puis corrigez « pas », « droite », « gauche » et « cinq » si nécessaire. Le changement de note attend la fin de la dictée pour éviter d’écrire dans le mauvais brouillon.
4. Dans **Bibliothèque**, les transcriptions sont regroupées par date de dernière modification. La recherche porte sur le titre et le texte. Cliquez sur l’icône à côté de **Dossiers** pour en créer un, puis glissez-y une note. Le menu dossier sous le titre et le clic droit **Déplacer vers** donnent la même possibilité. Vous pouvez revenir à **Sans dossier** ou renommer le dossier via son menu.
5. La sauvegarde est automatique. Attendez **Enregistré sur ce Mac** ou utilisez `⌘S`, puis fermez et relancez l’application pour retrouver la note. **Exporter le texte…** produit une copie TXT si vous en avez besoin.

Arrêtez la dictée avant de quitter. Réduire la fenêtre, passer à une autre application ou changer de périphérique audio interrompt la capture. Le provisoire peut alors être perdu ; le texte déjà transféré reste dans le brouillon. Le micro ne se rouvre que sur demande. Aucune capture audio n’est conservée et aucune donnée n’est envoyée par l’application.

La bibliothèque et sa copie de secours précédente restent dans le conteneur local de l’application. Le logiciel ne chiffre pas ces fichiers lui-même. En cas d’échec de sauvegarde, gardez NoteVive ouvert et utilisez **Réessayer** ou exportez le brouillon avant de fermer. Les exports TXT ne sont pas chiffrés non plus. La version Mac n’intègre pas le catalogue médical consultable de Windows.

## Refaire le paquet

Sur un Mac Apple Silicon avec Xcode et Python 3.11+, préparer les poids et notices ONNX dans `app/private/downloads/`, suivant les noms, liens et empreintes du [verrou des dépendances](../inputs.lock.json) : `encoder.onnx`, `decoder.onnx`, `joiner.onnx`, `tokens.txt`, `ONNX-LICENSE`, `ONNX-ThirdPartyNotices.txt`. Préparer aussi le [runtime Sherpa-ONNX macOS arm64 2.0.1](https://github.com/k2-fsa/sherpa-onnx/releases/download/v2.0.1/sherpa-onnx-v2.0.1-osx-arm64-shared-no-tts.tar.bz2) sous le nom `sherpa-macos-smoke.tar.bz2` ; son empreinte est dans le script de compilation. Les deux bibliothèques et les modèles sont copiés dans l’application. Aucun téléchargement ne se produit à la compilation ou à l’exécution.

```sh
python3 app/macos/build_macos.py --zip
```

Cette commande produit `dist/NoteVive-Mac.app`, `dist/NoteVive-Mac.zip` et l’empreinte du ZIP. Si les sorties existent, choisir un nouveau chemin `--output` ou mettre à part les précédentes. Après extraction hors d’un dossier synchronisé, vérifier la signature et rejouer la reconnaissance locale avec un WAV de test fictif ou public (PCM 16 bits, mono, jusqu’à 20 Mio) :

```sh
codesign --verify --deep --strict /chemin/NoteVive-Mac.app
/chemin/NoteVive-Mac.app/Contents/MacOS/NoteVive --self-test < /chemin/essai.wav
/chemin/NoteVive-Mac.app/Contents/MacOS/NoteVive --self-test-audio
```

Le premier test transmet un fichier au moteur et indique le nombre d’hypothèses et le texte final. Le second reproduit les rappels Core Audio sur un signal synthétique, sans microphone physique. Ils ne mesurent pas la fidélité médicale. Pour les contrôles de sauvegarde :

```sh
xcrun swiftc -swift-version 6 -o /private/tmp/notevive-library-tests \
  app/macos/Library.swift app/macos/tests/LibraryTests.swift
/private/tmp/notevive-library-tests
```

Voir [les composants et licences](NOTICE.md).
