"""Required field gaps: the org's rules (required fields, page layouts, validation rules, Apex triggers) and the records that break them."""
import pytest

from app.engine import required_rules
from app.engine.core import Unavailable
from app.engine.sf_formula import Formula, Unsupported


@pytest.mark.parametrize("formula, rec, broken", [
    ('AND(ISPICKVAL(StageName, "Closed Lost"), ISBLANK(Loss_Reason__c))', {"StageName": "Closed Lost", "Loss_Reason__c": None}, True),
    ('AND(ISPICKVAL(StageName, "Closed Lost"), ISBLANK(Loss_Reason__c))', {"StageName": "Closed Lost", "Loss_Reason__c": "Price"}, False),
    ("ISPICKVAL(StageName, 'Proposal') && Amount <= 0", {"StageName": "Proposal", "Amount": 0}, True),
    ("ISPICKVAL(StageName, 'Proposal') && Amount <= 0", {"StageName": "Proposal", "Amount": None}, False),  # blank isn't <= 0
    ("NOT(ISBLANK(Email)) && NOT(REGEX(Email, '[^@]+@[^@]+\\\\.[a-z]+'))", {"Email": "bad-email"}, True),
    ("LEN(Phone) < 10", {"Phone": "12345"}, True),
    ("CloseDate < DATE(2020, 1, 1)", {"CloseDate": "2019-05-01"}, True),
    ("$RecordType.DeveloperName = 'Partner' && ISBLANK(Account.Industry)", {"RecordType": {"DeveloperName": "Partner"}, "Account": {"Industry": None}}, True),
    ("ISNEW() && ISBLANK(Phone)", {"Phone": None}, False),  # an existing record saved again
    ("/* stage check */ CASE(TEXT(Type), 'New', 1, 0) = 1 && Amount > 1000", {"Type": "New", "Amount": 5000}, True),
])
def test_formula(formula, rec, broken):
    f = Formula(formula)
    assert f(rec) is broken


def test_formula_fields_and_unsupported():
    assert Formula("ISBLANK(Account.Industry) || $RecordType.Name = 'X'").fields == ["Account.Industry", "RecordType.Name"]
    with pytest.raises(Unsupported, match=r"\$User"):
        Formula("$User.ProfileId <> '00e' && ISBLANK(Phone)")
    with pytest.raises(Unsupported, match="VLOOKUP"):
        Formula("VLOOKUP(a, b, c) = 1")


LAYOUT = """<r xmlns="http://soap.sforce.com/2006/04/metadata"><records><fullName>Account-Sales Layout</fullName>
<layoutSections><layoutColumns><layoutItems><behavior>Required</behavior><field>Industry</field></layoutItems>
<layoutItems><behavior>Edit</behavior><field>Phone</field></layoutItems></layoutColumns></layoutSections></records>
<records><fullName>Account-Unused Layout</fullName><layoutSections><layoutColumns><layoutItems><behavior>Required</behavior>
<field>Type</field></layoutItems></layoutColumns></layoutSections></records></r>"""
RULES = """<r xmlns="http://soap.sforce.com/2006/04/metadata"><records><fullName>Account.Phone_Format</fullName>
<errorConditionFormula>NOT(ISBLANK(Phone)) &amp;&amp; LEN(Phone) &lt; 10</errorConditionFormula><errorDisplayField>Phone</errorDisplayField></records>
<records><fullName>Account.Owner_Check</fullName><errorConditionFormula>$User.Id = OwnerId</errorConditionFormula></records></r>"""
TRIGGER = "trigger AccountTrigger on Account (before insert, before update) { AccountHandler.check(Trigger.new); }"
HANDLER = "public class AccountHandler { public static void check(List<Account> rs) { for (Account a : rs) { if (String.isBlank(a.Website)) a.addError('Website please'); } } }"


class FakeSf:
    def read_metadata(self, kind, names):
        return LAYOUT if kind == "Layout" else RULES


