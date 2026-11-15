import unittest
from lexique.orphanet_domains import active_codes, classification_codes


class OrphanetDomainsTest(unittest.TestCase):
    def test_only_existing_active_pathologies_and_subtypes_are_selected(self):
        def disorder(code, state, level):
            return f'<Disorder><OrphaCode>{code}</OrphaCode><Totalstatus>{state}</Totalstatus><ClassificationLevel><Name>{level}</Name></ClassificationLevel></Disorder>'
        blob = ('<JDBOR><DisorderList count="4">' + disorder('1', 'Active', 'Pathologie')
                + disorder('2', 'Active', "Sous-type d'une pathologie")
                + disorder('3', 'Active', 'Groupe de pathologies')
                + disorder('4', 'Deprecated', 'Pathologie') + '</DisorderList></JDBOR>').encode()
        self.assertEqual(active_codes(blob), {'1', '2'})

    def test_classification_deduplicates_repeated_nodes_without_inventing_titles(self):
        blob = b'<JDBOR><Availability><Licence><ShortIdentifier>CC-BY-4.0</ShortIdentifier></Licence></Availability><ClassificationList count="1"><Classification id="146"><Name lang="fr">Titre exact</Name><Disorder><OrphaCode>1</OrphaCode></Disorder><Disorder><OrphaCode>1</OrphaCode></Disorder><Disorder><OrphaCode>9</OrphaCode></Disorder></Classification></ClassificationList></JDBOR>'
        spec = dict(id='146', title='Titre exact')
        self.assertEqual(classification_codes(blob, spec), {'1', '9'})
        for changed in [blob.replace(b'Titre exact', b'Autre titre'), blob.replace(b'CC-BY-4.0', b'Other'), blob.replace(b'count="1"', b'count="2"')]:
            with self.assertRaises(ValueError):
                classification_codes(changed, spec)


if __name__ == '__main__':
    unittest.main()
