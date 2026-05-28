import test from 'node:test';
import assert from 'node:assert/strict';

test('smoke', async () => {
  assert.equal(typeof process.version, 'string');
});