class FakeCtx:
    sf = FakeSf()

    def __init__(self, rows):
        self._rows = rows
        self.soql = []

    def setup_url(self, path):
        return "https://acme.my.salesforce.com" + path

    def fields(self, obj):
        f = lambda n, **kw: {"name": n, "label": n, "nillable": True, "createable": True, "updateable": True, **kw}  # noqa: E731
        return {n: f(n) for n in ("Id", "Industry", "Phone", "Type", "Website", "OwnerId", "RecordTypeId")} | {"Name": f("Name", nillable=False)}

    def setup(self, soql, tooling=True):
        if "FROM Layout" in soql:
            return [{"Id": "00h000000000001AAA", "Name": "Sales Layout"}, {"Id": "00h000000000002AAA", "Name": "Unused Layout"}]
        if "FROM ProfileLayout" in soql:  # Sales Layout is used for the Partner record type only; Unused Layout by nobody
            return [{"LayoutId": "00h000000000001AAA", "ProfileId": "00e000000000001AAA", "RecordTypeId": "012000000000009AAA"},
                    {"LayoutId": "00h000000000001AAA", "ProfileId": "00e000000000002AAA", "RecordTypeId": "012000000000009AAA"},
                    {"LayoutId": "00h000000000003AAA", "ProfileId": "00e000000000003AAA", "RecordTypeId": None}]
        if "FROM Profile" in soql:
            return [{"Id": "00e000000000001AAA", "Name": "Sales User"}, {"Id": "00e000000000002AAA", "Name": "System Administrator"},
                    {"Id": "00e000000000003AAA", "Name": "Marketing User"}]
        if "FROM ValidationRule" in soql:
            return [{"ValidationName": "Phone_Format", "Active": True, "ErrorMessage": "Phone needs 10 digits"},
                    {"ValidationName": "Owner_Check", "Active": True, "ErrorMessage": "x"},
                    {"ValidationName": "Old_Rule", "Active": False, "ErrorMessage": "Please add a Type before saving"}]
        if "FROM ApexTrigger" in soql:
            return [{"Name": "AccountTrigger", "Status": "Active", "UsageBeforeInsert": True, "UsageBeforeUpdate": True, "Body": TRIGGER}]
        if "FROM ApexClass" in soql:
            assert "'AccountHandler'" in soql
            return [{"Name": "AccountHandler", "Body": HANDLER}]
        raise Unavailable("no")

    def rows(self, soql, limit=2000):
        if "FROM User" in soql:  # active users per profile: Sales 6, Admin 2, Marketing 0
            return [{"p": "00e000000000001AAA", "c": 6}, {"p": "00e000000000002AAA", "c": 2}]
        if "FROM RecordType" in soql:
            return [{"Id": "012000000000009AAA", "Name": "Partner"}]
        self.soql.append(soql)
        return self._rows


def test_check_object_against_every_kind_of_rule():
    rows = [
        {"Id": "001A", "Name": "Acme", "RecordTypeId": "012000000000009AAA", "Industry": None, "Phone": "123", "Website": "acme.com"},
        {"Id": "001B", "Name": "Globex", "RecordTypeId": None, "Industry": None, "Phone": "1234567890", "Website": None},
        {"Id": "001C", "Name": "Initech", "RecordTypeId": "012000000000009AAA", "Industry": "Tech", "Phone": None, "Website": "x.com"},
    ]
    ctx = FakeCtx(rows)
    c = required_rules.check_object(ctx, "Account")
    kinds = {(r.kind, r.name): r.fields for r in c.rules}
    assert kinds == {("field", "Standard required field Name"): ["Name"], ("layout", "Sales Layout"): ["Industry"],
                     ("validation", "Phone_Format"): ["Phone"], ("trigger", "AccountTrigger"): ["Website"]}
    assert c.skipped == ["Validation rule “Owner_Check”: depends on who saves the record ($User)"]
    assert c.checked == 3 and c.bad_ids == ["001A", "001B"]
    # A: Partner record type, so its layout requires Industry; Phone too short. B: no record type (layout doesn't apply), no Website
    assert c.notes == {
        "001A": {"Industry": "Empty, but required on page layout “Sales Layout”", "Phone": "Breaks validation rule “Phone_Format”: Phone needs 10 digits"},
        "001B": {"Website": "Empty, but Apex trigger “AccountTrigger” requires it (read from its code)"},
    }
    # the rules each record breaks (the frozen Broken rule column), and the red notes one kind of rule at a time (the rule filter)
    assert c.broken == {"001A": [("layout", "Industry: Page layout “Sales Layout”"), ("validation", "Phone: Validation rule “Phone_Format”")],
                        "001B": [("trigger", "Website: Apex trigger “AccountTrigger”")]}
    assert c.kind_notes["validation"] == {"001A": {"Phone": "Breaks validation rule “Phone_Format”: Phone needs 10 digits"}}
    assert set(c.kind_notes["layout"]) == {"001A"} and set(c.kind_notes["trigger"]) == {"001B"}
    assert "Industry" in ctx.soql[0] and "Website" in ctx.soql[0] and "RecordTypeId" in ctx.soql[0]


