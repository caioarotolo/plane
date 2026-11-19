/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { AppError } from "@/lib/errors";
import { env } from "@/env";
import { PageService } from "./extended.service";

interface ProjectPageServiceParams {
  workspaceSlug: string | null;
  projectId: string | null;
  cookie: string | null;
  apiKey?: string;
  [key: string]: unknown;
}

export class ProjectPageService extends PageService {
  protected basePath: string;

  constructor(params: ProjectPageServiceParams) {
    super();
    const { workspaceSlug, projectId, apiKey, cookie } = params;
    if (!workspaceSlug || !projectId) throw new AppError("Missing required fields.");
    if (apiKey) {
      this.basePath = `/api/v1/workspaces/${encodeURIComponent(workspaceSlug)}/projects/${encodeURIComponent(projectId)}`;
      this.descriptionPath = "live-content";
      this.setHeader("X-Api-Key", apiKey);
      this.setHeader("Live-Server-Secret-Key", env.LIVE_SERVER_SECRET_KEY);
      return;
    }
    // validate cookie
    if (!cookie) throw new AppError("Cookie is required.");
    // set cookie
    this.setHeader("Cookie", cookie);
    // set base path
    this.basePath = `/api/workspaces/${encodeURIComponent(workspaceSlug)}/projects/${encodeURIComponent(projectId)}`;
  }
}
