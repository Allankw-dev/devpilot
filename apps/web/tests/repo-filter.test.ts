import { describe, expect, it } from "vitest";

import { filterRepos, hasFilters, languagesOf, NO_FILTERS, pageCount, paginate, parseTab } from "@/lib/repo-filter";
import { repo } from "./helpers";

const web = repo({ id: "1", full_name: "acme/web", description: "Customer portal", language: "TypeScript", ci: "passing" });
const api = repo({ id: "2", full_name: "acme/api", description: null, language: "Python", ci: "failing" });
const old = repo({ id: "3", full_name: "acme/old-site", language: "PHP", archived: true, ci: "none" });
const none = repo({ id: "4", full_name: "acme/notes", language: null });
const all = [web, api, old, none];

describe("filterRepos", () => {
  it("hides archived repositories until asked", () => {
    expect(filterRepos(all, NO_FILTERS).map((r) => r.id)).toEqual(["1", "2", "4"]);
    expect(filterRepos(all, { ...NO_FILTERS, showArchived: true })).toHaveLength(4);
  });

  it("searches the name and the description, ignoring case and spaces around", () => {
    expect(filterRepos(all, { ...NO_FILTERS, q: "  PORTAL " }).map((r) => r.id)).toEqual(["1"]);
    expect(filterRepos(all, { ...NO_FILTERS, q: "acme/a" }).map((r) => r.id)).toEqual(["2"]);
    expect(filterRepos(all, { ...NO_FILTERS, q: "zzz" })).toEqual([]);
  });

  it("filters by language and by CI state, and combines filters", () => {
    expect(filterRepos(all, { ...NO_FILTERS, language: "Python" }).map((r) => r.id)).toEqual(["2"]);
    expect(filterRepos(all, { ...NO_FILTERS, ci: "failing" }).map((r) => r.id)).toEqual(["2"]);
    expect(filterRepos(all, { ...NO_FILTERS, language: "Python", ci: "passing" })).toEqual([]);
  });

  it("knows whether any filter is on", () => {
    expect(hasFilters(NO_FILTERS)).toBe(false);
    expect(hasFilters({ ...NO_FILTERS, q: "  " })).toBe(false);
    expect(hasFilters({ ...NO_FILTERS, q: "x" })).toBe(true);
    expect(hasFilters({ ...NO_FILTERS, showArchived: true })).toBe(true);
  });
});

describe("languagesOf", () => {
  it("lists each language once, sorted, skipping repositories without one", () => {
    expect(languagesOf([...all, repo({ language: "Python" })])).toEqual(["PHP", "Python", "TypeScript"]);
    expect(languagesOf([])).toEqual([]);
  });
});

describe("pagination", () => {
  const items = Array.from({ length: 25 }, (_, i) => i + 1);

  it("counts at least one page", () => {
    expect(pageCount(0, 10)).toBe(1);
    expect(pageCount(10, 10)).toBe(1);
    expect(pageCount(11, 10)).toBe(2);
  });

  it("returns the rows of a page", () => {
    expect(paginate(items, 1, 10).rows).toHaveLength(10);
    expect(paginate(items, 3, 10)).toEqual({ rows: [21, 22, 23, 24, 25], page: 3, pages: 3 });
  });

  it("clamps a page that no longer exists, for example after filtering", () => {
    expect(paginate(items, 9, 10).page).toBe(3);
    expect(paginate(items, 0, 10).page).toBe(1);
    expect(paginate([], 4, 10)).toEqual({ rows: [], page: 1, pages: 1 });
  });
});

describe("parseTab", () => {
  const tabs = ["overview", "commits"] as const;
  it("accepts known tabs and falls back for anything else", () => {
    expect(parseTab("commits", tabs, "overview")).toBe("commits");
    expect(parseTab("bogus", tabs, "overview")).toBe("overview");
    expect(parseTab(null, tabs, "overview")).toBe("overview");
  });
});
