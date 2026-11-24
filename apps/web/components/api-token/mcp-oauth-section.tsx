/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { mutate } from "swr";
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { Icon } from "@makeplane/propel/components/icon";
import { CopyOutline, DeleteOutline, LinkOutline, TickOutline } from "@makeplane/propel/icons";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { API_TOKENS_LIST } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { APITokenService } from "@plane/services";
import type { IApiToken } from "@plane/types";
import { copyTextToClipboard, renderFormattedDate } from "@plane/utils";
// components
import { ProfileSettingsHeading } from "@/components/settings/profile/heading";
// local imports
import { getMcpOAuthClientName, getMcpOAuthEndpointUrl } from "./mcp-oauth";

const apiTokenService = new APITokenService();

type McpOAuthCopy = {
  headingTitle: string;
  headingDescription: string;
  activeCount: (count: number) => string;
  clearExpired: (count: number) => string;
  endpointTitle: string;
  endpointBadge: string;
  endpointHint: string;
  copyUrl: string;
  copied: string;
  copySuccessTitle: string;
  copySuccessMessage: string;
  copyErrorTitle: string;
  copyErrorMessage: string;
  emptyState: string;
  createdLabel: string;
  expiresLabel: string;
  expiredOnLabel: string;
  lastUsedLabel: string;
  revoke: string;
  revoking: string;
  remove: string;
  removing: string;
  revokeDialogTitle: string;
  revokeDialogDescription: (clientName: string) => string;
  removeDialogTitle: string;
  removeDialogDescription: (clientName: string) => string;
  revokeSuccessTitle: string;
  revokeSuccessMessage: (clientName: string) => string;
  removeSuccessTitle: string;
  removeSuccessMessage: (clientName: string) => string;
  revokeErrorTitle: string;
  revokeErrorMessage: string;
  clearExpiredDialogTitle: string;
  clearExpiredDialogDescription: (count: number) => string;
  clearExpiredSuccessTitle: string;
  clearExpiredSuccessMessage: (count: number) => string;
  clearExpiredPartialErrorTitle: string;
  clearExpiredPartialErrorMessage: (failedCount: number) => string;
};

const PT_COPY: McpOAuthCopy = {
  headingTitle: "Conexões OAuth (MCP)",
  headingDescription:
    "Conecte agentes de IA ao Plane via OAuth sem copiar tokens manualmente e revogue autorizações quando precisar.",
  activeCount: (count) => (count === 1 ? "1 ativa" : `${count} ativas`),
  clearExpired: (count) => `Limpar expiradas (${count})`,
  endpointTitle: "URL para handshake MCP (OAuth)",
  endpointBadge: "Expira em 7 dias",
  endpointHint:
    "Cole esta URL no Claude, ChatGPT, Codex, Antigravity ou outro cliente MCP compatível com OAuth para autorizar uma nova conexão.",
  copyUrl: "Copiar URL",
  copied: "Copiado",
  copySuccessTitle: "URL copiada",
  copySuccessMessage: "A URL do servidor MCP foi copiada para a área de transferência.",
  copyErrorTitle: "Erro ao copiar",
  copyErrorMessage: "Não foi possível copiar a URL do servidor MCP.",
  emptyState: "Nenhuma conexão OAuth encontrada. Copie a URL acima para iniciar um novo handshake no seu agente.",
  createdLabel: "Criado em",
  expiresLabel: "Expira em",
  expiredOnLabel: "Expirou em",
  lastUsedLabel: "Último uso",
  revoke: "Revogar",
  revoking: "Revogando...",
  remove: "Remover",
  removing: "Removendo...",
  revokeDialogTitle: "Revogar conexão OAuth",
  revokeDialogDescription: (clientName) =>
    `Revogar "${clientName}" desconectará este agente imediatamente. Para voltar a acessar o Plane, será necessário fazer um novo handshake OAuth.`,
  removeDialogTitle: "Remover conexão expirada",
  removeDialogDescription: (clientName) => `Remover o registro expirado de "${clientName}" da lista de conexões OAuth?`,
  revokeSuccessTitle: "Conexão revogada",
  revokeSuccessMessage: (clientName) => `O acesso OAuth de "${clientName}" foi revogado com sucesso.`,
  removeSuccessTitle: "Conexão removida",
  removeSuccessMessage: (clientName) => `O registro expirado de "${clientName}" foi removido.`,
  revokeErrorTitle: "Erro ao revogar conexão",
  revokeErrorMessage: "Não foi possível revogar esta autorização OAuth. Tente novamente.",
  clearExpiredDialogTitle: "Limpar conexões expiradas",
  clearExpiredDialogDescription: (count) =>
    count === 1
      ? "Remover 1 conexão OAuth expirada da sua lista?"
      : `Remover ${count} conexões OAuth expiradas da sua lista?`,
  clearExpiredSuccessTitle: "Conexões expiradas removidas",
  clearExpiredSuccessMessage: (count) =>
    count === 1 ? "1 conexão expirada foi removida." : `${count} conexões expiradas foram removidas.`,
  clearExpiredPartialErrorTitle: "Remoção parcial",
  clearExpiredPartialErrorMessage: (failedCount) =>
    failedCount === 1
      ? "1 conexão expirada não pôde ser removida. Tente novamente."
      : `${failedCount} conexões expiradas não puderam ser removidas. Tente novamente.`,
};

