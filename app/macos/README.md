# Essayer NoteVive sur Mac

**Version d’essai : Mac Apple Silicon (puce série M), macOS 15 ou ultérieur.** Elle inclut le modèle français et fonctionne hors ligne. Le paquet est signé localement, sans certificat Apple Developer ID ni notarisation. L’essai doit utiliser uniquement des phrases fictives.

1. Copiez `NoteVive-Mac.zip` dans un dossier local hors iCloud (par exemple `Téléchargements` s’il n’est pas synchronisé), extrayez l’archive en entier puis ouvrez `NoteVive-Mac.app` dans le Finder. Si une règle du poste refuse le lancement, demandez une version signée et approuvée plutôt que de modifier les protections du poste.
2. Cliquez sur **Dicter** ou faites **⌘D**. Au premier essai, macOS demande votre autorisation d’accès au micro. Attendez **Micro ouvert** puis dites : « Pas de douleur de la cheville droite. La gêne concerne la cheville gauche depuis cinq jours. » Si l’autorisation a été refusée, vous pouvez vérifier le réglage dans **Réglages Système → Confidentialité et sécurité → Microphone**.
3. Pendant la dictée, l’hypothèse apparaît dans **Texte provisoire**. Les segments que le moteur termine rejoignent **Brouillon à relire**. Cliquez sur **Arrêter**, attendez la finalisation puis corrigez le brouillon, en vérifiant « pas », « droite », « gauche » et « cinq ».
4. Si vous voulez conserver le résultat, cliquez sur **Exporter le texte…** et choisissez un dossier local hors synchronisation. Le fichier TXT n’est pas chiffré. Le brouillon reste en mémoire tant que l’application est ouverte. Le prototype Mac n’a pas de bibliothèque de notes ni de catalogue intégré.

La dictée s’arrête si vous quittez l’application, réduisez la fenêtre, passez à une autre application ou si le périphérique audio change. Le provisoire peut alors être perdu ; le texte déjà transféré reste dans le brouillon. Le micro ne se rouvre que sur demande. Aucune capture audio n’est conservée et aucune donnée n’est envoyée par l’application.

## Refaire le paquet

Sur un Mac Apple Silicon avec Xcode et Python 3.11+, préparer les poids et notices ONNX dans `app/private/downloads/`, suivant les noms, liens et empreintes du [verrou des dépendances](../inputs.lock.json) : `encoder.onnx`, `decoder.onnx`, `joiner.onnx`, `tokens.txt`, `ONNX-LICENSE`, `ONNX-ThirdPartyNotices.txt`. Préparer aussi le [runtime Sherpa-ONNX macOS arm64 2.0.1](https://github.com/k2-fsa/sherpa-onnx/releases/download/v2.0.1/sherpa-onnx-v2.0.1-osx-arm64-shared-no-tts.tar.bz2) sous le nom `sherpa-macos-smoke.tar.bz2` ; son empreinte est dans le script de compilation. Les deux bibliothèques et les modèles sont copiés dans l’application. Aucun téléchargement ne se produit à la compilation ou à l’exécution.

```sh
python3 app/macos/build_macos.py --zip
```

Cette commande produit `dist/NoteVive-Mac.app`, `dist/NoteVive-Mac.zip` et l’empreinte du ZIP. Si les sorties existent, choisir un nouveau chemin `--output` ou mettre à part les précédentes. Après extraction hors d’un dossier synchronisé, vérifier la signature et rejouer la reconnaissance locale avec un WAV de test fictif ou public (PCM 16 bits, mono, jusqu’à 20 Mio) :

```sh
codesign --verify --deep --strict /chemin/NoteVive-Mac.app
/chemin/NoteVive-Mac.app/Contents/MacOS/NoteVive --self-test < /chemin/essai.wav
```

Le test de fichier fait passer des tranches audio par le même moteur en flux que la dictée et indique le nombre d’hypothèses et le texte final. Il ne sollicite pas le micro et ne démontre pas la précision médicale. Voir [les composants et licences](NOTICE.md).