def test_rule_audit_lists_every_rule_with_its_message():
    c = required_rules.check_object(FakeCtx([]), "Account")
    rows = {(r["area"], r["name"]): r for r in c.audit}
    assert set(rows) == {("System Rule", "Name"), ("Page Layout", "Sales Layout"), ("Page Layout", "Unused Layout"),
                         ("Validation Rule", "Phone_Format"), ("Validation Rule", "Owner_Check"), ("Validation Rule", "Old_Rule"),
                         ("Trigger", "AccountTrigger")}
    # validation rules: their own message, judged; inactive ones listed as they are
    assert rows[("Validation Rule", "Owner_Check")]["issue"] == "Too short to explain the issue"  # “x”
    assert rows[("Validation Rule", "Phone_Format")]["issue"] is None  # “Phone needs 10 digits” says what to do
    old = rows[("Validation Rule", "Old_Rule")]
    assert not old["active"] and old["message"] == "Please add a Type before saving" and old["issue"] is None
    # page layouts and system rules: Salesforce's standard message (N/A); a layout assigned to nobody is inactive
    assert rows[("Page Layout", "Sales Layout")]["active"] and rows[("Page Layout", "Sales Layout")]["message"] is None
    assert not rows[("Page Layout", "Unused Layout")]["active"] and "not assigned" in rows[("Page Layout", "Unused Layout")]["description"]
    assert rows[("System Rule", "Name")]["assessed"] is False
    # triggers: the message written in the handler's code, judged
    trig = rows[("Trigger", "AccountTrigger")]
    assert trig["active"] and trig["message"] == "Website please" and trig["issue"] == "Too short to explain the issue"
    assert "Website is empty" in trig["description"] and "handler: AccountHandler" in trig["description"]


@pytest.mark.parametrize("message, issue", [
    ("", "Empty error message"), ("Error", "Only “Error”"), ("invalid.", "Only “invalid.”"), ("Please fix", "Generic: doesn’t say what to fix"),
    ("Bad value", "Too short to explain the issue"), ("Please enter a 10 digit phone number", None),
])
def test_message_issue(message, issue):
    assert required_rules.message_issue(message) == issue


def test_layout_rows_fields_profiles_and_usage():
    from app.engine.workflows import _layout_rows

    ctx = FakeCtx([])
    rows = _layout_rows(ctx, "Account", required_rules.collect(ctx, "Account"))
    assert [(r["name"], r["fields"], r["active"], r["profiles"], r["users"], r["usage"]) for r in rows] == [
        ("Sales Layout", 2, True, ["Sales User (Partner)", "System Administrator (Partner)"], 8, 100.0),  # all 8 active users
        ("Unused Layout", 1, False, [], 0, 0.0),  # assigned to nobody
    ]
    assert rows[0]["url"].endswith("/lightning/setup/ObjectManager/Account/PageLayouts/00h000000000001AAA/view")
