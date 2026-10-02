const assert = require("node:assert/strict");
const { truncateMiddle } = require("../build/truncate.js");

assert.equal(truncateMiddle("short", 8), "short");
assert.equal(truncateMiddle("abcdef", 6), "abcdef");
assert.equal(truncateMiddle("abcdef", 5), "ab…ef");
assert.equal(truncateMiddle("abcdef", 0), "");
assert.equal(truncateMiddle("abcdef", 1), "…");
assert.equal(truncateMiddle("abcdef", 2), "a…");
assert.equal(truncateMiddle("A😀BC", 3), "A…C");
assert.equal([...truncateMiddle("A😀BC", 3)].length, 3);
