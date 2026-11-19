# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.page import ProjectPageAPI, ProjectPageContentAPI

pages = "workspaces/<str:slug>/projects/<uuid:project_id>/pages/"

urlpatterns = [
    path(pages, ProjectPageAPI.as_view(http_method_names=["get", "post"]), name="api-project-pages"),
    path(f"{pages}<uuid:page_id>/", ProjectPageAPI.as_view(http_method_names=["get", "put"]), name="api-project-page"),
    path(f"{pages}<uuid:page_id>/live-content/", ProjectPageContentAPI.as_view(), name="api-project-page-live-content"),
]
