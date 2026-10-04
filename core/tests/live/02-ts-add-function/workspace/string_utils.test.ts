import assert from "node:assert/strict";
import { camelCase } from "./string_utils.ts";

assert.equal(camelCase("hello_world"), "helloWorld");
assert.equal(camelCase("background-color"), "backgroundColor");

console.log("TS-TESTS-OK");
