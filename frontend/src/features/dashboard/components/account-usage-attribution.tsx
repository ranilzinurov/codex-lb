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

const COLOR_CLASSES = [
  "bg-chart-1",
  "bg-chart-2",
  "bg-chart-3",
  "bg-chart-4",
  "bg-chart-5",
] as const;

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

function colorForItem(item: DashboardApiKeyAttributionEntry, index: number): string {
  if (item.bucket === "unattributed") {
    return "bg-amber-500";
  }

  const source = item.apiKeyId || item.keyPrefix || item.apiKeyName || String(index);
  let hash = 0;
  for (let i = 0; i < source.length; i += 1) {
    hash = (hash + source.charCodeAt(i) * (i + 1)) % COLOR_CLASSES.length;
  }
  return COLOR_CLASSES[hash];
}

function sortedItems(items: DashboardApiKeyAttributionEntry[]): DashboardApiKeyAttributionEntry[] {
  return [...items].sort((a, b) => {
    const shareDelta = (b.attributionSharePercent ?? 0) - (a.attributionSharePercent ?? 0);
    if (shareDelta !== 0) return shareDelta;
    return apiKeyLabel(a).localeCompare(apiKeyLabel(b));
  });
}

function hasApiKeyEntries(window: DashboardApiKeyAttributionWindow | null): boolean {
  return (window?.entries ?? []).some((item) => item.bucket === "api_key");
}

function AttributionWindow({
  title,
  window,
}: {
  title: string;
  window: DashboardApiKeyAttributionWindow | null;
}) {
  const blurred = usePrivacyStore((s) => s.blurred);
  const items = sortedItems(window?.entries ?? []);

  return (
    <div className="min-w-0 space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-semibold">{title}</h3>
        <p className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {formatNumber(window?.totalEstimatedUsedCredits)} credits used
        </p>
      </div>

      {items.length === 0 ? (
        <div className="rounded-md border border-dashed px-3 py-4 text-sm text-muted-foreground">
          No opted-in key usage in this quota window.
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((item, index) => {
            const account = accountLabel(item);
            const keyLabel = apiKeyLabel(item);
            const percent = Math.max(0, Math.min(100, item.attributionSharePercent ?? 0));
            const colorClass = colorForItem(item, index);
            const meta = [
              `${formatNumber(item.estimatedCredits)} credits`,
              `${formatCompactNumber(item.totalTokens)} tokens`,
              `${formatCompactNumber(item.requestCount)} req`,
              formatCurrency(item.totalCostUsd),
            ].join(" | ");

            return (
              <div
                key={`${window?.windowKey ?? title}-${item.accountId ?? "none"}-${item.apiKeyId ?? keyLabel}-${index}`}
                className="space-y-1.5"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <span className={cn("h-2 w-2 shrink-0 rounded-full", colorClass)} />
                      <KeyRound className="h-3 w-3 shrink-0 text-muted-foreground" />
                      <p className="truncate text-xs font-medium">{keyLabel}</p>
                      {item.keyPrefix && item.bucket !== "unattributed" ? (
                        <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                          {item.keyPrefix}
                        </span>
                      ) : null}
                      {item.isAttributionEstimated ? (
                        <span className="shrink-0 text-[10px] text-muted-foreground">est.</span>
                      ) : null}
                    </div>
                    <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                      <span className={blurred && account.isEmail ? "privacy-blur" : undefined}>
                        {account.label}
                      </span>
                      <span className="mx-1 text-muted-foreground/40">|</span>
                      <span className="tabular-nums">{meta}</span>
                    </p>
                  </div>
                  <span className="shrink-0 text-xs font-semibold tabular-nums">
                    {formatPercentNullable(item.attributionSharePercent)}
                  </span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className={cn("h-full rounded-full transition-all", colorClass)}
                    style={{ width: `${percent}%` }}
                  />
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
  if (!hasApiKeyEntries(primaryWindow) && !hasApiKeyEntries(secondaryWindow)) {
    return null;
  }

  return (
    <section className="space-y-3" data-testid="account-usage-attribution">
      <div className="flex items-center gap-3">
        <h2 className="text-[13px] font-medium uppercase tracking-wider text-muted-foreground">
          API Key Attribution
        </h2>
        <div className="h-px flex-1 bg-border" />
      </div>
      <div className="rounded-xl border bg-card p-4">
        <div className="grid gap-4 lg:grid-cols-2 lg:divide-x">
          <div className="min-w-0 lg:pr-4">
            <AttributionWindow title="5h current quota" window={primaryWindow} />
          </div>
          <div className="min-w-0 border-t pt-4 lg:border-t-0 lg:pl-4 lg:pt-0">
            <AttributionWindow title="Weekly current quota" window={secondaryWindow} />
          </div>
        </div>
      </div>
    </section>
  );
}
