import { test } from 'node:test';
import assert from 'node:assert/strict';
import { addStoredMessage, clearMessages, createExport, loadMessages, saveMessages } from './activity-store.js';

test('stores, restores and clears recent activity', () => {
  const values = new Map();
  const storage = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };
  const messages = addStoredMessage([], { type: 'message', sender: 'Channel 1', text: 'Hello' }, 123);

  saveMessages(messages, storage);
  assert.deepEqual(loadMessages(storage), messages);
  clearMessages(storage);
  assert.deepEqual(loadMessages(storage), []);
});

test('rejects malformed saved activity and limits retained messages', () => {
  const storage = {
    getItem: () => '{"not":"an array"}',
    setItem() {},
    removeItem() {},
  };
  assert.throws(() => loadMessages(storage), /invalid/);

  let messages = [];
  for (let index = 0; index < 550; index += 1) {
    messages = addStoredMessage(messages, { type: 'message', text: String(index) }, index);
  }
  assert.equal(messages.length, 500);
  assert.equal(messages[0].receivedAt, 549);
});

test('creates a readable JSON export with packet timestamps intact', () => {
  const messages = [{ receivedAt: 123, packet: { type: 'message', text: 'Hello' } }];
  const exported = JSON.parse(createExport(messages));

  assert.equal(exported.application, 'MeshCore Monitor');
  assert.deepEqual(exported.messages, messages);
  assert.ok(exported.exportedAt);
});
