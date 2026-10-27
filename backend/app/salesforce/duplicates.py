"""Find duplicate records the way Salesforce's standard matching rules do — or on fields the person chooses.

Standard rules (Salesforce Help: "Standard Account Matching Rule", "Standard Contact Matching Rule and Standard
Lead Matching Rule"): a pair of records is a duplicate when any group of fields in the rule's equation all match.
Each field is compared with the method Salesforce documents (cleaned company names with fuzzy matching, names with
typo/nickname/initial tolerance and first/last swapped, phone/street/ZIP compared in weighted sections). Blank values
never match. Like Salesforce's match keys, only records that share a quick "key" are compared, which keeps this fast.

Read-only: records are only read, never changed.
"""
import re
from collections import Counter, defaultdict
from collections.abc import Callable

from . import explorer
from .client import SalesforceClient

MAX_SCAN = 20_000  # records read per run
MAX_GROUPS = 3_000  # groups returned (all of them, in practice)
MAX_BLOCK = 2_500  # records compared pairwise within one key

# ---------------------------------------------------------------- cleaning and similarity

_COMPANY_WORDS = re.compile(r"\b(the|incorporated|inc|llc|llp|ltd|limited|corp|corporation|co|company|plc|gmbh|ag|pvt|private|pty|sa|srl|bv|com|net|org|io)\b")
_NICKNAMES = {
    "bob": "robert", "rob": "robert", "bobby": "robert", "bill": "william", "will": "william", "billy": "william",
    "mike": "michael", "mick": "michael", "jim": "james", "jimmy": "james", "liz": "elizabeth", "beth": "elizabeth",
    "kate": "katherine", "kathy": "katherine", "katie": "katherine", "tom": "thomas", "tommy": "thomas", "dave": "david",
    "dan": "daniel", "danny": "daniel", "chris": "christopher", "matt": "matthew", "steve": "steven", "joe": "joseph",
    "tony": "anthony", "alex": "alexander", "sam": "samuel", "nick": "nicholas", "ben": "benjamin", "jen": "jennifer",
    "jenny": "jennifer", "andy": "andrew", "drew": "andrew", "rick": "richard", "dick": "richard", "rich": "richard",
    "ed": "edward", "ted": "edward", "pat": "patricia", "patty": "patricia", "sue": "susan", "peggy": "margaret",
    "maggie": "margaret", "meg": "margaret", "greg": "gregory", "jeff": "jeffrey", "larry": "lawrence", "ron": "ronald",
    "don": "donald", "ken": "kenneth", "tim": "timothy", "jon": "jonathan", "nate": "nathan", "becky": "rebecca",
    "vicky": "victoria", "abby": "abigail", "jess": "jessica", "josh": "joshua", "ray": "raymond", "fred": "frederick",
}
_STREET_SUFFIX = {
    "street": "st", "st": "st", "drive": "dr", "dr": "dr", "avenue": "ave", "ave": "ave", "av": "ave", "road": "rd", "rd": "rd",
    "boulevard": "blvd", "blvd": "blvd", "lane": "ln", "ln": "ln", "court": "ct", "ct": "ct", "way": "way", "place": "pl",
    "pl": "pl", "parkway": "pkwy", "pkwy": "pkwy", "highway": "hwy", "hwy": "hwy", "circle": "cir", "cir": "cir",
    "terrace": "ter", "ter": "ter", "square": "sq", "sq": "sq", "trail": "trl", "trl": "trl",
}


def _clean(v: object) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9@. ]", " ", str(v or "").lower())).strip()


def norm_company(v: object) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", str(v or "").lower().replace("&", " and "))
    return re.sub(r"\s+", " ", _COMPANY_WORDS.sub(" ", s)).strip()


def norm_website(v: object) -> str:
    s = str(v or "").strip().lower()
    s = re.sub(r"^[a-z]+://", "", s)
    s = re.sub(r"^www\d?\.", "", s)
    return re.split(r"[/?#:]", s, maxsplit=1)[0].strip(".")


