# ruff: noqa: F811
import json

import httpx
import pytest
import respx

from amocrm import services
from tests.test_amocrm import HOST, conn  # noqa: F401

GROUPS = f"https://{HOST}/api/v4/leads/custom_fields/groups"
FIELDS = f"https://{HOST}/api/v4/leads/custom_fields"


@pytest.mark.django_db
@respx.mock
def test_old_prefixed_fields_move_into_the_uzbridge_tab(conn):
    respx.get(GROUPS).mock(return_value=httpx.Response(200, json={"_embedded": {"custom_field_groups": []}}))
    made = respx.post(GROUPS).mock(
        return_value=httpx.Response(200, json={"_embedded": {"custom_field_groups": [{"id": "leads_77", "name": "uzbridge"}]}})
    )
    respx.get(FIELDS).mock(
        return_value=httpx.Response(
            200, json={"_embedded": {"custom_fields": [{"id": 501, "name": "uzbridge: toʻlov havolasi", "type": "url"}]}}
        )
    )
    patch = respx.patch(FIELDS).mock(return_value=httpx.Response(200, json={}))
    post = respx.post(FIELDS).mock(
        return_value=httpx.Response(200, json={"_embedded": {"custom_fields": [{"id": 502, "name": "Toʻlov holati"}]}})
    )
    services.create_lead_fields(conn)
    conn.refresh_from_db()
    assert json.loads(made.calls.last.request.content) == [{"name": "uzbridge", "sort": 5}]
    assert json.loads(patch.calls.last.request.content) == [{"id": 501, "name": "Toʻlov havolasi", "group_id": "leads_77"}]
    assert json.loads(post.calls.last.request.content)[0] == {
        "name": "Toʻlov holati", "type": "text", "sort": 501, "group_id": "leads_77"
    }
    assert (conn.link_field_id, conn.status_field_id, conn.field_group) == (501, 502, "leads_77")
