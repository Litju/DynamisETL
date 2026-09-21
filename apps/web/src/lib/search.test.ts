import { describe, expect, it } from "vitest";

import {
  catalogSearchSchema,
  compareSearchSchema,
  labSearchSchema,
  labSearchToParams,
  normalizeLabSearch,
  parseSearch,
} from "@/lib/search";

describe("durable search parameter validation", () => {
  it("keeps a full deep link intact", () => {
    const parsed = parseSearch(labSearchSchema, {
      trial: "period-2",
      subject: "809166",
      stream: "tracking-period-1",
      metric: "pose.angular_rom.left_knee",
      result: "dm-pose-rom",
      t_ns: "2987480000000",
      from_ns: "0",
      to_ns: "10000000000",
      range_ns: "10000000000",
      view: "pose",
    });
    expect(parsed.trial).toBe("period-2");
    expect(parsed.subject).toBe("809166");
    expect(parsed.t_ns).toBe("2987480000000");
    expect(parsed.view).toBe("pose");
  });

  it("normalizes the router's numeric coercion back to decimal text", () => {
    // The router query decoder turns numeric-looking values into numbers before
    // validation; canonical time and subject identity must stay exact text.
    const parsed = parseSearch(labSearchSchema, {
      t_ns: 2987480000000,
      subject: 809166,
      trial: "period-1",
    });
    expect(parsed.t_ns).toBe("2987480000000");
    expect(parsed.subject).toBe("809166");
    expect(typeof parsed.t_ns).toBe("string");
  });

  it("normalizes every numeric subject identity at the root context seam", () => {
    for (const subject of [11897, 287934, 809166, 965697]) {
      expect(normalizeLabSearch({ subject }).subject).toBe(String(subject));
    }
  });

  it("drops invalid values instead of entering the state spine unchecked", () => {
    const parsed = parseSearch(labSearchSchema, {
      t_ns: "not-a-time",
      from_ns: "1.5e3",
      view: "cinema",
      unknown: "dropped",
    });
    expect(parsed.t_ns).toBeUndefined();
    expect(parsed.from_ns).toBeUndefined();
    expect(parsed.view).toBe("overview");
    expect("unknown" in parsed).toBe(false);
  });

  it("accepts signed canonical time from an event-aligned trial", () => {
    // White CMJ trials are takeoff-aligned and run up to zero from a negative
    // time; the durable playhead and range must survive that.
    const parsed = parseSearch(labSearchSchema, {
      t_ns: "-1345000000",
      from_ns: -1_345_000_000,
      to_ns: "0",
    });
    expect(parsed.t_ns).toBe("-1345000000");
    expect(parsed.from_ns).toBe("-1345000000");
    expect(parsed.to_ns).toBe("0");
  });

  it("fails closed on an unsafe nanosecond integer", () => {
    const parsed = parseSearch(labSearchSchema, { t_ns: Number.MAX_SAFE_INTEGER + 10 });
    expect(parsed.t_ns).toBeUndefined();
  });

  it("treats an unparseable search object as empty", () => {
    expect(parseSearch(labSearchSchema, {})).toEqual({ view: "overview" });
    const catalog = parseSearch(catalogSearchSchema, { rights: "bogus", modality: "laser" });
    expect(catalog.rights).toBe("all");
    expect(catalog.modality).toBeUndefined();
    expect(parseSearch(compareSearchSchema, { view: "cinema" }).view).toBe("signals");
  });

  it("serializes only non-empty durable context", () => {
    const params = labSearchToParams({
      trial: "period_1",
      subject: undefined,
      view: "signals",
    });
    expect(params).toEqual({ trial: "period_1", view: "signals" });
  });
});
