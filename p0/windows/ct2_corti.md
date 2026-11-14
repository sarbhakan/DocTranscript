# Contrôle Corti du moteur CT2 sous Windows

Le test compare la fidélité de CTranslate2 sous Windows aux résultats déjà mesurés de Whisper.cpp sous macOS, sur les deux notes humaines françaises de Corti Med-Dictate qui contiennent les **12 négations préannotées**. Les deux notes couvrent aussi quatre doses et trois latéralités. Les entrées sont 18 tranches de même longueur, préparées par Silero GGML 6.2.0 et le découpage NoteVive à 576 ms avant l'essai CT2. L'évaluation CT2 utilise les mêmes dépendances, le même poids, le préchauffage Px et les mêmes options de décodage que le banc Px, sur quatre fils et en CPU INT8. Seul le temps CT2 Windows est mesuré dans ce contrôle ; les plateformes et les quantifications diffèrent.

Le workflow Windows peut refaire ce comparatif à la demande : **Actions → Windows — construction et recette → Run workflow**, puis cocher `compare_ct2`. Les tests du paquet natif et de son interface restent obligatoires ; les sondes CT2 et Corti sont des comparaisons de développement facultatives, absentes du ZIP utilisateur. Les builds ordinaires ne téléchargent pas leurs dépendances.

Depuis le dépôt, après la préparation du venv et du poids vérifiés pour le [banc Px](ct2_probe.py), utiliser PowerShell :

```powershell
$py = "$env:RUNNER_TEMP/ct2-venv/Scripts/python.exe"
$data = "$env:RUNNER_TEMP/ct2-corti-private"
$model = "$env:RUNNER_TEMP/ct2-turbo"
$result = "$env:RUNNER_TEMP/ct2-corti-metrics.json"
python -m p0.windows.ct2_corti fetch --data $data
if ($LASTEXITCODE) { exit $LASTEXITCODE }
try {
    & $py -m p0.windows.ct2_corti run --model $model --data $data --output $result
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
} finally {
    Remove-Item -LiteralPath $data -Recurse -Force
}
```

Le téléchargement vient de [l'index officiel](https://datasets-server.huggingface.co/first-rows?dataset=corti%2Fmed-dictate&config=fr&split=test), vérifie le chemin de la [révision](https://huggingface.co/datasets/corti/med-dictate/tree/2a840558d221b4f306c52419d58f93270ea599bb/fr) et vérifie les empreintes des références, du PCM 16 bits et de chaque tranche dans le [verrou](../packs/ct2-corti.lock.json). L'inférence n'appelle pas le réseau. Sur un autre PC, régler les quatre chemins de test. Conserver uniquement le JSON agrégé, hors des répertoires source et runtime du produit. N'attacher à la CI ni le WAV ni le répertoire privé. L'option facultative `--local-review` n'écrit les sorties brutes que hors CI, dans un fichier réservé à la relecture locale.

Le JSON donne les gains et pertes appariés par catégorie ; une perte de négation est visible même si un autre cas est amélioré. Les matches de spans et le WER normalisé ne détectent pas tous les ajouts et erreurs de portée. Vérifier localement les omissions, inversions et ajouts avant toute décision ; deux notes suffisent pour déceler certaines régressions, sans établir une validation clinique ni les performances sur un PC physique à 8 Go.

[Licence d'évaluation Corti](https://huggingface.co/datasets/corti/med-dictate/blob/2a840558d221b4f306c52419d58f93270ea599bb/LICENCE.md) : aucune utilisation pour entraînement ou ajustement. Source : Corti ApS, Nix et al., *Symphony for Speech-to-Text: Supporting Real-Time Medical Voice Interfaces*, 2026, [DOI 10.48550/arXiv.2605.16545](https://doi.org/10.48550/arXiv.2605.16545).
