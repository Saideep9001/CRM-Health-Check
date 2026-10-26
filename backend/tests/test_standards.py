"""Data Standardization rules: what counts as an odd value, and why."""
from app.engine import standards as st


def items(*values):
    return [(f"id{i}", v) for i, v in enumerate(values)]


def test_phone_needs_ten_digits_and_a_country_code():
    assert st.phone("+1 408 555 0101") is None and st.phone("+91 98765 43210") is None and st.phone("0044 20 7946 0958") is None
    assert st.phone("(408) 555-01") == "too short — needs 10 digits plus a country code"  # the record that wasn't caught before
    assert st.phone("(408) 555-0101").startswith("no country code")
    assert st.phone("1 408 555 0101") == "country code without “+” in front"
    assert st.phone("+1 408 CALL NOW") == "has letters"
    assert st.phone("+1 111 111 1111") == "looks made up"
    assert st.phone("+1 408 555 0101 ext 12") is None  # an extension is fine


def test_email_format():
    assert st.email("ann.lee@acme.com") is None
    assert st.email("ann lee@acme.com") == "has spaces"
    assert st.email("ann@acme") == "not a valid email address" and st.email("ann..lee@acme.com") == "not a valid email address"
    assert st.email("none@test.com") == "a placeholder, not a real address"
    assert st.email("ann@gmial.com") == "misspelled domain — did you mean gmail.com?"
    assert st.email("karen@aqt.com") is None  # a short real domain, not a typo of aol.com


def test_states_countries_and_cities():
    odd = st.state(items("Telangana", "Telangana", "TS", "TG", "AP", "Andhra Pradesh", "Andhra Pradesh", "Telengana"))
    assert odd == {"id2": "written differently — usually “Telangana”", "id3": "written differently — usually “Telangana”",
                   "id4": "written differently — usually “Andhra Pradesh”", "id7": "misspelled? looks like Telangana"}
    odd = st.country(items("United States", "United States", "US", "USA", "London", "UK", "United Kingdom", "United Kingdom"))
    assert odd["id2"] == odd["id3"] == "written differently — usually “United States”"
    assert odd["id4"] == "a city, not a country — should be United Kingdom" and odd["id5"] == "written differently — usually “United Kingdom”"
    odd = st.city(items("Bangalore", "Houston,", "NEW YORK CITY", "san jose", "Austin 2", "Banglore", "San Francsico", "Madrid"))
    assert odd == {"id0": "older or short name — now “Bengaluru”", "id1": "stray punctuation", "id2": "all capitals",
                   "id3": "all lower case", "id4": "has numbers", "id5": "misspelled? looks like Bengaluru",
                   "id6": "misspelled? looks like San Francisco"}  # Madrid is a real city, not "Madras"


def test_company_names_flag_only_invalid_values():
    assert st.company_key("Pixel Tech Inc.") == st.company_key("PIXEL Technology, Incorporated")  # still used to match duplicates
    ok = ("Pixel Technology Inc", "Pixel Tech Inc.", "IBM", "Acme Co., Ltd.", "Hewlett-Packard",
          "Pacifica Inc", "Aquarient Technologies", "O’Reilly Media")
    assert st.company(items(*ok)) == {}  # short forms, short capitals (IBM) and another valid way of writing a name are fine
    odd = st.company(items("Acme Corp,", "  Globex  ", "Acme  LLC", "Acme #1 Holdings", "Acme_Ltd", "Test Account", "N/A", "12345",
                           "Pixel Technolgy Inc", "Acme,, Inc", "ACME HOLDINGS LTD", "account from script",
                           "Johnson & Johnson", "Yahoo!", "Smith (UK) Ltd"))
    assert odd == {"id0": "stray punctuation", "id1": "unwanted spaces (at the start, at the end or doubled)",
                   "id2": "unwanted spaces (at the start, at the end or doubled)", "id3": "unwanted symbol #", "id4": "unwanted symbol _",
                   "id5": "not a real name (a test or placeholder value)", "id6": "not a real name (a test or placeholder value)",
                   "id7": "not a real name (a test or placeholder value)", "id8": "misspelled? “Technolgy” should be “Technology”",
                   "id9": "stray punctuation", "id10": "all capitals", "id11": "all lower case",
                   "id12": "unwanted symbol &", "id13": "unwanted symbol !", "id14": "unwanted symbol ( )"}


def test_every_kind_has_a_rule_to_show():
    assert set(st.RULES) >= {"phone", "email", "country", "state", "city", "company", "text", "website", "postal", "amount", "date"}
