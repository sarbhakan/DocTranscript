# Outillage de la consolidation 0.4

Le plugin **Dev Toolkit Orchestrator 0.1.0** a été utilisé pour répartir le travail entre interface/recette, intégration Windows et entraînement/évaluation. Le coordinateur a raccordé les changements, vérifié les résultats et conservé une seule application distribuée.

## Sélection et installation

Les sources des trois aides recommandées ont été examinées avant usage :

- [ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) : principes de hiérarchie, contraste, espaces, lisibilité et parcours utilisateur. Pas de composant JavaScript ou de dépendance de ce dépôt dans le logiciel.
- [ponytail](https://github.com/DietrichGebert/ponytail) : démarche de modifications ciblées et vérifiables. Pas de moteur de transcription fourni par ce module.
- [i-have-adhd](https://github.com/ayghri/i-have-adhd) : consignes de clarté, d’étapes explicites et de réduction de la charge de lecture, pertinentes pour le guide débutant.

Consultation des README et licences le 14 novembre 2026 ; aucune installation ni exécution de leurs scripts. Les sources examinées déclarent la licence MIT. Aucun numéro de version figé n’est revendiqué pour cette lecture documentaire de leurs branches par défaut. Il n’y a pas de registre d’installation de ces modules, puisqu’ils ne sont pas installés.

## Technologies effectivement présentes

L’interface conserve les contrôles Windows natifs C++17, Win32 et Common Controls : navigation clavier, DPI et contraste élevé restent accessibles. Le thème GDI, les cartes, les états du micro et les lignes datées n’ajoutent pas de DLL à distribuer. La dictée externe utilise les API Microsoft UI Automation et SendInput lorsque le champ le permet ; le détail des vérifications et de leurs limites se trouve dans [le guide technique](dictee-externe.md).

Le moteur distribué repose sur whisper.cpp 1.8.5, le correctif amont de réinitialisation du générateur aléatoire, Whisper large-v3-turbo Q5_0, Silero VAD 6.2 et OpenBLAS 0.3.34. Les sources, licences et empreintes restent dans les verrous et attestations de construction. Les données de notes sont conservées localement avec DPAPI ; le catalogue de vocabulaire SQLite est consultatif.

L’ajustement expérimental utilise PyTorch 2.9.1, Transformers 4.57.3 et PEFT 0.18.0 dans un environnement Python 3.12 ARM64 isolé sur le Mac. Les wheels officielles sont verrouillées par SHA-256. Ces outils ne sont pas installés chez le médecin et ne sont pas ajoutés au ZIP Windows. Les commandes et les limites figurent dans [la documentation d’entraînement](../p0/training/README.md).

Un poids modifié n’est pas considéré meilleur parce que l’entraînement s’est exécuté. L’évaluation du candidat et la décision de distribution sont consignées séparément dans les rapports de validation.
