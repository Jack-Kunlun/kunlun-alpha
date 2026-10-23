import { describe, expect, it } from "vitest";
import { validatePaperTerminalCreateInput } from "./paper-terminal-form";

describe("validatePaperTerminalCreateInput", () => {
  it.each(["", "   ", " \n\t "])("rejects a blank account name %j", (name) => {
    expect(validatePaperTerminalCreateInput(name, "100000")).toBe("请输入账户名称。");
  });

  it("rejects account names longer than the server limit", () => {
    expect(validatePaperTerminalCreateInput("a".repeat(81), "100000")).toBe(
      "账户名称不能超过 80 个字符。",
    );
  });

  it.each(["0", "0.00", "-1", "+1", "1e3", "1."])(
    "rejects a non-positive-decimal initial amount %j",
    (initialCapital) => {
      expect(validatePaperTerminalCreateInput("本地账户", initialCapital)).toBe(
        "请输入 32 个字符以内的正数金额。",
      );
    },
  );

  it("rejects initial amounts longer than the server limit", () => {
    expect(validatePaperTerminalCreateInput("本地账户", "1".repeat(33))).toBe(
      "请输入 32 个字符以内的正数金额。",
    );
  });

  it("accepts positive decimal strings, including the exact server limit", () => {
    expect(validatePaperTerminalCreateInput(" 本地账户 ", "123456789012345678901.1234567890")).toBe(
      null,
    );
    expect(validatePaperTerminalCreateInput("a".repeat(80), "1.0")).toBe(null);
    expect(validatePaperTerminalCreateInput("本地账户", "0.0000001")).toBe(null);
  });
});
