"""Lead Assignment Rule entries: read from the Metadata API's answer, and checked against a Lead the way Salesforce does."""
from app.salesforce import assignment
from app.salesforce.assignment import Entry, Item

TYPES = {"LeadSource": "picklist", "Country": "string", "AnnualRevenue": "currency", "Industry": "picklist", "HasOptedOutOfEmail": "boolean"}


def test_reads_only_the_active_rule_and_marks_what_cant_be_checked():
    xml = """<r xmlns="http://soap.sforce.com/2006/04/metadata">
      <assignmentRule><fullName>Off</fullName><active>false</active></assignmentRule>
      <assignmentRule><fullName>Main</fullName><active>true</active>
        <ruleEntry><assignedTo>Q1</assignedTo><assignedToType>Queue</assignedToType><booleanFilter>1 OR 2</booleanFilter>
          <criteriaItems><field>Lead.Country</field><operation>equals</operation><value>US,USA</value></criteriaItems>
          <criteriaItems><field>Lead.AnnualRevenue</field><operation>greaterThan</operation><value>1000000</value></criteriaItems></ruleEntry>
        <ruleEntry><assignedTo>a@b.c</assignedTo><assignedToType>User</assignedToType><formula>ISPICKVAL(Status, 'New')</formula></ruleEntry>
        <ruleEntry><assignedTo>a@b.c</assignedTo><assignedToType>User</assignedToType>
          <criteriaItems><field>Lead.Owner.UserRoleId</field><operation>equals</operation><value>x</value></criteriaItems></ruleEntry>
      </assignmentRule></r>"""
    rule = assignment.active_rule(xml)
    assert rule.name == "Main" and [e.checkable for e in rule.entries] == [True, False, False]
    assert rule.entries[0].logic == "1 OR 2" and rule.entries[0].items[0].field == "Country"
    assert assignment.fields_used(rule) == ["AnnualRevenue", "Country"]


def test_matching_like_salesforce():
    any_of = Entry(1, "Q", "Queue", [Item("LeadSource", "equals", "Web, Phone")])
    assert assignment.matches(any_of, {"LeadSource": "web"}, TYPES) is True  # values are alternatives, case doesn't matter
    assert assignment.matches(any_of, {"LeadSource": "Event"}, TYPES) is False
    both = Entry(2, "Q", "Queue", [Item("Country", "startsWith", "U"), Item("AnnualRevenue", "greaterOrEqual", "500")])
    assert assignment.matches(both, {"Country": "UK", "AnnualRevenue": 900}, TYPES) is True
    assert assignment.matches(both, {"Country": "UK", "AnnualRevenue": None}, TYPES) is False
    logic = Entry(3, "Q", "Queue", [Item("Country", "equals", "US"), Item("Industry", "equals", "Tech"), Item("HasOptedOutOfEmail", "equals", "False")],
                  "1 AND (2 OR NOT 3)")
    assert assignment.matches(logic, {"Country": "US", "Industry": "Retail", "HasOptedOutOfEmail": True}, TYPES) is True
    assert assignment.matches(logic, {"Country": "FR", "Industry": "Tech", "HasOptedOutOfEmail": False}, TYPES) is False
    assert assignment.matches(Entry(4, "Q", "Queue"), {}, TYPES) is True  # no criteria: catches everything
    dated = Entry(5, "Q", "Queue", [Item("CreatedDate", "greaterThan", "1/1/2024")])
    assert assignment.matches(dated, {"CreatedDate": "2025-01-01"}, {"CreatedDate": "datetime"}) is None  # not guessed
    bad_logic = Entry(6, "Q", "Queue", [Item("Country", "equals", "US")], "1 AND __import__('os')")
    assert assignment.matches(bad_logic, {"Country": "US"}, TYPES) is None


def test_gap_reason_column():
    cols = [{"name": "Name", "label": "Name", "type": "string"}, {"name": "OwnerId", "label": "Owner ID", "type": "reference"},
            {"name": "Status", "label": "Status", "type": "picklist"}, {"name": "CreatedDate", "label": "Created Date", "type": "datetime"},
            {"name": "Email", "label": "Email", "type": "email"}]
    rows = [{"id": "00Q000000000001", "values": {}}, {"id": "00Q000000000002", "values": {}}]
    out = assignment.add_gap_reason(cols, rows, {"00Q000000000001": "Matches none"})
    assert [c["label"] for c in out] == ["Name", "Current Owner", "Status", "Created Date", "Assignment Gap Reason", "Email"]
    assert [r["values"]["AssignmentGapReason"] for r in rows] == ["Matches none", None]