def _digits(v: object) -> str:
    return re.sub(r"\D", "", str(v or ""))


def similarity(a: str, b: str) -> float:
    """1 - edit distance / longer length (Levenshtein)."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1 - prev[-1] / len(a)


def jaro_winkler(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    window = max(max(len(a), len(b)) // 2 - 1, 0)
    a_hit, b_hit = [False] * len(a), [False] * len(b)
    matches = 0
    for i, ca in enumerate(a):
        for j in range(max(0, i - window), min(len(b), i + window + 1)):
            if not b_hit[j] and b[j] == ca:
                a_hit[i] = b_hit[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    bs = [b[j] for j in range(len(b)) if b_hit[j]]
    transpositions = sum(ca != bs[k] for k, ca in enumerate(c for i, c in enumerate(a) if a_hit[i])) / 2
    jaro = (matches / len(a) + matches / len(b) + (matches - transpositions) / matches) / 3
    prefix = 0
    for ca, cb in zip(a[:4], b[:4]):
        if ca != cb:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


def soundex(word: str) -> str:
    """Sounds-alike code (Smith = Smyth = S530), standing in for Salesforce's Metaphone."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return ""
    codes = {**dict.fromkeys("bfpv", "1"), **dict.fromkeys("cgjkqsxz", "2"), **dict.fromkeys("dt", "3"), "l": "4", **dict.fromkeys("mn", "5"), "r": "6"}
    out, last = w[0].upper(), codes.get(w[0], "")
    for ch in w[1:]:
        code = codes.get(ch, "")
        if code and code != last:
            out += code
        if ch not in "hw":
            last = code
    return (out + "000")[:4]


def _acronym(a: str, b: str) -> bool:
    """“IBM” vs “International Business Machines”."""
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    words = long_.split()
    return len(short) >= 2 and " " not in short and len(words) >= 2 and "".join(w[0] for w in words) == short


# ---------------------------------------------------------------- field comparisons (Salesforce's documented methods)

def m_company(a, b) -> bool:  # Acronym, Edit Distance, Exact — threshold 70
    x, y = norm_company(a), norm_company(b)
    if not (x and y):
        return False
    if x == y or _acronym(x, y):
        return True
    if similarity(x, y) < 0.70:
        return False
    # Word by word: once the shared words are set aside, every remaining word must be a near-identical spelling of
    # one on the other side (a typo), so “Microsft” = “Microsoft” but “Resorts” ≠ “Restaurants”, “Group” ≠ “Partners”,
    # “Bayview Pediatrics” ≠ “Clearwater Pediatrics” and “Acme” ≠ “Acme Holdings”.
    only_x = [w for w in x.split() if w not in y.split()]
    only_y = [w for w in y.split() if w not in x.split()]
    if len(only_x) != len(only_y):
        return False
    left = list(only_y)
    for w in only_x:
        best = max(left, key=lambda v: similarity(w, v))
        if similarity(w, best) < 0.80:
            return False
        left.remove(best)
    return True


def m_first(a, b) -> bool:  # Exact, Initials, Jaro-Winkler, Name Variant — threshold 85
    x, y = _clean(a).replace(".", ""), _clean(b).replace(".", "")
    if not x or not y:
        return False
    if x == y or _NICKNAMES.get(x, x) == _NICKNAMES.get(y, y):
        return True
    if (len(x) == 1 or len(y) == 1) and x[0] == y[0]:
        return True
    return jaro_winkler(x, y) >= 0.85


def m_last(a, b) -> bool:  # Exact, Keyboard Distance, Metaphone — threshold 90
    x, y = _clean(a), _clean(b)
    return bool(x and y) and (x == y or jaro_winkler(x, y) >= 0.90 or (soundex(x) == soundex(y) and similarity(x, y) >= 0.6))


def m_email(a, b) -> bool:  # Exact
    x, y = str(a or "").strip().lower(), str(b or "").strip().lower()
    return bool(x and y) and x == y


