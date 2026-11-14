"""Fictional test scripts; references are never sent to the decoder."""

# The ten long scripts previously proposed to stress NoteVive. Each sentence is
# rendered separately, with known silence between sentences, to test the VAD.
# Critical spans use number words for the voice and accept numerical equivalents.
# A pipe separates acceptable written variants for a single occurrence.
LONG = [
    ("medical-01", "medecine-interne", [
        "En réunion de médecine interne et de néphrologie, le brouillon distingue une granulomatose éosinophilique avec polyangéite, dite syndrome de Churg-Strauss, d’une polyangéite microscopique avec anticorps anti-myéloperoxydase.",
        "Le nom avacopan figure dans la liste des médicaments discutés.",
        "La case d’essai contient trente milligrammes, et non trois milligrammes.",
        "Aucune hémoptysie n’a été rapportée, mais l’absence d’hématurie n’a pas été vérifiée.",
    ], ["granulomatose éosinophilique avec polyangéite", "Churg-Strauss",
        "polyangéite microscopique", "anti-myéloperoxydase", "avacopan"], {
        "dose": ["30 milligrammes et non 3 milligrammes"],
        "negation": ["aucune hémoptysie", "absence d’hématurie n’a pas été vérifiée"],
    }),
    ("medical-02", "neurologie", [
        "En consultation de neurologie neuromusculaire, le compte rendu mentionne une myasthénie avec anticorps anti-récepteur de l’acétylcholine, un ptosis droit fluctuant et une diplopie binoculaire, mais aucune dysphagie.",
        "Le dossier fictif contient les noms efgartigimod alfa, rozanolixizumab et ravulizumab.",
        "Sur la ligne de simulation, j’avais dicté zéro virgule soixante-quinze millilitre ; je corrige : zéro virgule zéro soixante-quinze millilitre, et aucune injection n’a été réalisée.",
    ], ["myasthénie", "acétylcholine", "ptosis", "diplopie binoculaire",
        "efgartigimod alfa", "rozanolixizumab", "ravulizumab"], {
        "dose": ["0,75 millilitre je corrige 0,075 millilitre"],
        "negation": ["aucune dysphagie", "aucune injection n’a été réalisée"],
        "latéralité": ["ptosis droit"],
    }),
    ("medical-03", "hematologie", [
        "En hématologie, le dossier évoque un purpura thrombotique thrombocytopénique avec schizocytes, thrombopénie et activité ADAMTS treize à zéro virgule treize pour cent, et non zéro virgule trois pour cent.",
        "Le caplacizumab et l’apadamtase alfa figurent sur deux lignes distinctes.",
        "Le chiffre de dix milligrammes appartient à la première ligne ; la deuxième n’a pas de dose renseignée.",
        "Le premier prélèvement est négatif, le second ne l’est pas.",
    ], ["purpura thrombotique thrombocytopénique", "schizocytes", "thrombopénie",
        "ADAMTS-13|ADAMTS treize", "caplacizumab", "apadamtase alfa"], {
        "dose": ["0,13 pour cent et non 0,3 pour cent", "10 milligrammes appartient à la première ligne"],
        "negation": ["deuxième n’a pas de dose", "premier prélèvement est négatif le second ne l’est pas"],
    }),
    ("medical-04", "genetique", [
        "En génétique métabolique, le dossier fictif oppose une maladie de Fabry avec déficit en alpha-galactosidase A à un déficit en lipase acide lysosomale.",
        "Le compte rendu cite le migalastat et la sébélipase alfa sans les intervertir.",
        "La première ligne de test mentionne un demi comprimé, la deuxième un quart de comprimé et la troisième trois quarts de comprimé.",
        "Aucun de ces fragments n’a été administré.",
    ], ["maladie de Fabry", "alpha-galactosidase A", "lipase acide lysosomale",
        "migalastat", "sébélipase alfa"], {
        "fraction": ["un demi comprimé", "un quart de comprimé", "trois quarts de comprimé"],
        "negation": ["aucun de ces fragments n’a été administré"],
    }),
    ("medical-05", "ophtalmologie", [
        "En neuro-ophtalmologie, le compte rendu distingue une microangiopathie cochléo-encéphalo-rétinienne de Susac d’une neuromyélite optique avec anticorps anti-aquaporine quatre.",
        "Le satralizumab est cité dans le second dossier, pas dans le premier.",
        "L’angiographie rétinienne décrit une occlusion artériolaire temporale supérieure à gauche et aucune occlusion à droite.",
        "Le volume du flacon de simulation est de zéro virgule trois millilitre ; zéro virgule trois millimètre correspond à une mesure sur l’image.",
    ], ["microangiopathie cochléo-encéphalo-rétinienne", "Susac", "neuromyélite optique",
        "anti-aquaporine-4|anti-aquaporine quatre", "satralizumab", "angiographie rétinienne", "occlusion artériolaire"], {
        "dose": ["0,3 millilitre 0,3 millimètre"],
        "negation": ["second dossier pas dans le premier", "aucune occlusion à droite"],
        "latéralité": ["temporale supérieure à gauche"],
    }),
    ("medical-06", "pediatrie", [
        "En pédiatrie métabolique, le compte rendu mentionne une mucopolysaccharidose de type quatre A, dite maladie de Morquio, avec déficit en N-acétylgalactosamine six sulfatase, dysplasie spondylo-épiphyso-métaphysaire et hypoplasie de l’odontoïde.",
        "L’élosulfase alpha est citée dans la liste.",
        "L’étiquette fictive indique deux virgule cinq milligrammes par millilitre, tandis que la seringue de démonstration contient deux virgule cinq millilitres.",
        "Aucune compression médullaire n’est décrite.",
    ], ["mucopolysaccharidose de type 4 A|mucopolysaccharidose de type IV A|mucopolysaccharidose de type quatre A",
        "maladie de Morquio", "N-acétylgalactosamine-6-sulfatase|N-acétylgalactosamine six sulfatase", "dysplasie spondylo-épiphyso-métaphysaire",
        "hypoplasie", "odontoïde", "élosulfase alpha|élosulfase alfa"], {
        "dose": ["étiquette fictive indique 2,5 milligrammes par millilitre",
                 "seringue de démonstration contient 2,5 millilitres"],
        "negation": ["aucune compression médullaire n’est décrite"],
    }),
    ("medical-07", "infectiologie", [
        "En infectiologie de transplantation, la discussion porte sur une infection à cytomégalovirus après allogreffe de cellules souches hématopoïétiques.",
        "Le maribavir, le valganciclovir et le foscarnet sont cités dans cet ordre.",
        "Le formulaire de test affichait quatre cents milligrammes et non quatre milligrammes.",
        "La charge virale du premier prélèvement était de mille cinq cents unités internationales par millilitre ; pour le second, aucun résultat n’a été rendu.",
    ], ["cytomégalovirus", "allogreffe de cellules souches hématopoïétiques",
        "maribavir", "valganciclovir", "foscarnet"], {
        "dose": ["400 milligrammes et non 4 milligrammes", "1500 unités internationales par millilitre"],
        "negation": ["pour le second aucun résultat n’a été rendu"],
    }),
    ("medical-08", "oncologie", [
        "En oncogénétique, la réunion consacrée à la maladie de von Hippel-Lindau mentionne un hémangioblastome cérébelleux, une tumeur neuroendocrine pancréatique et le belzutifan, également appelé Welireg.",
        "Je corrige la mesure de la lésion cérébelleuse : six virgule cinq millimètres, pas seize virgule cinq.",
        "La ligne d’essai contient quarante milligrammes, et non quatorze.",
        "Aucun carcinome rénal gauche n’a été identifié ; le rein droit n’était pas dans le champ de l’examen.",
    ], ["maladie de von Hippel-Lindau", "hémangioblastome cérébelleux",
        "tumeur neuroendocrine pancréatique", "belzutifan", "Welireg"], {
        "dose": ["6,5 millimètres pas 16,5", "40 milligrammes et non 14"],
        "negation": ["aucun carcinome rénal gauche n’a été identifié",
                     "rein droit n’était pas dans le champ"],
    }),
    ("medical-09", "cardiologie", [
        "En consultation d’hypertension pulmonaire, le compte rendu fictif cite un cathétérisme cardiaque droit, une pression artérielle pulmonaire moyenne de trente-deux millimètres de mercure et une résistance vasculaire pulmonaire de quatre virgule deux unités Wood.",
        "Le nom sotatercept apparaît à côté de zéro virgule trois milligramme par kilogramme, pas trois milligrammes par kilogramme.",
        "Aucune syncope à l’effort n’est rapportée depuis trois semaines ; la dernière présyncope remonte à trois jours.",
    ], ["hypertension pulmonaire", "cathétérisme cardiaque droit", "unités Wood", "sotatercept", "présyncope"], {
        "dose": ["32 millimètres de mercure", "4,2 unités Wood",
                 "0,3 milligramme par kilogramme pas 3 milligrammes par kilogramme"],
        "negation": ["aucune syncope à l’effort n’est rapportée"],
        "délai": ["depuis 3 semaines", "présyncope remonte à 3 jours"],
    }),
    ("medical-10", "hematologie", [
        "Pour l’hémoglobinurie paroxystique nocturne, le dossier de démonstration comporte trois noms proches à ne pas fusionner : pegcetacoplan, iptacopan et danicopan.",
        "Je relis les trois valeurs de test : vingt-cinq microgrammes, zéro virgule vingt-cinq milligramme et deux virgule cinq milligrammes.",
        "Le demi comprimé a été mentionné dans le premier brouillon ; je corrige, c’était un quart de comprimé, et aucun comprimé n’a été pris.",
        "Pas de douleur à gauche, douleur à droite, et pas l’inverse.",
    ], ["hémoglobinurie paroxystique nocturne", "pegcetacoplan|pegcétacoplan", "iptacopan", "danicopan"], {
        "dose": ["25 microgrammes 0,25 milligramme et 2,5 milligrammes"],
        "fraction": ["le demi comprimé", "un quart de comprimé"],
        "negation": ["aucun comprimé n’a été pris", "pas de douleur à gauche douleur à droite et pas l’inverse"],
    }),
]

