const assert = require("node:assert/strict");
const { isBetween } = require("../build/range.js");

assert.equal(isBetween(5, 1, 10), true);
assert.equal(isBetween(0, 1, 10), false);
assert.equal(isBetween(1, 1, 10), true, "lower boundary is inclusive");
assert.equal(isBetween(10, 1, 10), true, "upper boundary is inclusive");
assert.equal(isBetween(5, 10, 1), false, "reversed range is empty");
