"""What counts as an odd value in Data Standardization, field by field, with a short reason people can act on.

Phone numbers must be 10 digits with a country code ("+1 408 555 0101"); emails must be a valid address; states,
countries, cities and company names are compared after mapping the usual short forms and other names to one place or
word ("TS" = "TG" = Telangana, "US" = "USA" = United States, "Bangalore" = Bengaluru, "Tech" = "Technology"), and the
way most of your records write it counts as right.
"""
import re
from collections import Counter, defaultdict
from datetime import date, timedelta

# ---------------------------------------------------------------- places

COUNTRIES: dict[str, tuple[str, ...]] = {
    "United States": ("us", "usa", "u s", "u s a", "united states", "united states of america", "america", "the united states"),
    "United Kingdom": ("uk", "u k", "gb", "gbr", "great britain", "britain", "england", "scotland", "wales", "northern ireland", "united kingdom"),
    "India": ("in", "ind", "india", "bharat", "republic of india"),
    "Canada": ("ca", "can", "canada"),
    "Australia": ("au", "aus", "australia"),
    "Germany": ("de", "deu", "germany", "deutschland"),
    "France": ("fr", "fra", "france"),
    "United Arab Emirates": ("ae", "uae", "u a e", "emirates", "united arab emirates"),
    "Singapore": ("sg", "sgp", "singapore"),
    "Mexico": ("mx", "mex", "mexico"),
    "Brazil": ("br", "bra", "brazil", "brasil"),
    "Japan": ("jp", "jpn", "japan"),
    "China": ("cn", "chn", "china", "prc"),
    "Netherlands": ("nl", "nld", "netherlands", "the netherlands", "holland"),
    "Spain": ("es", "esp", "spain", "espana"),
    "Italy": ("it", "ita", "italy", "italia"),
    "Ireland": ("ie", "irl", "ireland"),
    "New Zealand": ("nz", "nzl", "new zealand"),
    "South Africa": ("za", "zaf", "rsa", "south africa"),
    "Switzerland": ("ch", "che", "switzerland"),
    "Sweden": ("se", "swe", "sweden"),
    "Saudi Arabia": ("ksa", "sau", "saudi", "saudi arabia"),
}
# Cities people type into a country field.
CITY_COUNTRY = {
    "london": "United Kingdom", "manchester": "United Kingdom", "new york": "United States", "san francisco": "United States",
    "delhi": "India", "new delhi": "India", "mumbai": "India", "bangalore": "India", "bengaluru": "India", "hyderabad": "India",
    "chennai": "India", "dubai": "United Arab Emirates", "abu dhabi": "United Arab Emirates", "toronto": "Canada",
    "sydney": "Australia", "melbourne": "Australia", "paris": "France", "berlin": "Germany", "tokyo": "Japan",
}
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}
# Indian states and union territories. Codes that clash with a US state (e.g. TN, GA, OR) aren't used as codes here.
INDIA_STATES: dict[str, tuple[str, ...]] = {
    "Telangana": ("ts", "tg", "telangana"), "Andhra Pradesh": ("ap", "andhra", "andhra pradesh"), "Karnataka": ("ka", "karnataka"),
    "Tamil Nadu": ("tamilnadu", "tamil nadu"), "Kerala": ("kl", "kerala"), "Maharashtra": ("mh", "maharashtra"),
    "Gujarat": ("gj", "gujarat"), "Rajasthan": ("rj", "rajasthan"), "Uttar Pradesh": ("up", "uttar pradesh"),
    "Madhya Pradesh": ("mp", "madhya pradesh"), "West Bengal": ("wb", "west bengal"), "Bihar": ("br", "bihar"),
    "Odisha": ("od", "orissa", "odisha"), "Punjab": ("pb", "punjab"), "Haryana": ("hr", "haryana"), "Delhi": ("dl", "nct", "new delhi", "delhi"),
    "Jharkhand": ("jh", "jharkhand"), "Chhattisgarh": ("cg", "ct", "chhattisgarh"), "Uttarakhand": ("uttaranchal", "uttarakhand"),
    "Himachal Pradesh": ("hp", "himachal", "himachal pradesh"), "Jammu and Kashmir": ("jk", "j k", "jammu kashmir", "jammu and kashmir"),
    "Goa": ("goa",), "Assam": ("assam",), "Puducherry": ("py", "pondicherry", "puducherry"), "Chandigarh": ("ch", "chandigarh"),
}
CANADA = {"ON": "Ontario", "QC": "Quebec", "BC": "British Columbia", "AB": "Alberta", "MB": "Manitoba", "SK": "Saskatchewan",
          "NS": "Nova Scotia", "NB": "New Brunswick", "PE": "Prince Edward Island", "YT": "Yukon"}
