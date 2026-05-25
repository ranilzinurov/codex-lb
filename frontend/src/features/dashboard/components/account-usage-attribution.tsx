import { KeyRound } from "lucide-react";

import type {
  DashboardApiKeyAttributionEntry,
  DashboardApiKeyAttributionWindow,
} from "@/features/dashboard/schemas";
import { usePrivacyStore } from "@/hooks/use-privacy";
import { cn } from "@/lib/utils";
import {
  formatCompactNumber,
  formatCurrency,
  formatNumber,
  formatPercentNullable,
} from "@/utils/formatters";

export type AccountUsageAttributionProps = {
  primaryWindow: DashboardApiKeyAttributionWindow | null;
  secondaryWindow: DashboardApiKeyAttributionWindow | null;
};

function accountLabel(item: DashboardApiKeyAttributionEntry): { label: string; isEmail: boolean } {
  const label = item.accountDisplayLabel || item.accountEmail || item.accountId || "Unknown account";
  return {
    label,
    isEmail: !!item.accountEmail && label === item.accountEmail,
  };
}

function apiKeyLabel(item: DashboardApiKeyAttributionEntry): string {
  if (item.bucket === "unattributed" || (!item.apiKeyId && !item.apiKeyName && !item.keyPrefix)) {
    return "Unattributed";
  }
  return item.apiKeyName || item.keyPrefix || item.apiKeyId || "Unknown key";
}

function sortedItems(items: DashboardApiKeyAttributionEntry[]): DashboardApiKeyAttributionEntry[] {
  return [...items].sort((a, b) => (b.attributionSharePercent ?? 0) - (a.attributionSharePercent ?? 0));
}

function AttributionWindow({
  title,
  window,
}: {
  title: string;
  window: DashboardApiKeyAttributionWindow | null;
}) {
  const blurred = usePrivacyStore((s) => s.blurred);
  const visibleItems = sortedItems(window?.entries ?? []);

  return (
    <div className="rounded-xl border bg-card">
      <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">{title}</h3>
          <p className="text-xs text-muted-foreground">
            {visibleItems.length > 0
              ? `${formatNumber(window?.totalEstimatedUsedCredits)} estimated credits`
              : "No attribution rows"}
          </p>
        </div>
      </div>
      {visibleItems.length === 0 ? (
        <div className="px-4 py-6 text-sm text-muted-foreground">No usage attributed in this window.</div>
      ) : (
        <div className="divide-y">
          {visibleItems.map((item, index) => {
            const account = accountLabel(item);
            const keyLabel = apiKeyLabel(item);
            const marker =
              item.bucket === "unattributed"
                ? "Unattributed"
                : item.isAttributionEstimated
                  ? "Estimated"
                  : null;

            return (
              <div
                key={`${window?.windowKey ?? title}-${item.accountId ?? "none"}-${item.apiKeyId ?? keyLabel}-${index}`}
                className="grid gap-3 px-4 py-3 md:grid-cols-[minmax(0,1.6fr)_minmax(8rem,0.7fr)_minmax(8rem,0.7fr)] md:items-center"
              >
                <div className="min-w-0">
                  <div className="flex min-w-0 items-center gap-2">
                    <KeyRound className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <p className="truncate text-sm font-medium">{keyLabel}</p>
                    {item.keyPrefix && item.bucket !== "unattributed" ? (
                      <span className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        {item.keyPrefix}
                      </span>
                    ) : null}
                    {marker ? (
                      <span
                        className={cn(
                          "shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-medium",
                          item.bucket === "unattributed"
                            ? "bg-amber-500/10 text-amber-700 dark:text-amber-300"
                            : "bg-blue-500/10 text-blue-700 dark:text-blue-300",
                        )}
                      >
                        {marker}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    <span className={blurred && account.isEmail ? "privacy-blur" : undefined}>
                      {account.label}
                    </span>
                  </p>
                </div>

                <div>
                  <p className="text-xs text-muted-foreground">Credits</p>
                  <p className="text-sm font-semibold tabular-nums">
                    {formatNumber(item.estimatedCredits)}
                    <span className="ml-2 text-xs font-normal text-muted-foreground">
                      {formatPercentNullable(item.attributionSharePercent)}
                    </span>
                  </p>
                </div>

                <div className="grid grid-cols-3 gap-3 text-xs md:block md:space-y-1">
                  <div>
                    <p className="text-muted-foreground">Requests</p>
                    <p className="font-medium tabular-nums">{formatCompactNumber(item.requestCount)}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Tokens</p>
                    <p className="font-medium tabular-nums">{formatCompactNumber(item.totalTokens)}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Cost</p>
                    <p className="font-medium tabular-nums">{formatCurrency(item.totalCostUsd)}</p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function AccountUsageAttribution({
  primaryWindow,
  secondaryWindow,
}: AccountUsageAttributionProps) {
  if ((primaryWindow?.entries.length ?? 0) === 0 && (secondaryWindow?.entries.length ?? 0) === 0) {
    return null;
  }

  return (
    <section className="space-y-4" data-testid="account-usage-attribution">
      <div className="flex items-center gap-3">
        <h2 className="text-[13px] font-medium uppercase tracking-wider text-muted-foreground">
          API Key Attribution
        </h2>
        <div className="h-px flex-1 bg-border" />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <AttributionWindow title="5-hour usage" window={primaryWindow} />
        <AttributionWindow title="Weekly usage" window={secondaryWindow} />
      </div>
    </section>
  );
}