def _phone_parts(v: object) -> tuple[str, str, str, str]:
    d = _digits(v)
    if len(d) == 11 and d.startswith("1"):
        return "1", d[1:4], d[4:7], d[7:]
    if len(d) == 10:
        return "", d[:3], d[3:6], d[6:]
    if len(d) > 10:
        return d[:-10], d[-10:-7], d[-7:-4], d[-4:]
    return "", "", d[:-4] if len(d) > 4 else "", d[-4:]


def m_phone(a, b) -> bool:  # sections: international 10%, area code 50%, next three 30%, last four 10% — threshold 80
    if len(_digits(a)) < 7 or len(_digits(b)) < 7:
        return False
    (i1, a1, n1, l1), (i2, a2, n2, l2) = _phone_parts(a), _phone_parts(b)
    score = 10 * (i1 == i2 or not i1 or not i2) + 50 * (a1 == a2 or not a1 or not a2) + 30 * (n1 == n2 and bool(n1)) + 10 * (l1 == l2 and bool(l1))
    return score >= 80


def _street_parts(v: object) -> tuple[str, str, str, str]:
    s = _clean(v).replace(".", "")
    suite = ""
    m = re.search(r"\b(suite|ste|apt|unit|#)\s*([a-z0-9-]+)", s)
    if m:
        suite, s = m.group(2), (s[: m.start()] + s[m.end():]).strip()
    words = s.split()
    number = words.pop(0) if words and re.match(r"^\d+[a-z]?$", words[0]) else ""
    suffix = _STREET_SUFFIX.get(words[-1], "") if words else ""
    if suffix:
        words = words[:-1]
    return number, " ".join(words), suffix, suite


def m_street(a, b) -> bool:  # number 20%, name 50% (edit distance), suffix 15%, suite 15% — threshold 80
    if not _clean(a) or not _clean(b):
        return False
    (n1, s1, x1, u1), (n2, s2, x2, u2) = _street_parts(a), _street_parts(b)
    score = 20 * (n1 == n2) + 50 * (similarity(s1, s2) >= 0.8) + 15 * (x1 == x2) + 15 * (u1 == u2)
    return score >= 80


def m_zip(a, b) -> bool:  # first five 90%, next four 10% — threshold 80
    x, y = re.sub(r"[^a-z0-9]", "", str(a or "").lower()), re.sub(r"[^a-z0-9]", "", str(b or "").lower())
    return bool(x and y) and x[:5] == y[:5]


def m_city(a, b) -> bool:  # Edit Distance, Exact — threshold 85
    x, y = _clean(a), _clean(b)
    return bool(x and y) and (x == y or similarity(x, y) >= 0.85)


def m_website(a, b) -> bool:  # Exact on the domain
    x, y = norm_website(a), norm_website(b)
    return bool(x and y) and x == y


def m_title(a, b) -> bool:  # Acronym, Exact, Kullback-Liebler — threshold 50
    x, y = _clean(a), _clean(b)
    return bool(x and y) and (x == y or _acronym(x, y) or similarity(x, y) >= 0.5)


def m_exact(a, b) -> bool:
    x, y = _clean(a), _clean(b)
    return bool(x and y) and x == y


KINDS: dict[str, tuple[str, Callable]] = {
    "company": ("Fuzzy company name: ignores Inc, Corp, LLC, .com…; differing words must be typos of each other (Microsft = Microsoft), or an acronym", m_company),
    "first": ("Fuzzy first name: typos, initials and nicknames (Bob = Robert)", m_first),
    "last": ("Fuzzy last name: small typos", m_last),
    "email": ("Exact email (any case)", m_email),
    "phone": ("Phone by parts: area code 50%, next 3 digits 30%, last 4 10%, country 10% — 80% needed", m_phone),
    "street": ("Street by parts: number 20%, name 50%, suffix (St/Ave…) 15%, suite 15% — 80% needed", m_street),
    "zip": ("ZIP: first five characters", m_zip),
    "city": ("City: 85% similar", m_city),
    "website": ("Website domain (ignores http, www and pages)", m_website),
    "title": ("Title: 50% similar or an acronym", m_title),
    "exact": ("Exact value (ignores case and punctuation)", m_exact),
}