const EN_COPY: McpOAuthCopy = {
  headingTitle: "OAuth Connections (MCP)",
  headingDescription:
    "Connect AI agents to Plane using OAuth without copying tokens manually, and revoke authorizations at any time.",
  activeCount: (count) => `${count} active`,
  clearExpired: (count) => `Clear expired (${count})`,
  endpointTitle: "MCP Handshake URL (OAuth)",
  endpointBadge: "7-day expiry",
  endpointHint:
    "Paste this URL in Claude, ChatGPT, Codex, Antigravity, or any OAuth-compatible MCP client to start a new handshake.",
  copyUrl: "Copy URL",
  copied: "Copied",
  copySuccessTitle: "URL copied",
  copySuccessMessage: "The MCP server URL has been copied to your clipboard.",
  copyErrorTitle: "Copy failed",
  copyErrorMessage: "Could not copy the MCP server URL.",
  emptyState: "No OAuth connections yet. Copy the URL above to start a new handshake from your agent.",
  createdLabel: "Created",
  expiresLabel: "Expires",
  expiredOnLabel: "Expired",
  lastUsedLabel: "Last used",
  revoke: "Revoke",
  revoking: "Revoking...",
  remove: "Remove",
  removing: "Removing...",
  revokeDialogTitle: "Revoke OAuth connection",
  revokeDialogDescription: (clientName) =>
    `Revoking "${clientName}" immediately disconnects this agent. A new OAuth handshake will be required to reconnect.`,
  removeDialogTitle: "Remove expired connection",
  removeDialogDescription: (clientName) => `Remove the expired record for "${clientName}" from your OAuth connections?`,
  revokeSuccessTitle: "Connection revoked",
  revokeSuccessMessage: (clientName) => `OAuth access for "${clientName}" has been revoked.`,
  removeSuccessTitle: "Connection removed",
  removeSuccessMessage: (clientName) => `Expired record for "${clientName}" has been removed.`,
  revokeErrorTitle: "Revoke failed",
  revokeErrorMessage: "Could not revoke this OAuth authorization. Please try again.",
  clearExpiredDialogTitle: "Clear expired connections",
  clearExpiredDialogDescription: (count) =>
    count === 1
      ? "Remove 1 expired OAuth connection from your list?"
      : `Remove ${count} expired OAuth connections from your list?`,
  clearExpiredSuccessTitle: "Expired connections cleared",
  clearExpiredSuccessMessage: (count) =>
    count === 1 ? "1 expired connection was removed." : `${count} expired connections were removed.`,
  clearExpiredPartialErrorTitle: "Partially cleared",
  clearExpiredPartialErrorMessage: (failedCount) =>
    failedCount === 1
      ? "1 expired connection could not be removed. Please try again."
      : `${failedCount} expired connections could not be removed. Please try again.`,
};

type Props = {
  tokens: IApiToken[];
};

