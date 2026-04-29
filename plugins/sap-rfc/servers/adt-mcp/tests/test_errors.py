import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from errors import ADTNotAvailable, ADTError


def test_adt_not_available_carries_tried_list():
    e = ADTNotAvailable([{"url": "https://a", "reason": "tcp timeout"}])
    assert e.tried == [{"url": "https://a", "reason": "tcp timeout"}]
    assert "tcp timeout" in str(e)


def test_adt_error_from_response_parses_sap_exception_xml():
    class FakeResp:
        status_code = 400
        text = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<exc:exception xmlns:exc="http://www.sap.com/abapxml/types/defined">'
            '<namespace>com.sap.adt</namespace>'
            '<type>ExceptionResourceFailure</type>'
            '<localizedMessage lang="EN">Object ZFOO is locked by user BAR</localizedMessage>'
            '</exc:exception>'
        )
        headers = {"Content-Type": "application/xml"}

    e = ADTError.from_response(FakeResp())
    assert e.status == 400
    assert "locked" in e.message
    assert e.code == "ExceptionResourceFailure"


def test_adt_error_from_response_non_xml_body():
    class FakeResp:
        status_code = 500
        text = "Internal Server Error"
        headers = {"Content-Type": "text/html"}

    e = ADTError.from_response(FakeResp())
    assert e.status == 500
    assert e.message == "Internal Server Error"
    assert e.code == ""
