# Essayer NoteVive sur Windows 11

NoteVive est un prototype de dictée en français. Le moteur et le vocabulaire sont inclus dans le ZIP et fonctionnent localement. Il ne faut ni compte NoteVive, ni Python, ni .NET. **Utilisez seulement des phrases et des notes fictives.** Le paquet est non signé et cet essai ne qualifie ni l’usage en cabinet ni la fidélité médicale.

## 1. Vérifier le ZIP et le lancer

1. Choisissez un PC de test autorisé, avec un microphone et un compte Windows standard. Dans **Paramètres → Système → Informations système**, vérifiez que Windows 11 indique un processeur **x64** (Intel ou AMD). Ce paquet ne vise pas Windows ARM. Pour l’essai sur matériel modeste, utilisez un PC physique avec **8 Go de RAM et sans carte graphique dédiée**.
2. Récupérez `NoteVive-Windows-x64-Essai.zip` et son fichier `NoteVive-Windows-x64-Essai.zip.sha256` auprès de l’organisateur de l’essai. Dans PowerShell, depuis le dossier contenant le ZIP, exécutez :

   ```powershell
   Get-FileHash -Algorithm SHA256 -LiteralPath '.\NoteVive-Windows-x64-Essai.zip'
   ```

   Comparez les 64 caractères de la colonne `Hash` avec l’empreinte de référence publiée par l’organisateur (ou la première valeur du fichier `.sha256` reçu d’une source de confiance). Majuscules et minuscules sont équivalentes. Si les empreintes diffèrent ou si vous n’avez pas de référence fiable, arrêtez l’essai. Le SHA-256 vérifie la concordance des fichiers ; il ne remplace pas la signature de l’application. [Documentation Microsoft sur `Get-FileHash`](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/get-filehash?view=powershell-5.1).
