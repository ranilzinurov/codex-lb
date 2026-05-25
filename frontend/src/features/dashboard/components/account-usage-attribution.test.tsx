import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AccountUsageAttribution } from "@/features/dashboard/components/account-usage-attribution";
import type {
  DashboardApiKeyAttributionEntry,
  DashboardApiKeyAttributionWindow,
} from "@/features/dashboard/schemas";

function attribution(overrides: Partial<DashboardApiKeyAttributionEntry> = {}): DashboardApiKeyAttributionEntry {
  return {
    bucket: "api_key",
    accountId: "acc-1",
    accountEmail: "one@example.com",
    accountDisplayLabel: "One Account",
    apiKeyId: "key-1",
    apiKeyName: "Production",
    keyPrefix: "sk-prod",
    requestCount: 120,
    totalTokens: 24000,
    cachedInputTokens: 200,
    totalCostUsd: 1.25,
    estimatedCredits: 42,
    attributionSharePercent: 64,
    isAttributionEstimated: false,
    ...overrides,
  };
}

function window(
  windowKey: "primary" | "secondary",
  entries: DashboardApiKeyAttributionEntry[],
): DashboardApiKeyAttributionWindow {
  return {
    windowKey,
    windowMinutes: windowKey === "primary" ? 300 : 10080,
    totalEstimatedUsedCredits: 42,
    entries,
  };
}

describe("AccountUsageAttribution", () => {
  it("renders nothing when attribution is absent", () => {
    const { container } = render(<AccountUsageAttribution primaryWindow={null} secondaryWindow={null} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders primary and secondary API key attribution rows", () => {
    render(
      <AccountUsageAttribution
        primaryWindow={window("primary", [attribution()])}
        secondaryWindow={window("secondary", [
          attribution({
            bucket: "unattributed",
            accountEmail: null,
            apiKeyId: null,
            apiKeyName: null,
            keyPrefix: null,
            requestCount: 3,
            totalTokens: 900,
            totalCostUsd: null,
            estimatedCredits: null,
            attributionSharePercent: null,
          }),
        ])}
      />,
    );

    expect(screen.getByTestId("account-usage-attribution")).toBeInTheDocument();
    expect(screen.getByText("API Key Attribution")).toBeInTheDocument();
    expect(screen.getByText("5h current quota")).toBeInTheDocument();
    expect(screen.getByText("Weekly current quota")).toBeInTheDocument();
    expect(screen.getByText("Production")).toBeInTheDocument();
    expect(screen.getAllByText("One Account").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Unattributed").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("64%")).toBeInTheDocument();
    expect(screen.getByText(/24K tokens/)).toBeInTheDocument();
    expect(screen.getByText(/\$1.25/)).toBeInTheDocument();
  });

  it("marks estimated rows", () => {
    render(
      <AccountUsageAttribution
        primaryWindow={window("primary", [attribution({ isAttributionEstimated: true })])}
        secondaryWindow={null}
      />,
    );

    expect(screen.getByText("est.")).toBeInTheDocument();
  });

  it("hides when no API keys are opted in", () => {
    const { container } = render(
      <AccountUsageAttribution
        primaryWindow={window("primary", [
          attribution({
            bucket: "unattributed",
            apiKeyId: null,
            apiKeyName: null,
            keyPrefix: null,
          }),
        ])}
        secondaryWindow={null}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
