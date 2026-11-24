/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { IApiToken } from "@plane/types";

export const MCP_OAUTH_LABEL_PREFIX = "MCP OAuth · ";
export const MCP_OAUTH_DESCRIPTION_MARKER = "Created after OAuth consent.";
export const MCP_OAUTH_ENDPOINT_PATH = "/mcp";

export function isMcpOAuthToken(token: Pick<IApiToken, "label" | "description">): boolean {
  const label = token.label ?? "";
  const description = token.description ?? "";
  return label.startsWith(MCP_OAUTH_LABEL_PREFIX) || description.includes(MCP_OAUTH_DESCRIPTION_MARKER);
}

export function getMcpOAuthClientName(token: Pick<IApiToken, "label">): string {
  const label = token.label?.trim() ?? "";
  if (label.startsWith(MCP_OAUTH_LABEL_PREFIX)) {
    const clientName = label.slice(MCP_OAUTH_LABEL_PREFIX.length).trim();
    if (clientName) return clientName;
  }
  return label || "MCP Client";
}

export function getMcpOAuthEndpointUrl(origin?: string): string {
  const resolvedOrigin = origin ?? (typeof window !== "undefined" ? window.location.origin : "");
  const normalizedOrigin = resolvedOrigin.trim().replace(/\/+$/, "");
  return normalizedOrigin ? `${normalizedOrigin}${MCP_OAUTH_ENDPOINT_PATH}` : MCP_OAUTH_ENDPOINT_PATH;
}

function getTokenSortTimestamp(token: Pick<IApiToken, "last_used" | "created_at">): number {
  const timestamp = Date.parse(token.last_used ?? token.created_at ?? "");
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

export function partitionApiTokens(tokens: IApiToken[]): {
  oauthTokens: IApiToken[];
  personalTokens: IApiToken[];
} {
  const oauthTokens: IApiToken[] = [];
  const personalTokens: IApiToken[] = [];

  for (const token of tokens) {
    if (isMcpOAuthToken(token)) {
      oauthTokens.push(token);
    } else {
      personalTokens.push(token);
    }
  }

  oauthTokens.sort((a, b) => {
    if (a.is_active !== b.is_active) return a.is_active ? -1 : 1;
    return getTokenSortTimestamp(b) - getTokenSortTimestamp(a);
  });

  return { oauthTokens, personalTokens };
}
