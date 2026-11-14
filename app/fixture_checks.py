"""Checks specific to the three affirmative, single-drug Px regression fixtures.

These predicates are not a clinical validator and never transform ASR output.
"""
import re
from p0.asr_compare import annotated_matches, meaning_words, words
from p0.lexicon_ab import matches


NEGATION = re.compile(r"\b(?:ne|pas|sans|ni|non|aucun|aucune|jamais|absence)\b|\bn[’'](?=[^\W\d_])",
                      re.IGNORECASE)
CONCENTRATION = re.compile(
    r"\b(?:mg|g|µg|μg|mcg|milligrammes?|grammes?|microgrammes?)\s*"
    r"(?:[/⁄∕／]|par\s+(?:ml|l|millilitres?|litres?|doses?|comprimés?|gélules?)\b)",
    re.IGNORECASE)
NEGATIVE_NUMBER = re.compile(r"(?:[-−–—﹣－]\s*|\bmoins\s+)(?=\d)", re.IGNORECASE)
TIME_UNIT = re.compile(r"(?:jours?|semaines?|mois|heures?|minutes?)\Z")
FORM_UNIT = re.compile(r"(?:comprimés?|gélules?)\Z")
NUMERIC_TOKEN = re.compile(r"(?:[+-]?\d+(?:[,.]\d+)?|[¼½¾])\Z")


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


def fraction_spans_in_order(tokens, spans):
    previous_end = 0
    for label in spans:
        candidates = (end for variant in label.split('|') for start, end in matches(tokens, fixture_words(variant))
                      if start >= previous_end)
        end = min(candidates, default=None)
        if end is None:
            return False
        previous_end = end
    return True


def adjacent_amounts(tokens, unit_pattern):
    # Keep the amounts tied to the units that directly follow them. This
    # targeted check does not try to parse general medical instructions.
    return [(amount, unit.removesuffix('s') if unit != 'mois' else unit)
            for amount, unit in zip(tokens, tokens[1:])
            if NUMERIC_TOKEN.fullmatch(amount) and unit_pattern.fullmatch(unit)]


def check_fixture(case, recognized):
    reference = case['reference']
    expected, actual = fixture_words(reference), fixture_words(recognized)
    signature = lambda tokens: [token for token in tokens if NUMERIC_TOKEN.fullmatch(token)]
    critical = {category: [sum(ok for _, ok in checks), len(checks)]
                for category, values in case['critical'].items()
                for checks in [annotated_matches(recognized, values, fixture_words)]}
    # None of these sources has a negation or a concentration. Catch additions which
    # would otherwise leave all annotated amounts present as subsequences.
    no_new_negation = NEGATION.findall(recognized.casefold()) == NEGATION.findall(reference.casefold())
    no_concentration = not CONCENTRATION.search(recognized)
    # The text normalizer discards punctuation, including minus signs. Check
    # signed amounts on the source as well as spoken "moins" before an amount.
    no_negative_number = not NEGATIVE_NUMBER.search(recognized) and not NEGATIVE_NUMBER.search(' '.join(actual))
    fraction_ordered = fraction_spans_in_order(actual, case['critical'].get('fraction', []))
    duration_match = adjacent_amounts(actual, TIME_UNIT) == adjacent_amounts(expected, TIME_UNIT)
    form_match = adjacent_amounts(actual, FORM_UNIT) == adjacent_amounts(expected, FORM_UNIT)
    terms = annotated_matches(recognized, case['terms'], words)
    # These three inputs are public fictional fixtures. Retain numbers only so a
    # failed comparison can distinguish notation issues from changed quantities
    # without publishing the ASR text. This helper is not used on patients' notes.
    expected_numbers, actual_numbers = signature(expected), signature(actual)
    result = {'critical_span_presence': critical, 'numeric_sequence_equal': actual_numbers == expected_numbers,
              'expected_numeric_sequence': expected_numbers, 'actual_numeric_sequence': actual_numbers,
              'no_added_negation': no_new_negation, 'no_added_concentration': no_concentration,
              'no_negative_number': no_negative_number, 'fraction_spans_ordered': fraction_ordered,
              'duration_amounts_equal': duration_match, 'administered_form_amounts_equal': form_match,
              'terms': [sum(ok for _, ok in terms), len(terms)]}
    # Mentioning the correct evening half before the correct morning half
    # changes narration order, not either fraction's explicit time of use.
    result['passed'] = (all(good == count for good, count in critical.values())
                        and result['numeric_sequence_equal'] and no_new_negation and no_concentration
                        and no_negative_number and duration_match and form_match)
    return result
