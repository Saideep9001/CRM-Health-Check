"""Relevant (fuzzy) company-name matching: abbreviations, legal suffixes and generic business words."""
import pytest

from app.salesforce.duplicates import m_company


@pytest.mark.parametrize("a, b", [
    ("Aquarient Technologies", "Aquarient Tech"),
    ("Aquarient Tech", "aquarient ltd"),
    ("Aquarient Technologies", "Aquarient Ltd"),
    ("Aquarient", "Aquarient Holdings"),
    ("Acme Intl", "Acme International Inc"),
    ("Microsft", "Microsoft"),
    ("IBM", "International Business Machines"),
])
def test_same_company(a, b):
    assert m_company(a, b)


@pytest.mark.parametrize("a, b", [
    ("Bay Pediatrics", "Bayview Pediatrics"),
    ("Bayview Pediatrics", "Clearwater Pediatrics"),
    ("Resorts", "Restaurants"),
    ("Global Partners", "Global"),  # the shared part is itself a generic word
    ("Acme Group", "Acme Partners"),
])
def test_different_companies(a, b):
    assert not m_company(a, b)
