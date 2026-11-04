"""Days in Queue: from the last Lead Owner change, or the Created Date when there's none."""
from datetime import datetime, timedelta, timezone

from app.salesforce import queues
from app.salesforce.errors import SalesforceError


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


class FakeSf:
    def __init__(self, history=None, fail=False):
        self.history, self.fail, self.soql = history or [], fail, []

    def query(self, soql, max_rows=None):
        self.soql.append(soql)
        if self.fail:
            raise SalesforceError("LeadHistory isn't available")
        return {"records": self.history}


COLS = [{"name": "Name", "label": "Name", "type": "string"}, {"name": "OwnerId", "label": "Owner ID", "type": "reference"},
        {"name": "CreatedDate", "label": "Created Date", "type": "datetime"}]


def _rows():
    return [{"id": "00Q000000000001AAA", "values": {"CreatedDate": _iso(20)}},
            {"id": "00Q000000000002AAA", "values": {"CreatedDate": _iso(9)}}]


def test_days_from_the_last_owner_change_else_created():
    sf = FakeSf([{"LeadId": "00Q000000000001AAA", "CreatedDate": _iso(4)}, {"LeadId": "00Q000000000001AAA", "CreatedDate": _iso(15)}])
    rows = _rows()
    cols = queues.add_days_in_queue(sf, COLS, rows)
    assert [c["label"] for c in cols] == ["Name", "Queue Name", "Days in Queue", "Urgency", "Created Date"]
    assert [r["values"]["DaysInQueue"] for r in rows] == [4, 9]  # latest owner change; no change → created
    assert "Field = 'Owner' AND LeadId IN ('00Q000000000001AAA', '00Q000000000002AAA')" in sf.soql[0]


def test_without_lead_history_every_lead_counts_from_created():
    rows = _rows()
    queues.add_days_in_queue(FakeSf(fail=True), COLS, rows)
    assert [r["values"]["DaysInQueue"] for r in rows] == [20, 9]