AUSTRALIA = {"NSW": "New South Wales", "VIC": "Victoria", "QLD": "Queensland", "TAS": "Tasmania", "ACT": "Australian Capital Territory"}
CITIES: dict[str, tuple[str, ...]] = {  # current name ← older names and short forms
    "Bengaluru": ("bangalore", "bengaluru", "blr"), "Mumbai": ("bombay", "mumbai"), "Chennai": ("madras", "chennai"),
    "Kolkata": ("calcutta", "kolkata"), "Gurugram": ("gurgaon", "gurugram"), "Pune": ("poona", "pune"), "Mysuru": ("mysore", "mysuru"),
    "Hyderabad": ("hyd", "hyderabad"), "New Delhi": ("new delhi", "ndls"), "New York": ("nyc", "new york city", "new york"),
    "San Francisco": ("sf", "san fran", "san francisco"), "Los Angeles": ("los angeles", "l a"), "Washington": ("washington dc", "washington d c", "washington"),
    "Saint Louis": ("st louis", "saint louis"), "Saint Paul": ("st paul", "saint paul"), "Fort Worth": ("ft worth", "fort worth"),
}


def _plain(v: object) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(v).lower())).strip()


def _aliases(groups: dict[str, tuple[str, ...]]) -> dict[str, str]:
    return {a: name for name, names in groups.items() for a in names} | {_plain(name): name for name in groups}


COUNTRY_OF = _aliases(COUNTRIES)
STATE_OF = (
    {code.lower(): name for code, name in US_STATES.items()} | {_plain(n): n for n in US_STATES.values()}
    | _aliases(INDIA_STATES)
    | {code.lower(): name for code, name in CANADA.items()} | {_plain(n): n for n in CANADA.values()}
    | {code.lower(): name for code, name in AUSTRALIA.items()} | {_plain(n): n for n in AUSTRALIA.values()}
)
CITY_OF = _aliases(CITIES)

# ---------------------------------------------------------------- company names

ABBREVIATIONS = {  # short form → the word it stands for
    "tech": "technology", "techn": "technology", "technologies": "technology", "inc": "incorporated", "corp": "corporation",
    "co": "company", "cos": "companies", "ltd": "limited", "intl": "international", "int l": "international", "svc": "services",
    "svcs": "services", "srvcs": "services", "mfg": "manufacturing", "mfr": "manufacturing", "assoc": "associates",
    "assn": "association", "bros": "brothers", "grp": "group", "sys": "systems", "sol": "solutions", "soln": "solutions",
    "solns": "solutions", "mgmt": "management", "univ": "university", "hosp": "hospital", "natl": "national", "ctr": "center",
    "cntr": "center", "centre": "center", "pvt": "private", "dept": "department", "eng": "engineering", "engg": "engineering",
    "govt": "government", "hldgs": "holdings", "ind": "industries", "inds": "industries", "indus": "industries", "and": "and",
}


def company_key(v: object) -> str:
    """A company name in a form where the same name written differently compares equal ("Acme Tech Inc." = "ACME Technology, Incorporated")."""
    words = _plain(str(v).replace("&", " and ")).split()
    return " ".join(ABBREVIATIONS.get(w, w) for w in words)


# ---------------------------------------------------------------- helpers

