const MAX_ACCOUNT_NAME_LENGTH = 80;
const MAX_INITIAL_CAPITAL_LENGTH = 32;
const POSITIVE_DECIMAL = /^(?:0\.\d*[1-9]\d*|[1-9]\d*(?:\.\d+)?)$/;

export function validatePaperTerminalCreateInput(
  name: string,
  initialCapital: string,
): string | null {
  if (name.trim().length === 0) return "请输入账户名称。";
  if (name.length > MAX_ACCOUNT_NAME_LENGTH) return "账户名称不能超过 80 个字符。";
  if (
    initialCapital.length > MAX_INITIAL_CAPITAL_LENGTH ||
    !POSITIVE_DECIMAL.test(initialCapital)
  ) {
    return "请输入 32 个字符以内的正数金额。";
  }
  return null;
}
