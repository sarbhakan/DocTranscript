"""Checks specific to the three affirmative, single-drug Px regression fixtures.

These predicates are not a clinical validator and never transform ASR output.
"""
import re
from p0.asr_compare import annotated_matches, meaning_words, words


def fixture_words(text):
    tokens = meaning_words(text)
    # Px-826 writes '1 gélule'; ASR may spell the feminine quantity 'une'.
    # Normalize this quantity in the scorer only, without counting every
    # indefinite article in free medical prose as a number.
    tokens = ['1' if token == 'une' and i + 1 < len(tokens)
              and tokens[i + 1] in {'gélule', 'gélules'} else token
              for i, token in enumerate(tokens)]
    # The existing scorer consumes 'de' in 'un quart de', but retains it
    # after the equivalent written glyph or slash fraction.
    return [token for i, token in enumerate(tokens)
            if not (token == 'de' and i and tokens[i - 1] in {'¼', '½', '¾'})]


def check_fixture(case, recognized):
    expected, actual = fixture_words(case['reference']), fixture_words(recognized)
    numeric = re.compile(r'(?:[+-]?\d+(?:[,.]\d+)?|[¼½¾])\Z')
    signature = lambda tokens: [token for token in tokens if numeric.fullmatch(token)]
    critical = {category: [sum(ok for _, ok in checks), len(checks)]
                for category, values in case['critical'].items()
                for checks in [annotated_matches(recognized, values, fixture_words)]}
    # None of these sources has a negation or a concentration. Catch additions which
    # would otherwise leave all annotated amounts present as subsequences.
    negators = {'pas', 'sans', 'ni', 'non', 'aucun', 'aucune', 'jamais'}
    no_new_negation = (set(actual) & negators) == (set(expected) & negators)
    no_concentration = not re.search(
        r'\b(?:mg|milligrammes?)\s*(?:/|par)\s*(?:ml|millilitres?|litres?)\b',
        recognized, flags=re.IGNORECASE)
    terms = annotated_matches(recognized, case['terms'], words)
    result = {'critical_span_presence': critical, 'numeric_sequence_equal': signature(actual) == signature(expected),
              'no_added_negation': no_new_negation, 'no_added_concentration': no_concentration,
              'terms': [sum(ok for _, ok in terms), len(terms)]}
    result['passed'] = (all(good == count for good, count in critical.values())
                        and result['numeric_sequence_equal'] and no_new_negation and no_concentration)
    return result
