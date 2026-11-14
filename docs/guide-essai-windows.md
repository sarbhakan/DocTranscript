# Installer et utiliser NoteVive sur Windows, pas à pas

[Retour à l’accueil du projet](../README.md) · **[Télécharger l’application Windows — ZIP, environ 544 Mo](https://github.com/sarbhakan/DocTranscript/releases/download/v0.3.0-essai/NoteVive-Windows-x64-Essai.zip)**

Ce guide concerne **NoteVive 0.3.0 pour Windows**. Il part du principe que vous découvrez GitHub. Vous pouvez suivre toutes les étapes avec la souris ; vous n’avez aucun logiciel de programmation à installer et aucun compte à créer pour télécharger l’application.

NoteVive transforme votre voix en texte sur votre PC. Le téléchargement nécessite Internet ; la dictée et la consultation des notes fonctionnent ensuite hors ligne, modèle inclus. **Cette version est un essai avec des données fictives uniquement.** Relisez toujours le résultat : une dose, un côté du corps ou une négation peuvent être mal transcrits.

**Aller directement à une étape :** [préparer le PC](#avant-de-commencer) · [télécharger](#telecharger) · [ouvrir l’application](#ouvrir) · [première dictée](#premiere-dictee) · [organiser les notes](#organiser-les-notes) · [dépannage](#depannage) · [transmettre un retour](#signaler-un-probleme).

<a id="avant-de-commencer"></a>

## 1. Avant de commencer

Prévoyez un PC sous **Windows 11, avec un processeur Intel ou AMD et un système x64**, un microphone et suffisamment de place pour le ZIP et son dossier extrait. Vous pouvez utiliser le micro intégré ou un micro externe. Aucune carte graphique dédiée n’est requise.

Pour connaître votre système, ouvrez le menu **Démarrer**, puis **Paramètres → Système → Informations système**. Relevez l’édition de Windows et le type du système. Le paquet proposé est destiné aux PC x64 ; il n’est pas une application Mac.

NoteVive vérifie automatiquement si le processeur permet la dictée. S’il manque les instructions appelées **AVX2** ou leurs extensions, un message l’indique et le micro reste fermé. Installer un logiciel supplémentaire ne rend pas ce processeur compatible. Les essais sur un PC physique à **8 Go de mémoire sans carte graphique dédiée** restent à faire : nous ne garantissons pas encore sa vitesse ni son bon fonctionnement sur cette configuration.

Sur un PC professionnel, appliquez les règles de votre organisation. Le paquet d’essai **n’est pas signé** et peut être bloqué au lancement ; la rubrique [dépannage](#depannage) explique quoi faire.

<a id="telecharger"></a>

## 2. Télécharger le bon fichier

Le plus simple est de cliquer sur **[Télécharger NoteVive pour Windows](https://github.com/sarbhakan/DocTranscript/releases/download/v0.3.0-essai/NoteVive-Windows-x64-Essai.zip)**. Le fichier s’appelle **`NoteVive-Windows-x64-Essai.zip`** et pèse environ **544 Mo**. Selon votre connexion, le téléchargement peut durer plusieurs minutes. Attendez sa fin.

Si vous partez de la page GitHub du projet :

1. Ouvrez **[la page de la version v0.3.0-essai](https://github.com/sarbhakan/DocTranscript/releases/tag/v0.3.0-essai)**. Sur GitHub, une page **Release** rassemble les fichiers d’une version à télécharger.
2. Descendez jusqu’à **Assets**, la liste des fichiers. Cliquez sur ce mot si la liste est repliée.
3. Cliquez sur **`NoteVive-Windows-x64-Essai.zip`**. La mention **Pre-release** signifie que c’est une version d’essai ; elle est attendue ici.

Le bouton vert **Code → Download ZIP** et les liens **Source code** contiennent les fichiers de développement, sans l’application prête à ouvrir. Le fichier **`.zip.sha256`** est une petite fiche de vérification du téléchargement. Son usage est expliqué à la [fin de ce guide](#verifier-le-telechargement).

Quand le téléchargement est terminé, utilisez le bouton de votre navigateur qui affiche le fichier dans son dossier, ou ouvrez l’**Explorateur de fichiers** de Windows puis **Téléchargements**. Si vous avez choisi un autre emplacement, ouvrez celui-ci.

<a id="ouvrir"></a>

## 3. Extraire le ZIP et ouvrir l’application

Un **ZIP** est un dossier compressé qui rassemble plusieurs fichiers. Il faut d’abord les extraire pour que l’application retrouve son moteur et son modèle.

1. Faites un **clic droit sur `NoteVive-Windows-x64-Essai.zip`**.
2. Choisissez **Extraire tout…**, puis un dossier local où vous pouvez écrire. Pour cet essai, choisissez un emplacement hors d’un dossier synchronisé avec OneDrive ou un autre service.
3. Cliquez sur **Extraire** et attendez la fin. Ouvrez le dossier extrait, puis le dossier **NoteVive** qu’il contient. [Aide Microsoft sur l’extraction des ZIP](https://support.microsoft.com/fr-fr/windows/experience/storage-filemanagement/zip-and-unzip-files).
4. Double-cliquez sur **`NoteVive.exe`**. Si Windows cache la fin des noms de fichiers, vous verrez **NoteVive**, avec le type **Application**.

Vous devez retrouver cette organisation dans le dossier extrait :

```text
NoteVive
├── NoteVive.exe          ← ouvrir ce fichier
├── runtime              ← laisser ce dossier à sa place
├── Licences
├── Build
├── LIRE-AVANT-ESSAI.txt
└── SHA256.txt
```

**Gardez tout le dossier NoteVive ensemble.** Ouvrir le programme à l’intérieur du ZIP, ou déplacer uniquement `NoteVive.exe` sur le Bureau, peut l’empêcher de fonctionner. Le programme présent dans `runtime` est un composant interne : ouvrez toujours le fichier indiqué ci-dessus.

L’application est dite *portable* : il n’y a pas d’assistant d’installation. Pour la rouvrir plus tard, revenez dans ce même dossier et double-cliquez sur le même fichier. Vous pouvez déconnecter Internet après le téléchargement pour vérifier le fonctionnement hors ligne.

Si une alerte Windows empêche l’ouverture, passez au [dépannage](#depannage) avant de poursuivre.

<a id="premiere-dictee"></a>

## 4. Faire une première dictée et vérifier la sauvegarde

Installez-vous dans un endroit calme. NoteVive utilise le **microphone par défaut de Windows**. Si vous avez plusieurs micros, vérifiez celui sélectionné dans **Paramètres → Système → Son → Entrée**.

1. Dans NoteVive, cliquez sur **+ Transcription**. Dans **Titre**, saisissez `Essai cheville`. Le titre suffit à commencer la sauvegarde de cette nouvelle note.
2. Cliquez sur **Dicter (F9)**. Pendant **Micro coupé · Préparation du moteur**, attendez : le micro est encore fermé. Commencez uniquement lorsque le message **Micro ouvert** apparaît.
3. Dites à voix normale : **« Pas de douleur à la cheville droite. »** Faites une pause et attendez que le texte apparaisse. Le calcul peut être long sur certains PC ; évitez de répéter immédiatement la phrase si rien ne s’affiche encore.
4. Dites ensuite : **« La gêne concerne la cheville gauche depuis cinq jours. »** Faites à nouveau une pause, puis cliquez sur **Arrêter (F9)**.
5. Attendez la fin de **Finalisation du texte…**. Le texte complet se trouve dans **Texte de la note (modifiable)**. Le cadre **Dernier passage dicté** ne montre que le dernier passage reconnu.
6. Relisez la note : retrouvez-vous **pas**, **droite**, **gauche** et **cinq jours** ? Si besoin, cliquez dans le texte et corrigez au clavier. Cliquez sur **Enregistrer**. Le message **Brouillon sauvegardé localement · À relire** confirme l’enregistrement.
7. Fermez la fenêtre, puis rouvrez `NoteVive.exe`. Dans **Transcriptions locales**, sélectionnez **Essai cheville** et vérifiez son titre et son texte.

**Le premier essai est réussi si** le micro s’ouvre, le texte rejoint la note, vous pouvez le corriger et la note revient après fermeture et réouverture. Notez séparément les erreurs de transcription et le délai d’affichage : un bon fonctionnement de l’interface ne garantit pas une reconnaissance fidèle.

La sauvegarde est automatique après les modifications, mais **Enregistrer** permet de la demander immédiatement. Une note entièrement vide, sans titre ni texte, n’est pas encore enregistrée. Avant de fermer, vérifiez la confirmation de sauvegarde et l’absence de message d’erreur.

<a id="organiser-les-notes"></a>

## 5. Retrouver et organiser les notes

Faites ces manipulations après l’arrêt de la dictée et la fin du traitement. Plusieurs commandes restent indisponibles pendant la capture ou la finalisation.

### Donner un nom à une transcription

Sélectionnez la note dans **Transcriptions locales**, modifiez le champ **Titre**, puis cliquez sur **Enregistrer**. Un titre comme `Essai cheville — 14 novembre` permet de la reconnaître facilement.

### Créer un dossier et un sous-dossier

1. Cliquez sur **Toutes les transcriptions** dans la liste des dossiers, puis sur **+ Dossier**. Saisissez `Mes essais` et validez : le dossier est créé au premier niveau.
2. Sélectionnez le dossier **Mes essais**, puis cliquez à nouveau sur **+ Dossier**. Saisissez `Médecine générale` et validez : ce dossier est créé à l’intérieur de **Mes essais**.
3. Pour ranger une note existante, retrouvez-la dans **Toutes les transcriptions** et sélectionnez-la. Cliquez sur **Classer…**, choisissez le dossier de destination et validez. Cette version Windows utilise ce bouton pour le classement.
4. Pour renommer ou déplacer un dossier, sélectionnez-le puis ouvrez **Dossier… → Renommer le dossier** ou **Déplacer le dossier…**.

Les dossiers de NoteVive servent à organiser la bibliothèque dans l’application. Vous n’avez pas à créer ou déplacer des fichiers dans l’Explorateur Windows. **Sans dossier** rassemble les notes qui n’ont pas été classées.

### Rechercher et trier

Dans **Rechercher dans le titre ou le texte**, saisissez un mot comme `cheville`. Pour chercher au-delà du dossier sélectionné, cochez **Dans tous les dossiers**, ou sélectionnez **Toutes les transcriptions**. Si cette dernière vue est déjà active, la case est désactivée parce que la recherche porte déjà sur toute la bibliothèque.

Le menu de tri propose **Dernière modification**, **Date de création** et **Titre (A à Z)**. Les deux tris par date placent les notes les plus récentes en premier. Les dates de création et de modification de la note sont également affichées sous le titre. Elles sont indiquées en **UTC**, un fuseau horaire qui peut différer de l’heure locale de votre PC.

Si une note semble avoir disparu, effacez le texte de recherche et choisissez **Toutes les transcriptions** avant de conclure qu’elle est perdue.

### Consulter le vocabulaire et masquer une note

**Vocabulaire** ouvre un catalogue médical local. Essayez par exemple une recherche sur `hémoglobine`. Il sert à consulter des termes et leur source ; il ne modifie pas la dictée et ne constitue pas un entraînement automatique du modèle.

**Masquer la note** cache la bibliothèque et interrompt une dictée en cours. Cliquez sur **Réafficher la note** pour la retrouver. Pour reprendre la capture, cliquez vous-même sur **Dicter** : le microphone ne se rouvre pas automatiquement.

### Raccourcis utiles, facultatifs

| Action dans la fenêtre NoteVive | Raccourci |
| --- | --- |
| Nouvelle transcription | `Ctrl+N` |
| Démarrer ou arrêter la dictée | `F9` — certains claviers demandent `Fn+F9` |
| Enregistrer | `Ctrl+S` |
| Masquer ou réafficher la note | `Ctrl+M` |

**Limites de cette version Windows :** le texte reste dans NoteVive. Le copier-coller, l’export de texte et l’insertion dans un autre logiciel ne sont pas disponibles. Aucun enregistrement audio n’est conservé et aucun fichier audio ne peut être importé dans l’application. Les instructions du prototype Mac peuvent décrire d’autres fonctions ; elles ne s’appliquent pas à ce ZIP Windows.

## 6. Comprendre ce qui se passe pendant la dictée

| Message ou bouton affiché | Ce que vous devez faire |
| --- | --- |
| **Micro coupé · Préparation du moteur** / **Annuler (F9)** | Attendre. Le modèle se prépare ; ne commencez pas à dicter. **Annuler** interrompt cette préparation. |
| **Micro ouvert** / **Arrêter (F9)** | Vous pouvez parler. Les phrases sont traitées après les pauses, puis ajoutées lorsque le calcul est terminé. |
| **Arrêt demandé…** | Attendre la confirmation de coupure du micro ; ne commencer aucune nouvelle dictée. |
| **Micro coupé · Finalisation du texte…** | Le micro est coupé mais les derniers mots sont encore en cours de traitement. Attendre avant de changer de note ou de fermer. |
| **Brouillon sauvegardé localement · À relire** | La sauvegarde a réussi. Relire les informations reconnues. |
| **Arrêt du microphone non confirmé. Fermez l’application.** | Fermer l’application comme demandé et signaler l’incident. |

Une pause déclenche le traitement ; elle ne garantit pas un affichage immédiat. Les mesures Windows disponibles dépassent encore l’objectif de rapidité du projet. Pour un retour utile, relevez approximativement le temps entre la fin d’une phrase et son apparition à l’écran.

<a id="depannage"></a>

## 7. Dépannage

### Je ne trouve pas NoteVive.exe

Vérifiez le nom du ZIP : **`NoteVive-Windows-x64-Essai.zip`**. S’il contient surtout `app`, `docs`, `p0` et des fichiers de code, vous avez téléchargé les sources. Revenez au [lien de l’application](#telecharger). Après extraction du bon ZIP, ouvrez le sous-dossier **NoteVive**. L’extension `.exe` peut être masquée par Windows ; cherchez alors **NoteVive**, de type **Application**.

### Windows bloque le programme ou affiche un avertissement de sécurité

Ce paquet d’essai n’a pas de signature de distribution. Windows ou la politique de votre organisation peut refuser son ouverture. **Transmettez le message exact et le lien de cette Release au service informatique, ou à la personne qui organise l’essai.** Sur un PC personnel, signalez également le blocage avant de poursuivre. Ne désactivez pas l’antivirus ou les protections de Windows pour suivre ce guide. [Explications Microsoft sur les protections des applications](https://support.microsoft.com/fr-fr/windows/security/windows-security/app-browser-control-in-the-windows-security-app).

### Rien ne s’affiche, ou un fichier / une DLL est annoncé manquant

Vérifiez que vous avez extrait **tout** le ZIP et que `runtime` est toujours à côté de `NoteVive.exe`. Ne lancez pas l’application depuis la vue du ZIP. Si nécessaire, fermez NoteVive et extrayez de nouveau le même ZIP dans un **nouveau dossier**, sans mélanger les fichiers de plusieurs versions. Si le problème persiste, indiquez si une fenêtre, une alerte ou un message est apparu. N’installez pas de DLL trouvée sur un site tiers : les composants nécessaires sont inclus dans le paquet.

### Le processeur est annoncé incompatible

Si NoteVive indique que le processeur ne prend pas en charge **AVX2 et ses extensions**, la dictée ne peut pas démarrer sur ce poste. La bibliothèque reste accessible. Utilisez un autre PC compatible pour l’essai et transmettez le message avec le modèle du PC si vous le connaissez.

### Le micro ne fonctionne pas, ou ma voix n’est pas reconnue

1. Vérifiez le branchement et le bouton de coupure du micro ou du casque.
2. Dans **Paramètres → Système → Son → Entrée**, sélectionnez le microphone voulu et vérifiez que Windows détecte votre voix avec son test du micro.
3. Dans **Paramètres → Confidentialité et sécurité → Microphone**, vérifiez l’accès au microphone et l’autorisation des **applications de bureau**, selon les règles de votre poste. NoteVive peut ne pas apparaître comme une application avec son propre interrupteur : le réglage des applications de bureau est global.
4. Fermez puis rouvrez NoteVive après avoir changé le micro, et attendez **Micro ouvert** avant de parler. [Dépannage du microphone par Microsoft](https://support.microsoft.com/fr-fr/windows/hardware/drivers/fix-microphone-problems).

Si `F9` ne répond pas, cliquez directement sur **Dicter** dans la fenêtre NoteVive.

### Le texte met longtemps à apparaître, ou certains mots sont faux

Commencez avec une seule phrase courte, laissez une pause et attendez le résultat. Cliquez sur **Arrêter**, puis attendez la fin de la finalisation. Notez le délai, la phrase fictive prononcée et le texte obtenu. Les erreurs sur une négation, une dose, une unité ou un côté du corps sont particulièrement utiles à signaler. Le catalogue **Vocabulaire** ne corrige pas ces erreurs automatiquement.

### Enregistrer échoue, ou une erreur survient pendant la dictée

En cas d’échec de sauvegarde, gardez la fenêtre ouverte, relevez le message et essayez **Enregistrer**. Si l’application propose de sauvegarder une copie, vérifiez que cette copie apparaît dans la bibliothèque avant de fermer. Le copier-coller ne permet pas de contourner ce problème dans cette version.

Après une panne du moteur, relisez ce qui a été conservé : le passage en cours peut manquer. Si le message **Arrêt du microphone non confirmé** apparaît, fermez l’application comme demandé. Après une fermeture inattendue, rouvrez la note et vérifiez les dernières phrases ; seule une sauvegarde réussie confirme leur conservation.

### Je ne retrouve pas mes notes après réouverture

Effacez la recherche et cliquez sur **Toutes les transcriptions**. Vérifiez que vous utilisez le **même compte Windows sur le même PC**. Changer de dossier d’application ne supprime pas les notes ; changer de compte ou de PC ne transfère pas la bibliothèque. Si le problème persiste, ne supprimez aucun fichier de notes pour tenter de le résoudre.

## 8. Fermer, mettre à jour ou retirer l’application

Avant de fermer, arrêtez la dictée, attendez la fin du traitement et vérifiez que la note a été enregistrée. Fermez ensuite la fenêtre. Pour reprendre, ouvrez le même `NoteVive.exe`.

Lorsqu’une nouvelle version sera publiée, téléchargez son ZIP depuis le dépôt, quittez l’ancienne application et extrayez le nouveau paquet dans son propre dossier. **Gardez chaque paquet complet** ; ne remplacez pas seulement l’EXE ou le modèle. Avec le même compte Windows sur le même PC, les notes sont conservées en dehors du dossier de l’application.

Pour retirer le programme, quittez-le puis retirez son dossier extrait et, si vous le souhaitez, le ZIP téléchargé. **Cela ne supprime pas les notes.** Leurs fichiers sont conservés séparément et chiffrés pour le compte Windows courant. Une copie sur une clé USB ne garantit pas de pouvoir les lire sur un autre poste ; cette version ne propose pas de migration de bibliothèque.

<details>
<summary>Information technique sur le stockage, pour le dépannage</summary>

Les notes et les dossiers se trouvent dans `%LOCALAPPDATA%\NoteVive-Pilote\notes`. La [notice de stockage](../app/windows/notes.md) décrit le chiffrement, la compatibilité et les conflits. Ne partagez pas ce dossier dans un signalement public et conservez les originaux en cas de problème.

</details>

<a id="signaler-un-probleme"></a>

## 9. Transmettre un résultat ou signaler un problème

Ouvrez le **[formulaire de retour d’essai](https://github.com/sarbhakan/DocTranscript/issues/new?template=essai-notevive.yml)**. GitHub demande un compte pour envoyer un retour, mais pas pour télécharger l’application. Si vous ne souhaitez pas créer de compte, transmettez les mêmes informations à la personne qui vous a fourni le lien du dépôt.

Indiquez la version **0.3.0**, l’étape suivie, le résultat attendu et ce qui s’est réellement passé. Ajoutez le message exact s’il y en a un, ainsi que votre version de Windows. Si vous connaissez le modèle du PC, sa mémoire et le type de micro, précisez-les ; sinon, indiquez simplement que vous ne savez pas.

Pour une erreur de transcription, donnez la **phrase fictive prononcée**, le **texte obtenu** et le **délai approximatif**. Vérifiez les captures d’écran avant de les joindre : aucun nom de patient, note réelle, enregistrement de consultation ou fichier de bibliothèque ne doit être publié.

Pour conduire une comparaison structurée sur deux postes, utilisez la [recette Windows 0.3.0](windows-recette-030.md). Elle complète ce premier essai par des contrôles de doses, de fractions, de négations, de performances et de sauvegarde.

<a id="verifier-le-telechargement"></a>

## 10. Vérifier le fichier téléchargé

Cette vérification technique permet de confirmer que le ZIP reçu correspond exactement au paquet publié. Elle peut être effectuée avec l’aide de la personne qui organise l’essai. Elle ne remplace pas la signature de l’application.

<details>
<summary>Afficher la procédure SHA-256 avec PowerShell</summary>

1. Téléchargez aussi le [fichier de vérification `.sha256`](https://github.com/sarbhakan/DocTranscript/releases/download/v0.3.0-essai/NoteVive-Windows-x64-Essai.zip.sha256). Il s’ouvre comme du texte, par exemple avec le Bloc-notes.
2. Ouvrez **PowerShell** depuis le menu Démarrer. Il n’est pas nécessaire de le lancer en administrateur.
3. Dans la commande ci-dessous, remplacez `C:\CHEMIN` par le dossier qui contient votre ZIP. Conservez les guillemets autour du chemin, puis exécutez la commande.

   ```powershell
   Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\CHEMIN\NoteVive-Windows-x64-Essai.zip'
   ```

4. Comparez les 64 caractères de la colonne **Hash** avec ceux du fichier `.sha256`, sans tenir compte des majuscules et minuscules. Pour **le ZIP v0.3.0-essai uniquement**, l’empreinte attendue est :

   ```text
   0ef1583902112316c5ea7c4af304e5f84e437276ec9ffec38704db5b119ae5c1
   ```

Si l’empreinte diffère, ne lancez pas le paquet : téléchargez-le à nouveau depuis le lien officiel et refaites la vérification. [Documentation Microsoft de `Get-FileHash`](https://learn.microsoft.com/fr-fr/powershell/module/microsoft.powershell.utility/get-filehash).

</details>
