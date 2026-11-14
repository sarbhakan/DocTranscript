# Essayer NoteVive 0.3.0 sur Windows 11

NoteVive transcrit dictées et notes en français, sur le PC. Il ne demande ni compte NoteVive, ni connexion, ni installation de Python, .NET ou d’un redistribuable Visual C++. Utilisez un compte de test et **des données fictives uniquement**. Cet essai ne qualifie pas l’usage en cabinet et la vitesse sur un PC à 8 Go reste à mesurer.

## 1. Télécharger, vérifier et ouvrir

1. Dans **Paramètres → Système → Informations système**, vérifiez que le système est Windows 11 avec un processeur **x64** Intel ou AMD. Le paquet ne cible pas Windows ARM. Un GPU dédié n’est pas nécessaire.
2. Dans les [Releases GitHub](https://github.com/sarbhakan/DocTranscript/releases), cherchez la préversion 0.3.0 et son fichier `NoteVive-Windows-x64-Essai.zip`. Si elle n’apparaît pas, sa publication n’est pas disponible : la préversion 0.1.0 utilise un autre moteur. Une fois le bon ZIP téléchargé, calculez son empreinte PowerShell :

   ```powershell
   Get-FileHash -Algorithm SHA256 -LiteralPath '.\NoteVive-Windows-x64-Essai.zip'
   ```

   Comparez le `Hash` aux 64 caractères annoncés dans la Release, sans tenir compte de la casse. Ne lancez pas un ZIP dont l’empreinte diffère. [Documentation Microsoft sur `Get-FileHash`](https://learn.microsoft.com/fr-fr/powershell/module/microsoft.powershell.utility/get-filehash).
3. Faites un clic droit sur le ZIP → **Extraire tout**, dans un dossier local hors d’un dossier synchronisé. Ouvrez `NoteVive.exe` depuis le dossier extrait. Gardez le dossier `runtime` et tous les fichiers à leur place. Vous pouvez couper Wi‑Fi et Ethernet avant ce premier lancement pour tester le parcours hors ligne. [Guide Microsoft sur les archives ZIP](https://support.microsoft.com/fr-fr/windows/experience/storage-filemanagement/zip-and-unzip-files).
4. Le paquet est non signé. Si les protections de Windows ou les règles du poste bloquent l’EXE, confiez le message au service informatique ou utilisez un poste de test autorisé. [Documentation Microsoft sur ces protections](https://support.microsoft.com/fr-fr/windows/security/windows-security/app-browser-control-in-the-windows-security-app).

## 2. Dicter, relire et retrouver une note

1. Cliquez sur **+ Transcription** (`Ctrl+N`), puis saisissez un titre, par exemple `Essai A — cheville`. Cliquez sur **Dicter** (`F9`, dans la fenêtre) et attendez **Micro ouvert**.
2. Dites : « Pas de douleur à la cheville droite. » Faites une pause et attendez que le texte apparaisse. Dites ensuite : « La gêne concerne la cheville gauche depuis cinq jours. » Le moteur commence à traiter le passage après une pause de 576 ms ; l’affichage prend ensuite le temps du calcul. Les passages s’ajoutent à la note modifiable et le dernier apparaît aussi dans **Dernier passage dicté**.
3. Cliquez sur **Arrêter** (`F9`) et laissez la finalisation se terminer. Relisez la note et vérifiez « pas », « droite », « gauche » et « cinq ». Corrigez dans le texte modifiable et choisissez **Enregistrer** (`Ctrl+S`) pour demander une sauvegarde immédiate. Le statut **Brouillon sauvegardé localement · À relire** confirme cette opération.
4. Pour classer la note, créez un dossier avec **+ Dossier**. Sélectionnez un dossier avant de cliquer sur le bouton pour créer un sous-dossier. **Dossier…** permet de renommer ou déplacer le dossier actif ; **Classer…** déplace la note affichée. Changez le titre dans l’éditeur.
5. Fermez puis rouvrez l’application. Retrouvez la note depuis l’arborescence ou tapez un mot du titre ou du texte dans **Rechercher**. Cochez **Dans tous les dossiers** pour élargir la recherche. Changez le tri entre dernière modification, date de création et titre. Les notes sont chiffrées pour le compte Windows courant dans `%LOCALAPPDATA%\NoteVive-Pilote\notes`, à part de l’application. Elles restent sur le même poste et le même compte si vous changez le dossier d’extraction du ZIP.

**Vocabulaire** ouvre un catalogue hors ligne : vous pouvez par exemple rechercher `hémoglobine` et consulter sa source. Cette consultation ne modifie pas la transcription. **Masquer la note** (`Ctrl+M`) interrompt une capture en cours ; réaffichez la note et relancez vous-même la dictée. L’application ne conserve aucun enregistrement audio, elle n’écrit pas dans les autres applications et n’importe pas de fichier audio dans ce paquet.

## 3. Dépanner

| Problème | Que vérifier |
| --- | --- |
| `F9` n’a pas d’effet | Revenez dans NoteVive et cliquez sur **Dicter**. Certains claviers demandent `Fn+F9`. |
| Le micro ne s’ouvre pas | Dans **Paramètres → Système → Son → Entrée**, vérifiez le micro par défaut. Vérifiez aussi **Confidentialité et sécurité → Microphone** selon les règles du poste. [Dépannage Microsoft](https://support.microsoft.com/fr-fr/windows/hardware/drivers/fix-microphone-problems). |
| Le texte tarde | Après une phrase courte, laissez du silence avant de reprendre. Notez le délai et précisez si la phrase apparaît avant ou après **Arrêter**. |
| Le moteur est absent, altéré ou ne répond plus | Si un nouveau lancement de dictée est proposé, essayez un passage fictif. Si l’arrêt du micro n’est pas confirmé, fermez l’application et signalez l’incident. Vérifiez l’empreinte et réextrayez le ZIP en entier si le paquet est en cause. |
| La note ne s’enregistre pas | Laissez la fenêtre ouverte, notez le message et essayez **Enregistrer**. Si NoteVive propose une copie, vérifiez que celle-ci réapparaît dans la bibliothèque avant de fermer. |

## 4. Comparer les deux postes

Suivez la [recette Windows 0.3.0](windows-recette-030.md) sur le PC de 8 Go sans GPU dédié et sur l’autre PC avec le même ZIP. Elle contient les dictées de contrôle, les chronomètres à relever et les essais de panne, de sauvegarde et de recherche. Consignez une panne avec les étapes, le résultat, le nombre d’occurrences, le SHA-256 du ZIP, la version Windows, le CPU, la mémoire et le type de micro. Partagez uniquement des observations et exemples fictifs.
