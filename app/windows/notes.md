# Bibliothèque locale NoteVive pour Windows

Les notes, les dossiers et les sous-dossiers sont conservés dans le dossier de données locales du compte Windows :

```text
%LOCALAPPDATA%\NoteVive-Pilote\notes
```

Ce dossier est commun aux copies de l’application utilisées par le même compte Windows sur le même poste. Il n’est pas créé dans le répertoire extrait du ZIP. Une note garde le même identifiant et la même date de création. Sa date de modification avance lorsqu’un changement de texte, de titre ou de dossier est enregistré. Déplacer ou renommer un dossier ne réécrit pas les notes qu’il contient.

## Compatibilité et récupération

- Les fichiers de note `*.nvn` de l’ancien pilote (`NVN1`) restent lisibles et apparaissent sans dossier. Aucune conversion en masse n’est effectuée. Une note rangée dans un dossier utilise `NVN2`, dont l’unique champ supplémentaire est l’identifiant de dossier. Replacer cette note dans « Sans dossier » l’enregistre à nouveau au format `NVN1`. L’ancien pilote ne sait pas lire les notes `NVN2`.
- Les dossiers sont des enregistrements `*.nvf` indépendants, qui conservent le nom, les dates et l’identifiant du parent. La limite est de 1 000 dossiers et 32 niveaux. Les identifiants de notes et de dossiers ne dépendent pas de leurs noms. Un cycle ou une destination absente sont refusés.
- Notes, titres, dates et rattachements sont contenus dans des fichiers chiffrés par le service DPAPI du compte Windows. Les noms de fichiers ne donnent que des identifiants techniques. L’écriture utilise un verrou commun, un temporaire chiffré et un remplacement atomique. Une révision plus récente écrite par une autre copie déclenche un conflit explicite plutôt qu’un écrasement.
- Si un élément est illisible, la bibliothèque garde les autres éléments disponibles et signale la lecture partielle. Une note dont le dossier a disparu reste dans l’historique et apparaît aussi sous « Sans dossier », sans modifier le fichier existant. Le moteur de consultation ne répare pas les fichiers en silence. Conserver les fichiers originaux lors d’un diagnostic ; restaurer ou déplacer une copie sous un autre compte ou poste peut ne pas être possible avec DPAPI.

La recherche compare le titre et le texte en mémoire, sans index de recherche en clair. Elle ignore la casse, les accents du français, les ligatures et les différences courantes d’apostrophe et d’espacement. Les tris disponibles comparent la dernière modification décroissante, la date de création décroissante ou le titre alphabétique normalisé. Les dates persistées sont en UTC, à la milliseconde.

## Vérification d’ingénierie

Le test C++ portable vérifie les octets d’un exemple historique NVN1 construit indépendamment du générateur, la réouverture, les déplacements et cycles, les dates, la recherche et la résistance à des formats incomplets. Depuis la racine :

```sh
clang++ -std=c++17 -Wall -Wextra -Werror -g -fsanitize=address,undefined \
  app/windows/notes_model_test.cpp -o /tmp/notevive-notes-model-test
/tmp/notevive-notes-model-test
```

Pour vérifier également DPAPI et le stockage natif, compiler le test séparé avec Zig puis le lancer sous Windows dans une session utilisateur ordinaire. Il crée et retire son seul dossier temporaire de test sans utiliser la bibliothèque du compte :

```sh
zig c++ -target x86_64-windows-gnu -std=c++17 -O2 \
  -DUNICODE -D_UNICODE -DNOTEVIVE_NOTES_TEST \
  app/windows/notes.cpp app/windows/notes_test.cpp \
  -lcrypt32 -lole32 -lshell32 -luuid -o notes-test.exe
```

Sur Windows, tester ensuite dans l’interface avec des notes fictives : ouvrir une ancienne note, la renommer, la ranger dans un sous-dossier, fermer puis rouvrir et vérifier son titre, sa date de création et son texte. Rechercher un terme accentué sans son accent, changer le tri, et déplacer le parent pour vérifier que les notes restent associées aux bons dossiers.
