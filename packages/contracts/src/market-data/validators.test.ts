/**
 * Market data validator tests.
 *
 * Driven by the same fixtures file as the Python suite
 * (packages/contracts/market-data/fixtures.json) so both validators stay
 * aligned. Covers price, volume, amount, suspended and adjustment samples.
 */

import { describe, expect, it } from "vitest";
import fixtures from "../../market-data/fixtures.json";
import {
  type AdjustmentFactor,
  type Bar,
  type CorporateAction,
  type Tick,
  validateAdjustmentFactor,
  validateBar,
  validateCorporateAction,
  validateTick,
} from "./validators";

interface NamedBar {
  name: string;
  bar: Bar;
}

interface InvalidBar extends NamedBar {
  reason: string;
}

interface NamedTick {
  name: string;
  tick: Tick;
}

interface InvalidTick extends NamedTick {
  reason: string;
}

interface NamedFactor {
  name: string;
  factor: AdjustmentFactor;
}

interface InvalidFactor extends NamedFactor {
  reason: string;
}

interface NamedAction {
  name: string;
  action: CorporateAction;
}

interface InvalidAction extends NamedAction {
  reason: string;
}

const data = fixtures as unknown as {
  bars: { valid: NamedBar[]; suspended: NamedBar[]; invalid: InvalidBar[] };
  ticks: { valid: NamedTick[]; invalid: InvalidTick[] };
  factors: { valid: NamedFactor[]; invalid: InvalidFactor[] };
  actions: { valid: NamedAction[]; invalid: InvalidAction[] };
};

describe("validateBar valid", () => {
  it.each(data.bars.valid.map((b) => [b.name, b] as const))("%s", (_name, fixture) => {
    const result = validateBar(fixture.bar);
    expect(result.valid).toBe(true);
    expect(result.errors).toEqual([]);
  });
});

describe("validateBar suspended", () => {
  it.each(data.bars.suspended.map((b) => [b.name, b] as const))("%s", (_name, fixture) => {
    const result = validateBar(fixture.bar);
    expect(result.valid).toBe(true);
    expect(result.errors).toEqual([]);
  });
});

describe("validateBar invalid", () => {
  it.each(data.bars.invalid.map((b) => [b.name, b] as const))("%s", (_name, fixture) => {
    const result = validateBar(fixture.bar);
    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThan(0);
  });
});

describe("validateTick valid", () => {
  it.each(data.ticks.valid.map((t) => [t.name, t] as const))("%s", (_name, fixture) => {
    const result = validateTick(fixture.tick);
    expect(result.valid).toBe(true);
    expect(result.errors).toEqual([]);
  });
});

describe("validateTick invalid", () => {
  it.each(data.ticks.invalid.map((t) => [t.name, t] as const))("%s", (_name, fixture) => {
    const result = validateTick(fixture.tick);
    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThan(0);
  });
});

describe("validateAdjustmentFactor valid", () => {
  it.each(data.factors.valid.map((f) => [f.name, f] as const))("%s", (_name, fixture) => {
    const result = validateAdjustmentFactor(fixture.factor);
    expect(result.valid).toBe(true);
    expect(result.errors).toEqual([]);
  });
});

describe("validateAdjustmentFactor invalid", () => {
  it.each(data.factors.invalid.map((f) => [f.name, f] as const))("%s", (_name, fixture) => {
    const result = validateAdjustmentFactor(fixture.factor);
    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThan(0);
  });
});

describe("validateCorporateAction valid", () => {
  it.each(data.actions.valid.map((a) => [a.name, a] as const))("%s", (_name, fixture) => {
    const result = validateCorporateAction(fixture.action);
    expect(result.valid).toBe(true);
    expect(result.errors).toEqual([]);
  });
});

describe("validateCorporateAction invalid", () => {
  it.each(data.actions.invalid.map((a) => [a.name, a] as const))("%s", (_name, fixture) => {
    const result = validateCorporateAction(fixture.action);
    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThan(0);
  });
});

describe("research vs trade price separation", () => {
  it("accepts both RAW and adjusted bars as long as priceType is explicit", () => {
    for (const fixture of data.bars.valid) {
      expect(["RAW", "FORWARD_ADJUSTED", "BACKWARD_ADJUSTED"]).toContain(fixture.bar.priceType);
    }
  });
});
