import pytest
import responses
from responses import matchers

from tools.code_inspector import _code_inspector_impl, _parse_worklist


BASE = "https://sap.example.com:8443"


@pytest.fixture
def base(keyring_stub, monkeypatch):
    monkeypatch.setattr("adt_client.discovery.find_adt_url", lambda: BASE)


WORKLIST_WITH_FINDINGS = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<atcworklist:worklist atcworklist:id="WID1" atcworklist:timestamp="x"'
    ' xmlns:atcworklist="http://www.sap.com/adt/atc/worklist">'
    '<atcworklist:objects>'
    '<atcworklist:object atcworklist:name="ZFOO" atcworklist:type="PROG/P"'
    '                    atcworklist:packageName="ZPKG">'
    '<atcworklist:findings>'
    '<atcfinding:finding atcfinding:priority="2" atcfinding:checkId="PERF"'
    '                    atcfinding:messageTitle="Hardcoded SY-SUBRC"'
    '                    atcfinding:location="/sap/bc/adt/programs/programs/zfoo/source/main#start=5,1"'
    '                    xmlns:atcfinding="http://www.sap.com/adt/atc/finding"/>'
    '<atcfinding:finding atcfinding:priority="3" atcfinding:checkId="ROBUST"'
    '                    atcfinding:messageTitle="No USING option"'
    '                    atcfinding:location="/sap/bc/adt/programs/programs/zfoo/source/main#start=9,1"'
    '                    xmlns:atcfinding="http://www.sap.com/adt/atc/finding"/>'
    '</atcworklist:findings>'
    '</atcworklist:object>'
    '</atcworklist:objects>'
    '</atcworklist:worklist>'
)


def test_parse_worklist_counts_by_priority():
    findings, summary = _parse_worklist(WORKLIST_WITH_FINDINGS)
    assert len(findings) == 2
    assert summary == {"error_count": 1, "warning_count": 1, "info_count": 0}
    assert findings[0]["line"] == 5 and findings[0]["severity"] == "E"
    assert findings[1]["line"] == 9 and findings[1]["severity"] == "W"


def test_parse_worklist_empty_objects():
    xml = (
        '<atcworklist:worklist xmlns:atcworklist="http://www.sap.com/adt/atc/worklist">'
        '<atcworklist:objects/></atcworklist:worklist>'
    )
    findings, summary = _parse_worklist(xml)
    assert findings == []
    assert summary == {"error_count": 0, "warning_count": 0, "info_count": 0}


@responses.activate
def test_code_inspector_returns_object_not_found_on_404(base):
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/core/discovery",
        status=200, headers={"x-csrf-token": "T"}, body="<ok/>",
    )
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/programs/programs/ZGHOST",
        status=404,
        headers={"Content-Type": "application/xml"},
        body=(
            '<exc:exception xmlns:exc="http://www.sap.com/abapxml/types/defined">'
            '<type>NotFound</type>'
            '<localizedMessage>ZGHOST does not exist</localizedMessage>'
            '</exc:exception>'
        ),
    )
    r = _code_inspector_impl("ZGHOST", "program")
    assert r["error"] == "ObjectNotFound"
    assert "ZGHOST" in r["detail"]


@responses.activate
def test_code_inspector_runs_three_step_flow(base):
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/core/discovery",
        status=200, headers={"x-csrf-token": "T"}, body="<ok/>",
    )
    # Step 0: existence probe.
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/programs/programs/ZFOO",
        status=200, body="<ok/>",
    )
    # Step 1: worklist create -> plain text id.
    responses.add(
        responses.POST, BASE + "/sap/bc/adt/atc/worklists",
        status=200, body="WID1",
        match=[matchers.query_param_matcher({"checkVariant": "DEFAULT"})],
    )
    # Step 2: run.
    seen_run = {}
    def _run_cb(request):
        seen_run["body"] = (request.body.decode()
                            if isinstance(request.body, (bytes, bytearray))
                            else request.body)
        return (200, {}, "<ok/>")
    responses.add_callback(
        responses.POST, BASE + "/sap/bc/adt/atc/runs", callback=_run_cb,
        match=[matchers.query_param_matcher({"worklistId": "WID1"})],
    )
    # Step 3: fetch worklist with findings.
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/atc/worklists/WID1",
        status=200, body=WORKLIST_WITH_FINDINGS,
    )
    r = _code_inspector_impl("ZFOO", "program", variant="DEFAULT")
    assert r["variant"] == "DEFAULT"
    assert len(r["findings"]) == 2
    assert r["summary"]["error_count"] == 1
    assert r["summary"]["warning_count"] == 1
    assert "ZFOO" in seen_run["body"].upper()
    assert 'xmlns:atc="http://www.sap.com/adt/atc"' in seen_run["body"]


@responses.activate
def test_code_inspector_empty_worklist_id_errors(base):
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/core/discovery",
        status=200, headers={"x-csrf-token": "T"}, body="<ok/>",
    )
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/programs/programs/ZFOO",
        status=200, body="<ok/>",
    )
    responses.add(
        responses.POST, BASE + "/sap/bc/adt/atc/worklists",
        status=200, body="",
    )
    r = _code_inspector_impl("ZFOO", "program", variant="BOGUS_VARIANT")
    assert r["error"] == "ATCWorklistEmpty"
