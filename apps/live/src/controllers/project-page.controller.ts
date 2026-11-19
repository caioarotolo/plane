/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Hocuspocus } from "@hocuspocus/server";
import express from "express";
import type { Request, Response } from "express";
import * as Y from "yjs";
import { z } from "zod";
// plane imports
import { Controller, Middleware, Post } from "@plane/decorators";
import { getBinaryDataFromDocumentEditorHTMLString } from "@plane/editor/server";
import { logger } from "@plane/logger";
import { requireSecretKey } from "@/lib/auth-middleware";
import { PROJECT_PAGE_API_ORIGIN } from "@/types";
import type { HocusPocusServerContext } from "@/types";

const projectPageUpdate = z
  .object({
    slug: z.string().min(1),
    projectId: z.string().uuid(),
    pageId: z.string().uuid(),
    userId: z.string().uuid(),
    name: z.string().optional(),
    description_html: z.string().optional(),
  })
  .refine(({ name, description_html }) => name !== undefined || description_html !== undefined);

export const PROJECT_PAGE_EDIT_PATH = "/collaboration/project-page";
export const projectPageJson = express.json({ limit: "10mb" });

@Controller(PROJECT_PAGE_EDIT_PATH)
export class ProjectPageController {
  [key: string]: unknown;
  private readonly hocusPocusServer: Hocuspocus;

  constructor(hocusPocusServer: Hocuspocus) {
    this.hocusPocusServer = hocusPocusServer;
  }

  @Post("/")
  @Middleware(requireSecretKey)
  async updateProjectPage(req: Request, res: Response) {
    const parsed = projectPageUpdate.safeParse(req.body);
    const apiKey = req.get("X-Api-Key");
    if (!parsed.success || !apiKey) return res.status(400).json({ error: "Invalid project page update" });

    const { slug, projectId, pageId, userId, name, description_html } = parsed.data;
    const context: HocusPocusServerContext = {
      workspaceSlug: slug,
      projectId,
      userId,
      apiKey,
      cookie: "",
      documentType: "project_page",
      updateTitle: name !== undefined,
    };
    const replacement = new Y.Doc();

    try {
      Y.applyUpdate(replacement, getBinaryDataFromDocumentEditorHTMLString(description_html || "<p></p>", name));
      const connection = await this.hocusPocusServer.openDirectConnection(pageId, context);
      try {
        const document = connection.document;
        if (!document) throw new Error("Page document is unavailable");
        const fields: string[] = [];
        if (description_html !== undefined) fields.push("default");
        if (name !== undefined) fields.push("title");

        document.transact(() => {
          for (const field of fields) {
            const fragment = document.getXmlFragment(field);
            const content = replacement
              .getXmlFragment(field)
              .toArray()
              .filter((node) => node instanceof Y.XmlElement || node instanceof Y.XmlText)
              .map((node) => node.clone());
            fragment.delete(0, fragment.length);
            fragment.insert(0, content);
          }
        }, PROJECT_PAGE_API_ORIGIN);
      } finally {
        // The direct connection flushes the edited document through the usual database extension.
        await connection.disconnect();
      }
      return res.sendStatus(204);
    } catch {
      logger.error("Project page update did not complete", { pageId });
      return res.status(502).json({ error: "Could not save the project page" });
    } finally {
      replacement.destroy();
    }
  }
}
