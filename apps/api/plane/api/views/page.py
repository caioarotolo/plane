# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.crypto import constant_time_compare
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from plane.api.views.base import BaseAPIView
from plane.app.permissions import ProjectPagePermission, ROLE
from plane.app.serializers.page import PageBinaryUpdateSerializer, PageDetailSerializer
from plane.bgtasks.page_transaction_task import page_transaction
from plane.bgtasks.page_version_task import track_page_version
from plane.db.models import APIToken, Page, Project, ProjectMember, ProjectPage
from plane.utils.exception_logger import log_exception
from plane.utils.url import normalize_url_path


class PageWriteSerializer(PageDetailSerializer):
    name = serializers.CharField(allow_blank=True)
    description_html = serializers.CharField(allow_blank=True)

    class Meta(PageDetailSerializer.Meta):
        fields = ["name", "description_html"]
        read_only_fields = []


class PageCreateSerializer(PageWriteSerializer):
    parent_id = serializers.UUIDField(required=False)
    is_locked = serializers.BooleanField(required=False)

    class Meta(PageWriteSerializer.Meta):
        fields = PageWriteSerializer.Meta.fields + [
            "access",
            "color",
            "parent_id",
            "is_locked",
            "external_id",
            "external_source",
        ]


class ProjectPageListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Page
        fields = [
            "id",
            "name",
            "access",
            "color",
            "is_locked",
            "archived_at",
            "workspace",
            "owned_by",
            "parent_id",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "external_id",
            "external_source",
        ]


class ProjectPageSerializer(ProjectPageListSerializer):
    class Meta(ProjectPageListSerializer.Meta):
        fields = ProjectPageListSerializer.Meta.fields + ["description_html"]


class ProjectPageBaseAPI(BaseAPIView):
    permission_classes = [ProjectPagePermission]

    def initialize_request(self, request, *args, **kwargs):
        request.api_log_body = False
        return super().initialize_request(request, *args, **kwargs)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        slug = self.kwargs["slug"]
        if APIToken.objects.filter(token=request.auth, workspace__isnull=False).exclude(workspace__slug=slug).exists():
            raise PermissionDenied()
        self.project = get_object_or_404(Project, workspace__slug=slug, pk=self.kwargs["project_id"], archived_at=None)

    def get_pages(self):
        links = ProjectPage.objects.filter(project=self.project, workspace_id=self.project.workspace_id)
        return Page.objects.filter(workspace_id=self.project.workspace_id, pk__in=links.values("page_id"))

    def get_page(self, page_id, *, lock=False):
        pages = self.get_pages()
        return get_object_or_404(pages.select_for_update() if lock else pages, pk=page_id)

    def require_editable_page(self, page):
        if page.is_locked or page.archived_at:
            raise ValidationError({"error": "Locked or archived pages cannot be updated."})


class ProjectPageAPI(ProjectPageBaseAPI):
    def get(self, request, slug, project_id, page_id=None):
        if page_id is not None:
            return Response(ProjectPageSerializer(self.get_page(page_id)).data)

        visible = Q(owned_by=request.user)
        if (
            self.project.guest_view_all_features
            or not ProjectMember.objects.filter(
                project=self.project, member=request.user, role=ROLE.GUEST.value, is_active=True
            ).exists()
        ):
            visible |= Q(access=Page.PUBLIC_ACCESS)
        pages = (
            self.get_pages()
            .filter(visible, archived_at=None)
            .defer("description_html", "description_json", "description_binary")
            .order_by("-created_at", "id")
        )
        return self.paginate(
            request=request,
            queryset=pages,
            default_per_page=100,
            on_results=lambda rows: ProjectPageListSerializer(rows, many=True).data,
        )

    @transaction.atomic
    def post(self, request, slug, project_id):
        serializer = PageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        if (parent_id := fields.get("parent_id")) and not self.get_pages().filter(
            Q(owned_by=request.user) | Q(access=Page.PUBLIC_ACCESS), pk=parent_id, archived_at=None
        ).exists():
            raise ValidationError({"parent_id": "Parent page must be visible in this project."})

        page = Page.objects.create(workspace_id=self.project.workspace_id, owned_by=request.user, **fields)
        ProjectPage.objects.create(project=self.project, workspace_id=self.project.workspace_id, page=page)
        transaction.on_commit(
            lambda: page_transaction.delay(
                new_description_html=page.description_html, old_description_html=None, page_id=str(page.id)
            )
        )
        return Response(ProjectPageSerializer(page).data, status=status.HTTP_201_CREATED)

    def put(self, request, slug, project_id, page_id):
        page = self.get_page(page_id)
        self.require_editable_page(page)
        serializer = PageWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if not serializer.validated_data:
            raise ValidationError({"error": "Pass a name or description_html."})

        live_url = settings.LIVE_URL or urljoin(settings.WEB_URL or "", settings.LIVE_BASE_PATH)
        if not live_url.startswith(("https://", "http://")) or not settings.LIVE_SERVER_SECRET_KEY:
            return Response({"error": "The live editor is unavailable."}, status=status.HTTP_502_BAD_GATEWAY)

        try:
            response = requests.post(
                normalize_url_path(f"{live_url.rstrip('/')}/collaboration/project-page/"),
                headers={"X-Api-Key": request.auth, "Live-Server-Secret-Key": settings.LIVE_SERVER_SECRET_KEY},
                json={
                    "slug": slug,
                    "projectId": str(project_id),
                    "pageId": str(page_id),
                    "userId": str(request.user.id),
                    **serializer.validated_data,
                },
                timeout=15,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            log_exception(exc)
        else:
            if response.status_code == status.HTTP_204_NO_CONTENT:
                page.refresh_from_db()
                return Response(ProjectPageSerializer(page).data)
        return Response({"error": "The live editor could not save the page."}, status=status.HTTP_502_BAD_GATEWAY)


class ProjectPageContentAPI(ProjectPageBaseAPI):
    """Binary persistence for the live editor handling an API edit."""

    def get_throttles(self):
        return []  # The API update already consumed the caller's rate limit.

    def initial(self, request, *args, **kwargs):
        secret = settings.LIVE_SERVER_SECRET_KEY
        if not secret or not constant_time_compare(secret, request.headers.get("Live-Server-Secret-Key", "")):
            raise NotFound()
        super().initial(request, *args, **kwargs)

    def get(self, request, slug, project_id, page_id):
        page = self.get_page(page_id)
        return HttpResponse(page.description_binary or b"", content_type="application/octet-stream")

    @transaction.atomic
    def patch(self, request, slug, project_id, page_id):
        page = self.get_page(page_id, lock=True)
        self.require_editable_page(page)
        before = page.description_html
        serializer = PageBinaryUpdateSerializer(page, data=request.data)
        serializer.is_valid(raise_exception=True)
        if "name" in request.data:
            page.name = serializers.CharField(allow_blank=True).run_validation(request.data["name"])
        serializer.save()
        if before != page.description_html:
            transaction.on_commit(
                lambda: page_transaction.delay(
                    new_description_html=page.description_html, old_description_html=before, page_id=str(page.id)
                )
            )
            transaction.on_commit(
                lambda: track_page_version.delay(
                    page_id=str(page.id),
                    existing_instance=json.dumps({"description_html": before}),
                    user_id=str(request.user.id),
                )
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