# Reused public benchmark files. These annotations select specific fields, not
# the complete texts or audio, which stay in the local P0 lot.
PUBLIC = [
    ("px-212", "infectiologie", ["norfloxacine"], {"dose": ["400 milligrammes"]}),
    ("px-1331", "ophtalmologie", ["lacrifluid"], {"dose": ["0,13 pour cent"]}),
    ("px-584", "cardiologie", ["sotalex"], {"dose": ["80 milligrammes"],
                                          "fraction": ["un demi le matin", "un demi le soir|un demi soir"]}),
    ("px-23", "neurologie", ["imovane"], {"dose": ["7,5 milligrammes"], "fraction": ["un quart de comprimé"]}),
    ("px-634", "pneumologie", ["ventoline"], {"dose": ["100 microgrammes"], "quantité": ["2 bouffées", "2 bouffées"]}),
    ("px-597", "oncologie", ["décapeptyl|decapeptyl"], {"dose": ["22,5 milligrammes"]}),
    ("px-173", "neurologie", ["lamictal"], {"dose": ["25 milligrammes"]}),
    ("dev-04", "medecine-interne", ["méthotrexate"], {"dose": ["7,5 milligrammes"],
                                                     "negation": ["prise quotidienne n’est pas confirmée"]}),
    ("dev-05", "medecine-generale", ["lévothyroxine"], {"dose": ["25 microgrammes", "50 microgrammes"]}),
    ("dev-06", "medecine-generale", [], {"dose": ["0,3 millilitre"],
                                        "negation": ["concentration n’est pas renseignée", "pas une masse"]}),
    ("dev-08", "medecine-generale", [], {"negation": ["pas de douleur de la cheville droite"],
                                        "latéralité": ["douleur de la cheville gauche"]}),
    ("dev-17", "neurologie", ["paresthésie"], {"negation": ["pas de paresthésie du pouce droit|pas de paresthésie de pouce droit",
                                                           "n’a pas été vérifié"], "latéralité": ["main gauche"]}),
    ("dev-19", "hematologie", [], {}),
    ("dev-20", "ophtalmologie", [], {}),
    ("dev-noise-12s", "medecine-interne", [], {}),
    ("dev-noise-30s", "infectiologie", [], {}),
    ("dev-silence-08s", "cardiologie", [], {}),
    ("dev-silence-30s", "neurologie", [], {}),
]

