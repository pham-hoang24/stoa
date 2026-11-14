"""Seam: stoa.qparse.quoted — pulling room/storey names out of questions in many languages."""
from stoa.qparse import quoted


def test_ascii_single_quotes():
    assert quoted("What is the net floor area of the room 'Gang (Rum nr. K13)' on 'Kælder', in m²?") == ["Gang (Rum nr. K13)", "Kælder"]


def test_estonian_low_high_quotes():
    assert quoted("Kui suur on ruumi „ESIK (77-2)“ netopõrandapind korrusel „5.korrus“ (m²)?") == ["ESIK (77-2)", "5.korrus"]


def test_french_guillemets_with_spaces():
    assert quoted("Combien de pièces portant la désignation « Cage d'escalier » y a-t-il à cet étage ?") == ["Cage d'escalier"]


def test_apostrophe_inside_word_is_not_a_quote():
    assert quoted("How many rooms labelled 'Cage d'escalier' are there on this floor?") == ["Cage d'escalier"]


def test_no_quotes():
    assert quoted("How many windows are drawn on this floor plan?") == []
