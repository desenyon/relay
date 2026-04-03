import { describe, expect, it } from "@jest/globals";
import { RelayError } from "../src/errors.js";
import { TypeTag } from "../src/types.js";

describe("relay-js smoke", () => {
  it("exports TypeTag constants", () => {
    expect(TypeTag.STRING).toBe(0x0d);
  });

  it("RelayError carries code", () => {
    const e = new RelayError("msg", { code: "E001" });
    expect(e.code).toBe("E001");
    expect(e.message).toBe("msg");
  });
});