def kind_of(name: str, field: dict | None) -> str:
    n = name.lower()
    t = (field or {}).get("type", "")
    if n in ("company", "account.name"):
        return "company"
    if n == "firstname":
        return "first"
    if n == "lastname":
        return "last"
    if n == "title":
        return "title"
    if t == "email":
        return "email"
    if t == "phone":
        return "phone"
    if t == "url" or n == "website":
        return "website"
    if n.endswith("street"):
        return "street"
    if n.endswith("city"):
        return "city"
    if n.endswith("postalcode"):
        return "zip"
    return "exact"


# ---------------------------------------------------------------- Salesforce's standard rules

def _contact_like(company: str, street: str, city: str, zip_: str) -> list[list[str]]:
    base = ["FirstName", "LastName"]
    return [
        base + ["Title", company],
        base + ["Email"],
        base + ["Phone", company],
        base + [street, city],
        base + [street, zip_],
        base + [street, "Phone"],
        base + [street, "Title"],
        base + ["Title", "Email"],
        base + ["Phone"],
    ]


STANDARD: dict[str, dict] = {
    "Account": {
        "name": "Standard Account Matching Rule",
        "groups": [["Name", "BillingStreet"], ["Name", "BillingCity", "BillingState"], ["Name", "BillingPostalCode"],
                   ["Name", "Phone"], ["Website", "Phone"], ["Website", "BillingStreet"]],
        "kinds": {"Name": "company"},
    },
    "Contact": {"name": "Standard Contact Matching Rule", "groups": _contact_like("Account.Name", "MailingStreet", "MailingCity", "MailingPostalCode"),
                "kinds": {"Account.Name": "company"}},
    "Lead": {"name": "Standard Lead Matching Rule", "groups": _contact_like("Company", "Street", "City", "PostalCode"), "kinds": {"Company": "company"}},
}


# Shown alongside the matched fields so people can tell real duplicates apart (skipped if the object lacks them).
CONTEXT = {
    "Account": ["Website", "Phone", "BillingCity", "Owner.Name", "CreatedDate"],
    "Contact": ["Email", "Phone", "Account.Name", "Owner.Name", "CreatedDate"],
    "Lead": ["Email", "Company", "Phone", "Status", "Owner.Name", "CreatedDate"],
}
DEFAULT_CONTEXT = ["Owner.Name", "CreatedDate"]


# ---------------------------------------------------------------- reading records

def _value(rec: dict, path: str):
    cur = rec
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def matchable_fields(sf: SalesforceClient, obj: str) -> list[dict]:
    """Fields a person can choose to find duplicates on, with how each is compared."""
    desc = explorer._describe(sf, obj)
    fields = explorer._fields(desc)
    out = []
    if obj == "Contact" and "AccountId" in fields:
        out.append({"name": "Account.Name", "label": "Account Name", "kind": "company"})
    for f in desc.get("fields", []):
        street = f.get("type") == "textarea" and f["name"].endswith("Street")  # address streets are long text
        if (f.get("type") not in ("string", "email", "phone", "url", "picklist", "combobox") and not street) or not f.get("filterable", True):
            continue
        name = f["name"]
        kind = STANDARD.get(obj, {}).get("kinds", {}).get(name) or ("company" if f.get("nameField") and obj in ("Account",) else kind_of(name, f))
        out.append({"name": name, "label": f.get("label") or name, "kind": kind})
    return out


def _fetch(sf: SalesforceClient, obj: str, paths: list[str]) -> tuple[list[dict], bool]:
    soql = f"SELECT Id, {', '.join(dict.fromkeys(paths))} FROM {obj}"
    body = sf.query(soql, max_rows=MAX_SCAN + 1)  # one more than we read, to know when there are more (Bulk API)
    rows = list(body.get("records", []))
    while not body.get("done", True) and body.get("nextRecordsUrl") and len(rows) < MAX_SCAN:
        body = sf.get(body["nextRecordsUrl"])
        rows += body.get("records", [])
    more = len(rows) > MAX_SCAN or (bool(body.get("nextRecordsUrl")) and not body.get("done", True))
    return rows[:MAX_SCAN], more


