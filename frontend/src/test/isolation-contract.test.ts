import { describe, expect, it, vi } from "vitest";

describe.sequential("frontend test isolation contract", () => {
  it("allows a test to use browser storage and fake timers", () => {
    window.localStorage.setItem("test-local", "secret-local");
    window.sessionStorage.setItem("test-session", "secret-session");
    vi.useFakeTimers();

    expect(window.localStorage.getItem("test-local")).toBe("secret-local");
    expect(window.sessionStorage.getItem("test-session")).toBe("secret-session");
    expect(vi.isFakeTimers()).toBe(true);
  });

  it("starts the next test with clean storage and real timers", () => {
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(vi.isFakeTimers()).toBe(false);
  });
});