export function McpOAuthSection({ tokens }: Props) {
  const { t, currentLocale } = useTranslation();
  const copy = currentLocale?.toLowerCase().startsWith("pt") ? PT_COPY : EN_COPY;

  const [copied, setCopied] = useState(false);
  const [tokenToRevoke, setTokenToRevoke] = useState<IApiToken | null>(null);
  const [isRevoking, setIsRevoking] = useState(false);
  const [isClearExpiredOpen, setIsClearExpiredOpen] = useState(false);
  const [isClearingExpired, setIsClearingExpired] = useState(false);
  const copyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const mcpUrl = useMemo(() => getMcpOAuthEndpointUrl(), []);
  const activeTokens = useMemo(() => tokens.filter((token) => token.is_active), [tokens]);
  const expiredTokens = useMemo(() => tokens.filter((token) => !token.is_active), [tokens]);

  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) {
        clearTimeout(copyTimeoutRef.current);
      }
    };
  }, []);

  const handleCopyUrl = async () => {
    try {
      await copyTextToClipboard(mcpUrl);
      setCopied(true);
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
      copyTimeoutRef.current = setTimeout(() => setCopied(false), 2000);
      setToast({
        type: "success",
        title: copy.copySuccessTitle,
        message: copy.copySuccessMessage,
      });
    } catch {
      setToast({
        type: "error",
        title: copy.copyErrorTitle,
        message: copy.copyErrorMessage,
      });
    }
  };

  const handleRevokeConfirm = async () => {
    if (!tokenToRevoke) return;
    const targetToken = tokenToRevoke;
    const clientName = getMcpOAuthClientName(targetToken);
    setIsRevoking(true);
    try {
      await apiTokenService.destroy(targetToken.id);
      await mutate<IApiToken[]>(
        API_TOKENS_LIST,
        (prevData) => (prevData ?? []).filter((token) => token.id !== targetToken.id),
        false
      );
      setToast({
        type: "success",
        title: targetToken.is_active ? copy.revokeSuccessTitle : copy.removeSuccessTitle,
        message: targetToken.is_active ? copy.revokeSuccessMessage(clientName) : copy.removeSuccessMessage(clientName),
      });
      setTokenToRevoke(null);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : undefined;
      setToast({
        type: "error",
        title: copy.revokeErrorTitle,
        message: errorMessage ?? copy.revokeErrorMessage,
      });
    } finally {
      setIsRevoking(false);
    }
  };

  const handleClearExpiredConfirm = async () => {
    if (expiredTokens.length === 0) {
      setIsClearExpiredOpen(false);
      return;
    }

    setIsClearingExpired(true);
    try {
      const results = await Promise.allSettled(
        expiredTokens.map(async (token) => {
          await apiTokenService.destroy(token.id);
          return token.id;
        })
      );

      const deletedIds = new Set<string>();
      let failedCount = 0;
      for (const result of results) {
        if (result.status === "fulfilled") {
          deletedIds.add(result.value);
        } else {
          failedCount += 1;
        }
      }

      if (deletedIds.size > 0) {
        await mutate<IApiToken[]>(
          API_TOKENS_LIST,
          (prevData) => (prevData ?? []).filter((token) => !deletedIds.has(token.id)),
          failedCount > 0
        );
      }

      if (failedCount === 0) {
        setToast({
          type: "success",
          title: copy.clearExpiredSuccessTitle,
          message: copy.clearExpiredSuccessMessage(deletedIds.size),
        });
      } else {
        setToast({
          type: "error",
          title: copy.clearExpiredPartialErrorTitle,
          message: copy.clearExpiredPartialErrorMessage(failedCount),
        });
      }
      setIsClearExpiredOpen(false);
    } finally {
      setIsClearingExpired(false);
    }
  };

  const targetClientName = tokenToRevoke ? getMcpOAuthClientName(tokenToRevoke) : "";

  return (
    <section className="flex flex-col gap-4">
      <ConfirmDialog
        isOpen={tokenToRevoke !== null}
        handleClose={() => {
          if (!isRevoking) setTokenToRevoke(null);
        }}
        handleSubmit={handleRevokeConfirm}
        isSubmitting={isRevoking}
        title={tokenToRevoke?.is_active ? copy.revokeDialogTitle : copy.removeDialogTitle}
        content={
          tokenToRevoke?.is_active
            ? copy.revokeDialogDescription(targetClientName)
            : copy.removeDialogDescription(targetClientName)
        }
        primaryButtonText={
          tokenToRevoke?.is_active
            ? { default: copy.revoke, loading: copy.revoking }
            : { default: copy.remove, loading: copy.removing }
        }
      />
      <ConfirmDialog
        isOpen={isClearExpiredOpen}
        handleClose={() => {
          if (!isClearingExpired) setIsClearExpiredOpen(false);
        }}
        handleSubmit={handleClearExpiredConfirm}
        isSubmitting={isClearingExpired}
        title={copy.clearExpiredDialogTitle}
        content={copy.clearExpiredDialogDescription(expiredTokens.length)}
        primaryButtonText={{ default: copy.remove, loading: copy.removing }}
      />

      <ProfileSettingsHeading
        title={copy.headingTitle}
        description={copy.headingDescription}
        control={
          <div className="flex flex-wrap items-center gap-2">
            {activeTokens.length > 0 && (
              <Badge variant="success" size="sm" label={copy.activeCount(activeTokens.length)} />
            )}
            {expiredTokens.length > 0 && (
              <Button
                variant="secondary"
                size="sm"
                stretch="auto"
                label={copy.clearExpired(expiredTokens.length)}
                onClick={() => setIsClearExpiredOpen(true)}
              />
            )}
          </div>
        }
      />

      <div className="flex flex-col gap-3 rounded-lg border border-subtle bg-surface-2/60 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Icon icon={LinkOutline} size="sm" tint="secondary" />
            <span className="text-body-xs-medium text-primary">{copy.endpointTitle}</span>
          </div>
          <Badge variant="neutral" size="xs" label={copy.endpointBadge} />
        </div>
        <p className="text-caption-sm-regular text-tertiary">{copy.endpointHint}</p>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div
            className="font-mono flex min-w-0 flex-1 items-center rounded-md border border-subtle bg-surface-1 px-3 py-2 text-body-xs-regular text-primary select-all"
            title={mcpUrl}
          >
            <span className="truncate">{mcpUrl}</span>
          </div>
          <Button
            variant="primary"
            size="md"
            stretch="auto"
            icon={<Icon icon={copied ? TickOutline : CopyOutline} />}
            label={copied ? copy.copied : copy.copyUrl}
            onClick={() => void handleCopyUrl()}
          />
        </div>
      </div>

      {tokens.length === 0 ? (
        <p className="rounded-lg border border-dashed border-subtle bg-surface-1 px-4 py-6 text-center text-body-xs-regular text-tertiary">
          {copy.emptyState}
        </p>
      ) : (
        <div className="divide-y divide-subtle overflow-hidden rounded-lg border border-subtle bg-surface-1">
          {tokens.map((token) => {
            const clientName = getMcpOAuthClientName(token);
            return (
              <div
                key={token.id}
                className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-body-sm-medium text-primary">{clientName}</span>
                    <Badge
                      variant={token.is_active ? "success" : "warning"}
                      size="xs"
                      label={token.is_active ? t("common.active") : t("workspace_settings.settings.api_tokens.expired")}
                    />
                  </div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-caption-sm-regular text-tertiary">
                    <span>
                      {copy.createdLabel} {renderFormattedDate(token.created_at)}
                    </span>
                    {token.expired_at && (
                      <span>
                        {token.is_active ? copy.expiresLabel : copy.expiredOnLabel}{" "}
                        {renderFormattedDate(token.expired_at)}
                      </span>
                    )}
                    <span>
                      {copy.lastUsedLabel}:{" "}
                      {token.last_used
                        ? renderFormattedDate(token.last_used)
                        : t("workspace_settings.settings.api_tokens.not_used_yet")}
                    </span>
                  </div>
                </div>
                <div className="flex shrink-0 items-center justify-end">
                  <Button
                    variant={token.is_active ? "danger-outline" : "ghost"}
                    size="xs"
                    stretch="auto"
                    icon={<Icon icon={DeleteOutline} />}
                    label={token.is_active ? copy.revoke : copy.remove}
                    onClick={() => setTokenToRevoke(token)}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