# ---------------------------------------------------------------- matching

def _key(kind: str, v) -> str:
    """Quick key so only likely duplicates are compared (like Salesforce match keys)."""
    if kind == "company":
        return norm_company(v).replace(" ", "")[:6]
    if kind == "first":
        return _clean(v)[:1]
    if kind == "last":
        return soundex(_clean(v))  # sounds-alike, like Salesforce's metaphone keys
    if kind == "email":
        return str(v or "").strip().lower()
    if kind == "phone":
        d = _digits(v)
        return d[-10:-4] if len(d) >= 10 else d[-7:-4] if len(d) >= 7 else ""
    if kind == "website":
        return norm_website(v)
    if kind == "street":
        return _street_parts(v)[0]  # street number (must match exactly for 80%)
    if kind in ("city", "title"):
        return _clean(v)[:4]
    if kind == "zip":
        return re.sub(r"[^a-z0-9]", "", str(v or "").lower())[:5]
    return _clean(v)


class _Groups:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        self.parent[self.find(a)] = self.find(b)


def find_duplicates(sf: SalesforceClient, obj: str, fields: list[str] | None = None, standard: bool = False,
                    prefetched: tuple[list[dict], bool] | None = None) -> dict:
    """Groups of duplicate records. `standard` uses Salesforce's standard rule for Account/Contact/Lead; otherwise
    records match when every field in `fields` matches. `prefetched` reuses records already read (with these fields)."""
    available = {f["name"]: f for f in matchable_fields(sf, obj)}
    if standard:
        if obj not in STANDARD:
            raise ValueError("Salesforce has a standard matching rule only for Accounts, Contacts and Leads. Choose fields instead.")
        groups = [[f for f in g if f in available] for g in STANDARD[obj]["groups"]]
        groups = [g for g, orig in zip(groups, STANDARD[obj]["groups"]) if len(g) == len(orig)]  # skip groups using missing fields
        if not groups:
            raise ValueError("This org doesn't have the fields the standard rule needs.")
    else:
        chosen = [f for f in dict.fromkeys(fields or []) if f in available]
        if not chosen:
            raise ValueError("Choose at least one field to compare.")
        if len(chosen) > 6:
            raise ValueError("Choose up to 6 fields.")
        groups = [chosen]

    paths = sorted({f for g in groups for f in g})
    name_field = next((f["name"] for f in explorer._describe(sf, obj).get("fields", []) if f.get("nameField")), None)
    described = explorer._fields(explorer._describe(sf, obj))
    has = lambda f: f in described or (f == "Owner.Name" and "OwnerId" in described) or (f == "Account.Name" and "AccountId" in described)  # noqa: E731
    context = [f for f in CONTEXT.get(obj, DEFAULT_CONTEXT) if has(f)]
    show = list(dict.fromkeys(([name_field] if name_field else []) + paths + context))
    rows, truncated = prefetched or _fetch(sf, obj, show)
    values = [{p: _value(r, p) for p in show} for r in rows]
    kinds = {p: available[p]["kind"] for p in paths}

    def fields_match(a: dict, b: dict, group: list[str]) -> bool:
        has_email = "Email" in group
        if "FirstName" in group and "LastName" in group:
            straight = (m_first(a["FirstName"], b["FirstName"]) or (has_email and not (a["FirstName"] and b["FirstName"]))) and \
                       (m_last(a["LastName"], b["LastName"]) or (has_email and not (a["LastName"] and b["LastName"])))
            swapped = m_first(a["FirstName"], b["LastName"]) and m_last(a["LastName"], b["FirstName"])
            if not (straight or swapped):
                return False
            rest = [f for f in group if f not in ("FirstName", "LastName")]
        else:
            rest = group
        return all(KINDS[kinds[f]][1](a[f], b[f]) for f in rest)

    # Which fields make up a group's match key: exact-ish fields first (email, website, phone, ZIP), plus the company
    # name; people are keyed by first initial + how the surname sounds (and the other way round, for swapped names).
    KEYED = ("email", "website", "phone", "zip", "company", "city", "street", "exact")

    def keys_for(v: dict, group: list[str]) -> list[str]:
        names = "FirstName" in group and "LastName" in group
        if names and "Email" in group:
            k = _key("email", v.get("Email"))
            return [k] if k else []
        extra = [f for f in group if f not in ("FirstName", "LastName") and kinds[f] in ("email", "website", "phone", "zip")][:1]
        tail = "|".join(_key(kinds[f], v.get(f)) for f in extra)
        if extra and not tail.strip("|"):
            return []
        if names:
            first, last = _clean(v.get("FirstName")), _clean(v.get("LastName"))
            if not first or not last:
                return []
            out = {f"{first[0]}{soundex(last)}|{tail}", f"{last[0]}{soundex(first)}|{tail}"}  # swapped names meet too
            return list(out)
        fields_ = [f for f in group if kinds[f] in KEYED][:3] or group[:1]
        parts = [_key(kinds[f], v.get(f)) for f in fields_]
        return ["|".join(parts)] if all(parts) else []

    uf = _Groups(len(values))
    members_of: dict[int, list[int]] = {i: [i] for i in range(len(values))}  # group's first record -> its records
    reasons: dict[tuple[int, int], int] = {}
    for gi, group in enumerate(groups):
        blocks: dict[str, list[int]] = defaultdict(list)
        for i, v in enumerate(values):
            for k in keys_for(v, group):
                blocks[k].append(i)
        for members in blocks.values():
            members = list(dict.fromkeys(members))[:MAX_BLOCK]
            for x in range(len(members)):
                for y in range(x + 1, len(members)):
                    i, j = members[x], members[y]
                    ri, rj = uf.find(i), uf.find(j)
                    if ri == rj or not fields_match(values[i], values[j], group):
                        continue
                    # No chaining (A~B and B~C isn't enough): every record in a group must match the group's first record.
                    if not (all(fields_match(values[ri], values[m], group) for m in members_of[rj])
                            and all(fields_match(values[rj], values[m], group) for m in members_of[ri])):
                        continue
                    merged = members_of.pop(ri) + members_of.pop(rj)
                    uf.union(i, j)
                    members_of[uf.find(i)] = merged
                    reasons[(i, j)] = gi
    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(values)):
        clusters[uf.find(i)].append(i)
    found = sorted((c for c in clusters.values() if len(c) > 1), key=len, reverse=True)
    pair_reason = defaultdict(Counter)
    for (i, j), gi in reasons.items():
        pair_reason[uf.find(i)][gi] += 1

    def label(f: str) -> str:
        if f in available:
            return available[f]["label"]
        return {"Owner.Name": "Owner", "Account.Name": "Account Name"}.get(f) or described.get(f, {}).get("label") or f

    out_groups = []
    for c in found[:MAX_GROUPS]:
        gi = pair_reason[uf.find(c[0])].most_common(1)[0][0] if pair_reason[uf.find(c[0])] else 0
        out_groups.append({
            "size": len(c),
            "matched_on": " + ".join(label(f) for f in groups[gi]),
            "records": [{"id": rows[i].get("Id"), "values": {p: values[i][p] for p in show}} for i in c[:50]],
        })
    return {
        "object": obj,
        "standard": standard,
        "rule_name": STANDARD[obj]["name"] if standard else None,
        "rules": [[label(f) for f in g] for g in groups],
        "methods": [{"field": label(p), "method": KINDS[kinds[p]][0]} for p in paths],
        "columns": [{"name": p, "label": label(p)} for p in show],
        "scanned": len(rows),
        "truncated": truncated,
        "total_groups": len(found),
        "extra_copies": sum(len(c) - 1 for c in found),
        "groups": out_groups,
        "record_url_prefix": f"{sf.base}/",
    }