3. Dans l’Explorateur, faites un clic droit sur le ZIP → **Extraire tout**. Choisissez un dossier local, hors dossier synchronisé. Ouvrez `NoteVive.exe` depuis le dossier extrait, avec `runtime` à côté de l’EXE. Ne déplacez pas l’EXE seul. [Guide Microsoft d’extraction des archives ZIP](https://support.microsoft.com/fr-fr/windows/experience/storage-filemanagement/zip-and-unzip-files).
4. Si SmartScreen, Smart App Control, l’antivirus ou une règle du poste signale ou bloque l’EXE, arrêtez-vous et transmettez le message à l’organisateur ou au service informatique. Demandez un poste de test autorisé ou une version signée et approuvée. Ne désactivez aucune protection, ne créez pas d’exception et ne lancez pas l’EXE en administrateur. [Documentation Microsoft sur ces protections](https://support.microsoft.com/fr-fr/windows/security/windows-security/app-browser-control-in-the-windows-security-app).

## 2. Dicter, relire et retrouver une note

1. Ouvrez **Nouvelle note** (`Ctrl+N`) et saisissez un titre fictif, par exemple `Essai A — cheville`. Au repos, vérifiez que NoteVive indique **Micro coupé**.
2. Cliquez sur **Dicter** ou appuyez sur `F9` quand NoteVive est au premier plan. Attendez **Micro ouvert · Dictée en cours**, puis lisez : « Pas de douleur de la cheville droite. La gêne concerne la cheville gauche depuis cinq jours. » La zone **Texte provisoire** peut changer pendant que vous parlez. Le texte finalisé rejoint la note modifiable ; seul ce dernier peut être sauvegardé.
3. Cliquez sur **Arrêter** ou appuyez à nouveau sur `F9`. Attendez la fin de la finalisation, puis vérifiez notamment « pas », « droite », « gauche » et « cinq ». Corrigez directement dans **Texte de la note**. La sauvegarde est automatique ; **Enregistrer** (`Ctrl+S`) permet de la demander tout de suite. Vérifiez le message **Brouillon sauvegardé localement · À relire** avant de fermer.
4. Rouvrez NoteVive et cliquez sur la note dans **Notes locales (UTC)**. Cette liste présente les notes par modification récente. Modifiez leur titre pour les retrouver plus facilement ; le pilote ne gère pas de dossiers ni d’étiquettes. Les notes chiffrées sont liées au compte Windows qui les a créées, sous `%LOCALAPPDATA%\NoteVive-Pilote\notes`. Déplacer ou effacer le ZIP ne retire pas ces notes. Le dossier chiffré n’est pas une sauvegarde transportable vers un autre poste.

Au repos, **Vocabulaire** permet de chercher `hémoglobine` et de consulter la provenance du libellé. Il ne modifie pas la dictée. **Masquer la note** (`Ctrl+M`) interrompt une capture en cours ; il faut réafficher la note, puis lancer explicitement la dictée. Le `F9` est propre à la fenêtre NoteVive. Le pilote n’écrit pas dans d’autres applications, n’enregistre pas l’audio et n’importe pas de fichiers audio.

## 3. Dépanner un essai

| Si vous observez… | Vérifiez… |
| --- | --- |
| `F9` n’a pas d’effet | Revenez dans NoteVive et essayez **Dicter**. Sur certains claviers, `Fn+F9` est nécessaire. |
| Le micro ne s’ouvre pas ou aucun texte n’apparaît | Dans **Paramètres → Système → Son → Entrée**, choisissez et testez le microphone par défaut. Dans **Confidentialité et sécurité → Microphone**, vérifiez que l’accès des applications de bureau est autorisé par les règles du poste. Attendez la fermeture de la capture avant de rebrancher ou de changer de micro, puis relancez l’essai. [Dépannage du microphone, Microsoft](https://support.microsoft.com/fr-fr/windows/hardware/drivers/fix-microphone-problems). |
| « Arrêt du microphone non confirmé. Fermez l’application. » | Fermez NoteVive, puis signalez l’incident avant de relancer la dictée. |
| Un fichier du moteur manque ou sa vérification échoue | Fermez NoteVive, vérifiez de nouveau le SHA-256 du ZIP et extrayez-le en entier dans un nouveau dossier local. N’ajoutez pas de DLL isolée. |
| La note ne s’enregistre pas | Laissez la fenêtre ouverte, notez le message et réessayez **Enregistrer**. Si NoteVive propose d’enregistrer une copie dans une nouvelle note, la note précédente reste intacte. Vérifiez que la copie apparaît dans la liste avant de fermer. |

## 4. Refaire l’essai sur le PC de 8 Go

Utilisez le même ZIP et les mêmes phrases sur le PC de 8 Go et, si possible, sur un second PC. Relevez chaque résultat comme **réussi**, **échoué** ou **non essayé**. L’absence de problème sur ces quelques essais ne valide pas la précision médicale.

| Essai | Résultat attendu ou observation à relever |
| --- | --- |
| Premier lancement après redémarrage, puis nouvelle dictée sans fermer NoteVive | Chronométrez approximativement l’attente de **Micro ouvert**, celle du premier texte après le début de la parole, puis le temps entre **Arrêter** et la fin de la finalisation. Indiquez ce qui s’affiche seulement après l’arrêt. |
| Deux à trois minutes de dictée fictive avec un navigateur et un document fictif ouverts | L’interface doit rester utilisable. Relevez tout gel, texte ajouté pendant le silence ou écart de transcription. Rejouez la phrase sur la cheville et vérifiez les quatre éléments sensibles. |
| Interruption pendant une dictée par réduction de la fenêtre, verrouillage (`Win+L`), veille ou débranchement du micro | Testez chaque interruption séparément. La capture doit s’arrêter sans redémarrer seule. Les segments déjà sauvegardés doivent rester disponibles ; le provisoire peut être perdu. |
| Démarrage et dictée avec le réseau déconnecté, si autorisé sur le poste | Relancez NoteVive hors connexion, dictez, enregistrez, puis rouvrez la note. Cela vérifie que ce parcours fonctionne hors ligne. Pour surveiller aussi les tentatives réseau, suivez la [procédure de recette Windows](p0-windows.md#5-vérifier-le-hors-ligne-et-contre-vérifier). |

Pour signaler un défaut à l’organisateur, envoyez le SHA-256 du ZIP, la version de Windows (`winver`), le modèle de processeur, la quantité de RAM et le type de micro (intégré ou USB, par exemple). Indiquez les étapes, le résultat attendu, le résultat observé, le message d’erreur s’il est anonymisé et le nombre de reproductions. Ne transmettez ni nom d’utilisateur, ni fichier de notes, ni audio, ni capture contenant une note ou une donnée patient.