def _edits(a: str, b: str) -> int:
    """Letters added, removed, changed or swapped with the next one ("Francsico" is one away from "Francisco")."""
    d = [[i + j if i * j == 0 else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def _written_differently(items: list[tuple[str, str]], key) -> dict[str, str]:
    """Values that mean the same as others but are written differently from the way most records write them."""
    buckets: dict[str, Counter] = defaultdict(Counter)
    for _, v in items:
        if k := key(v):
            buckets[k][v.strip()] += 1
    usual = {k: c.most_common(1)[0][0] for k, c in buckets.items() if len(c) > 1}
    return {i: f"written differently — usually “{usual[k]}”" for i, v in items if (k := key(v)) in usual and v.strip() != usual[k]}


def _layout(v: str, *, caps: bool = True) -> str | None:
    """Spacing and capitals: extra spaces, ALL CAPITALS, all lower case."""
    if v != " ".join(v.split()):
        return "extra spaces"
    letters = re.sub(r"[^A-Za-z]", "", v)
    if caps and len(letters) > 4 and letters.isupper() and " " in v.strip():
        return "all capitals"
    if len(letters) > 3 and letters.islower():
        return "all lower case"
    return None


def _close_to(value: str, names: list[str], most: int = 2) -> str | None:
    """The known name `value` is probably a misspelling of (at most `most` letters away), if any."""
    p = _plain(value)
    if len(p) < 5:
        return None
    best = min(names, key=lambda n: _edits(p, _plain(n)))
    return best if 0 < _edits(p, _plain(best)) <= most else None


# ---------------------------------------------------------------- rules

_EMAIL = re.compile(r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*@([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$", re.I)
# Typos are only guessed for longer provider names: short domains (aqt.com, aon.com) are too close to tell apart.
_PROVIDERS = ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "rediffmail.com")
_PLACEHOLDER = re.compile(r"(@(example|test|email|domain|mail)\.(com|org|net)$)|^(none|noemail|no-?reply|test|na|n/a|xxx+)@", re.I)


def phone(v: str) -> str | None:
    s = v.strip()
    main = re.split(r"\s*(?:ext\.?|extension|x)\s*\d+$", s, flags=re.I)[0]
    if re.search(r"[A-Za-z]", main):
        return "has letters"
    digits = re.sub(r"\D", "", main)
    if s.startswith("00"):  # "00" is another way to write "+": not part of the number
        digits = digits[2:]
    if len(digits) < 10:
        return "too short — needs 10 digits plus a country code"
    if len(digits) > 15:
        return "too long"
    if len(set(digits[-10:])) == 1 or digits[-10:] in ("1234567890", "0123456789"):
        return "looks made up"
    if not s.startswith(("+", "00")):
        return "no country code (write it like +1 408 555 0101)" if len(digits) == 10 else "country code without “+” in front"
    if len(digits) not in (11, 12, 13):
        return "not a country code plus 10 digits"
    return None


def email(v: str) -> str | None:
    s = v.strip()
    if s != v or " " in s:
        return "has spaces"
    if not _EMAIL.match(s) or ".." in s:
        return "not a valid email address"
    if _PLACEHOLDER.search(s):
        return "a placeholder, not a real address"
    domain = s.rsplit("@", 1)[-1].lower()
    near = next((p for p in _PROVIDERS if 0 < _edits(domain, p) <= 2), None)
    return f"misspelled domain — did you mean {near}?" if near else None


def _places(items: list[tuple[str, str]], lookup: dict[str, str], names: list[str], extra=None) -> dict[str, str]:
    out: dict[str, str] = {}
    for i, v in items:
        if extra and (r := extra(v)):
            out[i] = r
        elif _plain(v) not in lookup and (near := _close_to(v, names)):
            out[i] = f"misspelled? looks like {near}"
        elif (r := _layout(v.strip(), caps=False)) and r == "all lower case":
            out[i] = r
    known = [(i, v) for i, v in items if i not in out and _plain(v) in lookup]
    out |= _written_differently(known, lambda v: lookup.get(_plain(v), ""))
    return out


def country(items: list[tuple[str, str]]) -> dict[str, str]:
    def city(v: str) -> str | None:
        c = CITY_COUNTRY.get(_plain(v))
        return f"a city, not a country — should be {c}" if c else None
    return _places(items, COUNTRY_OF, list(COUNTRIES), city)


def state(items: list[tuple[str, str]]) -> dict[str, str]:
    return _places(items, STATE_OF, sorted(set(STATE_OF.values())))


def city(items: list[tuple[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i, v in items:
        if re.search(r"\d", v):
            out[i] = "has numbers"
        elif re.search(r"^[^A-Za-z]|[,.;:/\\-]\s*$", v.strip()):
            out[i] = "stray punctuation"
        elif r := _layout(v):
            out[i] = r
        elif (alias := CITY_OF.get(_plain(v))) and _plain(alias) != _plain(v):
            out[i] = f"older or short name — now “{alias}”"
        elif _plain(v) not in CITY_OF and (near := _close_to(v, list(CITY_OF), most=1)):  # 1 letter: "Madrid" isn't "Madras"
            out[i] = f"misspelled? looks like {CITY_OF[near]}"
    rest = [(i, v) for i, v in items if i not in out]
    return out | _written_differently(rest, lambda v: _plain(CITY_OF.get(_plain(v), v)))


def company(items: list[tuple[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i, v in items:
        if re.search(r"[,;:/\\-]\s*$", v.strip()):
            out[i] = "stray punctuation at the end"
        elif r := _layout(v):
            out[i] = r
    rest = [(i, v) for i, v in items if i not in out]
    return out | _written_differently(rest, company_key)


def text(items: list[tuple[str, str]]) -> dict[str, str]:
    out = {i: r for i, v in items if (r := _layout(v))}
    rest = [(i, v) for i, v in items if i not in out]
    return out | _written_differently(rest, _plain)


def _usual_shape(items: list[tuple[str, str]], shape, what: str) -> dict[str, str]:
    counts = Counter(shape(v) for _, v in items)
    if len(counts) < 2:
        return {}
    usual = counts.most_common(1)[0][0]
    return {i: f"{what} — most are written like “{usual}”" for i, v in items if shape(v) != usual}


def website(items: list[tuple[str, str]]) -> dict[str, str]:
    out = {i: "not a valid web address" for i, v in items if " " in v.strip() or "@" in v or "." not in v}
    rest = [(i, v) for i, v in items if i not in out]

    def form(v: str) -> str:
        s = v.strip().lower()
        return ("https://" if re.match(r"^[a-z]+://", s) else "") + ("www." if "www." in s else "") + "example.com"
    return out | _usual_shape(rest, form, "different form")


def postal(items: list[tuple[str, str]]) -> dict[str, str]:
    out = {i: "invalid characters" for i, v in items if re.search(r"[^A-Za-z0-9 \-]", v.strip())}
    rest = [(i, v) for i, v in items if i not in out]
    return out | _usual_shape(rest, lambda v: re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", v.strip())), "different format")


def odd_values(kind: str, items: list[tuple[str, object]], open_ids: set[str]) -> dict[str, str]:
    """Record id → why its value is odd, for one field's values."""
    if kind == "amount":
        return {i: "zero or negative" for i, v in items if isinstance(v, (int, float)) and v <= 0}
    text_items = [(i, str(v)) for i, v in items]
    if kind == "date":
        today, out = date.today(), {}
        for i, v in text_items:
            try:
                d = date.fromisoformat(v[:10])
            except ValueError:
                out[i] = "not a date"
                continue
            if d.year < 2000:
                out[i] = "before 2000"
            elif d > today + timedelta(days=5 * 365):
                out[i] = "more than 5 years ahead"
            elif i in open_ids and d < today:
                out[i] = "open deal whose close date has passed"
        return out
    if kind == "phone":
        return {i: r for i, v in text_items if (r := phone(v))}
    if kind == "email":
        return {i: r for i, v in text_items if (r := email(v))}
    rules = {"country": country, "state": state, "city": city, "company": company, "website": website, "postal": postal}
    return rules.get(kind, text)(text_items)


RULES = {  # shown in "How it's flagged"
    "phone": "must be 10 digits with a country code, e.g. +1 408 555 0101 (too short, no country code, letters or made-up numbers are odd)",
    "email": "must be a valid address (no spaces, one @, a real domain); placeholders like none@test.com and misspelled domains like gmial.com are odd",
    "country": "the same country written different ways (US / USA / America = United States; UK / GB / England = United Kingdom); a city typed in "
               "(London) or a misspelling is odd; the way most records write it counts as right",
    "state": "the same state written different ways (TS / TG = Telangana, AP = Andhra Pradesh, CA = California); misspellings and all lower case "
             "are odd; the way most records write it counts as right",
    "city": "older or short names (Bangalore → Bengaluru, Bombay → Mumbai, NYC → New York), numbers, stray punctuation, extra spaces, "
            "ALL CAPITALS or all lower case, or the same city written differently",
    "company": "the same name written differently once short forms are read in full (Tech = Technology, Inc = Incorporated, Corp, Ltd, Co, "
               "Intl, Mfg, Svcs…), stray punctuation, extra spaces, ALL CAPITALS or all lower case",
    "text": "extra spaces, ALL CAPITALS or all lower case, or the same value written different ways (the way most records write it counts as right)",
    "website": "not a valid web address, or written in a different form from the one most used (with or without https:// and www.)",
    "postal": "invalid characters, or a different format from the one most used (for example 5 digits vs 5+4)",
    "amount": "zero or negative",
    "date": "an open deal whose close date has passed, a date before 2000 or more than 5 years ahead",
}
