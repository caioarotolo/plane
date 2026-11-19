# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from base64 import b64encode
from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from plane.db.models import Page, Project, ProjectMember, ProjectPage, Workspace
from plane.tests.factories import UserFactory


pytestmark = [pytest.mark.contract, pytest.mark.django_db, pytest.mark.usefixtures("mock_celery")]


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="Project Pages", identifier="PAGES")
    ProjectMember.objects.create(workspace=workspace, project=project, member=create_user, role=20)
    return project


def pages_url(project):
    return f"/api/v1/workspaces/{project.workspace.slug}/projects/{project.id}/pages/"


def add_page(project, owner, **fields):
    page = Page.objects.create(workspace=project.workspace, owned_by=owner, **fields)
    link = ProjectPage.objects.create(workspace=project.workspace, project=project, page=page)
    return page, link


def test_create_list_and_retrieve_private_page(api_key_client, project, create_user):
    url = pages_url(project)
    response = api_key_client.post(
        url,
        {"name": "Meeting notes", "description_html": "<p>Body</p><script>x</script>", "access": 1},
        format="json",
    )

    assert response.status_code == 201, response.data
    page_id = response.data["id"]
    assert response.data["owned_by"] == create_user.id
    assert ProjectPage.objects.filter(page_id=page_id, project=project, workspace=project.workspace).exists()
    assert response.data["access"] == Page.PRIVATE_ACCESS
    assert "<script>" not in response.data["description_html"]

    other = UserFactory()
    add_page(project, other, access=Page.PRIVATE_ACCESS)
    detached, link = add_page(project, create_user)
    link.delete()

    response = api_key_client.get(url, {"per_page": 1})
    assert response.status_code == 200, response.data
    assert response.data["total_results"] == 1
    assert [row["id"] for row in response.data["results"]] == [page_id]
    assert "description_html" not in response.data["results"][0]

    response = api_key_client.get(f"{url}{page_id}/")
    assert response.status_code == 200, response.data
    assert "<p>Body</p>" in response.data["description_html"]
    assert api_key_client.get(f"{url}{detached.id}/").status_code in (403, 404)


def test_permissions_and_workspace_scoped_keys(api_key_client, api_token, project, create_user):
    url = pages_url(project)
    payload = {"name": "Updated"}
    private, _ = add_page(project, UserFactory(), access=Page.PRIVATE_ACCESS)

    assert APIClient().get(url).status_code in (401, 403)
    assert api_key_client.get(f"{url}{private.id}/").status_code in (403, 404)
    assert api_key_client.put(f"{url}{private.id}/", payload, format="json").status_code in (403, 404)

    ProjectMember.objects.filter(project=project, member=create_user).update(role=5)
    public, _ = add_page(project, UserFactory())
    assert api_key_client.get(url).data["results"] == []
    assert api_key_client.get(f"{url}{public.id}/").status_code in (403, 404)
    Project.objects.filter(pk=project.pk).update(guest_view_all_features=True)
    assert api_key_client.get(f"{url}{public.id}/").status_code == 200
    assert api_key_client.put(f"{url}{public.id}/", payload, format="json").status_code == 403

    api_token.workspace = Workspace.objects.create(name="Different workspace", slug="elsewhere", owner=create_user)
    api_token.save(update_fields=["workspace"])
    assert api_key_client.get(url).status_code == 403


def test_update_forwards_to_live_and_returns_persisted_document(api_key_client, project, create_user, mocker, settings):
    settings.LIVE_SERVER_SECRET_KEY = "test-live-secret"
    settings.LIVE_URL = "http://live.test/live/"
    page, _ = add_page(project, create_user, name="Original", description_html="<p>Original</p>")
    url = f"{pages_url(project)}{page.id}/"
    payload = {"name": "Renamed", "description_html": "<h2>New body</h2>"}
    binary = b64encode(b"test-yjs-update").decode()

    def save_in_live(_url, **kwargs):
        assert kwargs["json"]["name"] == payload["name"]
        assert kwargs["json"]["description_html"] == payload["description_html"]
        live_client = APIClient()
        live_client.credentials(
            HTTP_X_API_KEY=kwargs["headers"]["X-Api-Key"],
            HTTP_LIVE_SERVER_SECRET_KEY=kwargs["headers"]["Live-Server-Secret-Key"],
        )
        response = live_client.get(f"{url}live-content/")
        assert response.status_code == 200
        assert response.content == b""
        response = live_client.patch(
            f"{url}live-content/", {**payload, "description_binary": binary, "description_json": {}}, format="json"
        )
        assert response.status_code == 204, response.data
        return SimpleNamespace(status_code=204)

    live = mocker.patch("plane.api.views.page.requests.post", side_effect=save_in_live)
    assert api_key_client.get(f"{url}live-content/").status_code == 404
    response = api_key_client.put(url, payload, format="json")
    assert response.status_code == 200, response.data
    assert response.data["name"] == payload["name"]
    assert response.data["description_html"] == payload["description_html"]
    page.refresh_from_db()
    assert bytes(page.description_binary) == b"test-yjs-update"

    Page.objects.filter(pk=page.pk).update(is_locked=True)
    assert api_key_client.put(url, payload, format="json").status_code == 400
    assert live.call_count == 1


def test_live_failure_does_not_report_a_successful_edit(api_key_client, project, create_user, mocker, settings):
    settings.LIVE_SERVER_SECRET_KEY = "test-live-secret"
    settings.LIVE_URL = "http://live.test/live/"
    page, _ = add_page(project, create_user, name="Original")
    mocker.patch("plane.api.views.page.requests.post", return_value=SimpleNamespace(status_code=503))

    response = api_key_client.put(f"{pages_url(project)}{page.id}/", {"name": "Renamed"}, format="json")

    assert response.status_code == 502
    page.refresh_from_db()
    assert page.name == "Original"
