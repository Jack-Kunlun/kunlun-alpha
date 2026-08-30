import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const schema = JSON.parse(
  readFileSync("schemas/alerts/in-app-notification-center.json", "utf8"),
) as {
  additionalProperties: boolean;
  required: string[];
  properties: Record<string, unknown>;
  $defs: Record<string, { required?: string[]; properties?: Record<string, unknown> }>;
};

describe("in-app notification center schema", () => {
  it("is closed and exposes delivery evidence plus persistent read state", () => {
    expect(schema.additionalProperties).toBe(false);
    expect(schema.required).toEqual(
      expect.arrayContaining(["generatedAt", "unreadCount", "notifications", "dataMeaning"]),
    );
    expect(schema.$defs.InAppNotification?.required).toEqual(
      expect.arrayContaining([
        "notificationId",
        "historyId",
        "instrumentId",
        "deliveryStatus",
        "deliveryAttempts",
        "readAt",
      ]),
    );
    expect(schema.properties).not.toHaveProperty("broker");
    expect(schema.properties).not.toHaveProperty("order");
  });
});
