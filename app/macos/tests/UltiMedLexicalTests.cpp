#include "../native/UltiMedLexicalContext.h"

#include <cassert>
#include <iostream>

int main() {
    using notevive::LexicalContext;
    constexpr int blank = 14;
    LexicalContext ctx({" la", " cap", "lac", "laz", "iz", "umab", " abus", "caplacizumab",
                        " Décap", " DE", " 400", " quatre", " pas", " millilitres", "<blk>"});
    assert(ctx.set("caplacizumab\nCAPLACIZUMAB\nDécapeptyl\n400 milligrammes\n"
                   "un demi comprimé\nabsence\nsans fièvre\nvingt-cinq\nnon-insulino-dépendant") == 2);
    assert(ctx.enabled());
    const auto start = ctx.advance(LexicalContext::none, 1, false, true);
    assert(start != LexicalContext::none);
    assert(ctx.advance(LexicalContext::none, 7, true, true) != LexicalContext::none);
    assert(ctx.advance(LexicalContext::none, 7, false, true) == LexicalContext::none);
    assert(ctx.advance(start, 6, false, true) == LexicalContext::none);
    float logits[blank + 1];
    std::fill(std::begin(logits), std::end(logits), -15.f);
    logits[3] = 0;
    logits[2] = -.5f;
    assert(ctx.suggest(start, 3, logits, blank, false, true) == 2);
    assert(ctx.suggest(start, blank, logits, blank, false, true) == blank);
    logits[2] = -2.f;
    assert(ctx.suggest(start, 3, logits, blank, false, true) == 3);
    for (int protectedToken : {10, 11, 12, 13})
        assert(ctx.suggest(start, protectedToken, logits, blank, false, true) == protectedToken);

    assert(ctx.permits("Caplazizumab, pas 400 mg.", "Caplacizumab, pas 400 mg."));
    assert(ctx.permits("Décapepil 22,5 milligrammes.", "Décapeptyl 22,5 milligrammes."));
    assert(ctx.permits("Capiacizumab 1/2 comprimé.", "Caplacizumab 1/2 comprimé."));
    assert(!ctx.permits("Caplazizumab, pas 400 mg.", "Caplacizumab, 400 mg."));
    assert(!ctx.permits("Caplazizumab, pas 400 mg.", "Caplacizumab, pas 4 mg."));
    assert(!ctx.permits("Caplazizumab, pas 400 mg.", "Caplacizumab, pas 400 ml."));
    assert(!ctx.permits("Caplazizumab, un demi.", "Caplacizumab, un quart."));
    assert(!ctx.permits("Caplazizumab à droite.", "Caplacizumab à gauche."));
    assert(!ctx.permits("Caplazizumab, pas 400 mg.", "Caplacizumab pas 400 mg."));
    assert(!ctx.permits("La dose est notée.", "Caplacizumab La dose est notée."));
    assert(!ctx.permits("Médicament, pas 400 mg.", "Caplacizumab, pas 400 mg."));
    assert(ctx.set("caplacizumab\ncaplazizumab\n") == 2);
    assert(!ctx.permits("Caplazizumab, pas 400 mg.", "Caplacizumab, pas 400 mg."));
    std::string tooMany;
    for (size_t i = 0; i <= LexicalContext::maxPhrases; ++i) tooMany += "caplacizumab\n";
    bool rejected = false;
    try { ctx.set(tooMany); } catch (const std::invalid_argument &) { rejected = true; }
    assert(rejected && ctx.enabled());
    assert(ctx.set({}) == 0 && !ctx.enabled());
    std::cout << "UltiMed lexical checks passed\n";
}
