import { describe, expect, it } from "vitest";

import { formatPercent, formatSeconds } from "@/lib/duration";

describe("formatSeconds", () => {
  it("writes short spans in seconds and longer ones in minutes and hours", () => {
    expect(formatSeconds(0)).toBe("0 s");
    expect(formatSeconds(45)).toBe("45 s");
    expect(formatSeconds(60)).toBe("1 min");
    expect(formatSeconds(125)).toBe("2 min 5 s");
    expect(formatSeconds(3600)).toBe("1 h");
    expect(formatSeconds(3780)).toBe("1 h 3 min");
  });

  it("rounds, and says n/a instead of inventing a value", () => {
    expect(formatSeconds(44.6)).toBe("45 s");
    expect(formatSeconds(null)).toBe("n/a");
    expect(formatSeconds(-1)).toBe("n/a");
    expect(formatSeconds(Number.NaN)).toBe("n/a");
  });
});

describe("formatPercent", () => {
  it("shows whole percentages and n/a when there was nothing to measure", () => {
    expect(formatPercent(0.6667)).toBe("67%");
    expect(formatPercent(1)).toBe("100%");
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(null)).toBe("n/a");
  });
});