# Ordinary language and deliberately plausible distractors. The proper terms
# below are scored as intrusions only; they are not sent to the ASR process.
ORDINARY = [
    ("leurre-01", "hematologie", [
        "J’ai posé la cape là-bas sur le dossier bleu, entre le classeur et le catalogue.",
        "Il n’y a aucun nouveau courrier à distribuer et la réunion est reportée à jeudi.",
    ], ["caplacizumab", "apadamtase alfa", "purpura thrombotique thrombocytopénique"]),
    ("leurre-02", "infectiologie", [
        "Valentin a vérifié le fossé et le carnet de livraison avant le rendez-vous.",
        "L’équipe a compté quatre cents cartons et non quatre, puis a fermé le quai de droite.",
    ], ["valganciclovir", "foscarnet", "maribavir"]),
    ("leurre-03", "ophtalmologie", [
        "La grille était temporairement bloquée à gauche, mais il n’y avait pas de défaut à droite.",
        "Sonia a rendu son sac à la réception et reprend la route à dix heures.",
    ], ["Susac", "satralizumab", "occlusion artériolaire"]),
    ("leurre-04", "genetique", [
        "La fabrique a expédié un demi carton le matin et un quart de carton le soir.",
        "La seconde commande n’a pas été livrée, et le bordereau indique une erreur de saisie.",
    ], ["maladie de Fabry", "migalastat", "sébélipase alfa"]),
]
