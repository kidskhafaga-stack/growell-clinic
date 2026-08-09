"""Recognising one ingredient however it happens to be spelled.

A brand gets its paediatric dosing by matching its scientific name against the
curated reference. The match was exact — so ``PARACETAMOL(ACETAMINOPHEN)``,
which is how the Egyptian register writes it on **92 products**, matched
nothing, and 92 boxes of the commonest drug in paediatrics arrived with no
dose calculator behind them. ``CHOLECALCIFEROL(VITAMIN D3)`` is another 116.
``ACYCLOVIR`` and ``CEFALEXIN`` are the American and British spellings of
drugs the reference already holds under the other one.

Measured over the whole register: spelling accounts for **344 brands** that
can now be dosed from clinical data already written and already referenced —
2,018 linked → 2,362, with no new numbers and no new judgement.

An earlier version reached 2,613, and 251 of that was wrong. It stripped
brackets off this program's own ingredient names too, where a bracket usually
means a *route*: "Ofloxacin (otic)" is ear drops, and 27 systemic ofloxacin
products were being given its entry. See
``test_a_route_qualifier_is_a_fact_not_a_spelling``.

**The dangerous version of this fix is a fuzzy matcher, and there isn't one
here.** ``Cefixime`` and ``Cefuroxime`` are four letters apart and are
different antibiotics; a similarity score that brought them together would put
one cephalosporin's dose on another and nothing downstream would question it.
Every rule below is either a known orthographic pair or a synonym the register
itself printed in brackets beside the name it belongs to. The old exact match
failed *safely*; what replaced it has to fail the same way, and most of these
tests are about that rather than about the 595.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_a_synonym_in_brackets_is_the_same_drug():
    """The 92, and the 116.

    The register writes the other pharmacopoeia's name beside its own. Both
    halves are tried, because the reference may hold either one.
    """
    from app.utils.ingredient_names import variants

    assert "PARACETAMOL" in variants("PARACETAMOL(ACETAMINOPHEN)")
    assert "ACETAMINOPHEN" in variants("PARACETAMOL(ACETAMINOPHEN)")
    assert "CHOLECALCIFEROL" in variants("CHOLECALCIFEROL(VITAMIN D3)")
    assert "VITAMIN D3" in variants("CHOLECALCIFEROL(VITAMIN D3)")


def test_the_two_pharmacopoeias_spell_these_differently():
    """British and American packaging, both sold in Egypt."""
    from app.utils.ingredient_names import variants

    assert "ACICLOVIR" in variants("ACYCLOVIR")
    assert "ACYCLOVIR" in variants("ACICLOVIR")
    assert "CEFALEXIN" in variants("CEPHALEXIN")
    assert "CEPHALEXIN" in variants("CEFALEXIN")
    assert "ZINC SULPHATE" in variants("ZINC SULFATE")


def test_two_different_antibiotics_are_never_brought_together():
    """The failure this whole module is written to avoid.

    A similarity score would find these four letters apart and hand one
    cephalosporin the other's dose. Nothing here compares for closeness, so
    nothing here can make that mistake.
    """
    from app.utils.ingredient_names import variants

    assert "CEFUROXIME" not in variants("CEFIXIME")
    assert "CEFIXIME" not in variants("CEFUROXIME")
    assert "CEFTRIAXONE" not in variants("CEFOTAXIME")
    assert "AMOXICILLIN" not in variants("AMPICILLIN")

    # And no partial match in either direction. Checking only the pairs above
    # let a truncating variant through: adding `raw[:6]` to the variant list
    # kept every assertion green while making "CEFIXI" a lookup key.
    from app.utils.ingredient_names import match

    marker = object()
    assert match("CEFIXIME", {"CEFIX": marker}) is None
    assert match("CEFIX", {"CEFIXIME": marker}) is None
    assert all(len(v) >= len("CEFIXIME") for v in variants("CEFIXIME"))


def test_a_combination_is_never_matched():
    """Because dosing a box on one of its ingredients is the original sin.

    "PARACETAMOL+CAFFEINE" contains a drug the reference knows well. Dosing
    the box on it gives a child a correct dose of the paracetamol and an
    unexamined dose of everything else.
    """
    from app.utils.ingredient_names import match

    # The table must actually *contain* the combination, or this passes for
    # the wrong reason — measured: with the "+" guard deleted, the first
    # version of this test stayed green because no variant of
    # "PARACETAMOL+CAFFEINE" was a key. The reference really does hold
    # combinations ("Vitamins A + D", "Amoxicillin/Clavulanate"), so a
    # register row naming one would match without the guard.
    table = {"PARACETAMOL": object(), "VITAMINS A + D": object()}
    assert match("Vitamins A + D", table) is None
    assert match("PARACETAMOL+CAFFEINE", table) is None
    assert match("PARACETAMOL + CAFFEINE", table) is None
    assert match("PARACETAMOL", table) is not None


def test_nothing_matches_nothing():
    """An empty or unknown name is not an excuse to pick something."""
    from app.utils.ingredient_names import match, variants

    assert variants("") == []
    assert variants(None) == []
    assert match("", {"X": object()}) is None
    assert match("SOMETHING WE DO NOT HOLD", {"X": object()}) is None


def test_a_spelling_is_not_reassigned_once_claimed():
    """Two ingredients normalising alike must not swap by query order.

    Whichever one a brand ended up with would then depend on nothing anybody
    could see or reproduce.
    """
    from app.utils.ingredient_names import index_of

    class Fake:
        def __init__(self, en):
            self.name_en, self.name_ar = en, None

    first, second = Fake("Paracetamol"), Fake("Paracetamol")
    table = index_of([first, second])
    assert table["PARACETAMOL"] is first


def test_the_register_gains_the_brands_this_was_written_for(clinic):
    """End to end, and the number is the whole justification.

    Without the spelling table these 595 brands are in the catalogue, findable
    and printable, and silently have no dose behind them.
    """
    with clinic["app"].app_context():
        from app.models import Drug
        from app.utils.drugbook_seed import seed_drugbook
        from app.utils.egypt_drugs import seed_register

        seed_drugbook()
        seed_register()
        linked = Drug.query.filter(Drug.generic_id.isnot(None)).count()
        # 2,018 before the spelling table, 2,362 after — and not the 2,613 an
        # earlier version reached, because 251 of those were route confusions.
        assert 2300 < linked < 2500

        # And the drug the whole thing started from.
        para = Drug.query.filter(
            Drug.generic_name == "PARACETAMOL(ACETAMINOPHEN)").first()
        assert para is not None
        assert para.generic_id is not None
        assert para.dose_per_kg == 10          # from the curated reference


def test_no_combination_in_the_register_was_given_a_dose(clinic):
    """The safety property, checked against all 25,000 rather than argued.

    One brand does link to a combination — "A-D Vit" to "Vitamins A + D" — and
    that is a *curated* pairing from the reference's own brand list, not
    something the matcher did. It carries no dose, so nothing can be computed
    from it either way.
    """
    with clinic["app"].app_context():
        from app.models import Drug
        from app.utils.drugbook_seed import seed_drugbook
        from app.utils.egypt_drugs import seed_register

        seed_drugbook()
        seed_register()
        dosed_combos = (Drug.query
                        .filter(Drug.generic_name.like("%+%"),
                                Drug.dose_per_kg.isnot(None))
                        .count())
        assert dosed_combos == 0


def test_a_drug_the_clinic_typed_is_matched_the_same_way(clinic):
    """One table for both paths.

    Matching exactly for a drug somebody typed and loosely for one the
    register imported would make whether a box carries a dose depend on who
    entered it.
    """
    with clinic["app"].app_context():
        from app.models import Drug
        from app.utils.drugbook_seed import link_existing_drugs, seed_drugbook
        db = clinic["db"]

        seed_drugbook()
        db.session.add(Drug(trade_name="TYPED BY THE NURSE",
                            generic_name="Acyclovir", is_active=True))
        db.session.commit()

        link_existing_drugs()
        db.session.commit()
        typed = Drug.query.filter_by(trade_name="TYPED BY THE NURSE").first()
        assert typed.generic_id is not None


def test_a_route_qualifier_is_a_fact_not_a_spelling():
    """A bracket means opposite things in the two files this reads.

    In the register it is a synonym — "PARACETAMOL(ACETAMINOPHEN)" is one drug
    written twice. In this program's own reference it is usually a route:
    "Ofloxacin (otic)" is ear drops, and the bare word on a box may be oral
    tablets.

    Stripping both was measured across all 25,000 rows and linked 27 systemic
    ofloxacin products to the ear-drop entry, 21 chloramphenicol to the eye
    entry — whose systemic form causes grey baby syndrome — and 18
    ketoconazole to the topical entry, whose oral form is hepatotoxic and
    restricted. A route is a fact about the drug, not a way of spelling it.
    """
    from app.utils.ingredient_names import variants

    # Route-qualified: the bare name must NOT become a key.
    assert "OFLOXACIN" not in variants("Ofloxacin (otic)")
    assert "CHLORAMPHENICOL" not in variants("Chloramphenicol (eye)")
    assert "KETOCONAZOLE" not in variants("Ketoconazole (topical)")
    assert "BUDESONIDE" not in variants("Budesonide (inhaled)")

    # Synonym-qualified: the bare name and the synonym both should.
    assert "VITAMIN D" in variants("Vitamin D (cholecalciferol)")
    assert "CHOLECALCIFEROL" in variants("Vitamin D (cholecalciferol)")
    assert "OMEGA-3" in variants("Omega-3 (fish oil)")
    assert "FISH OIL" in variants("Omega-3 (fish oil)")
