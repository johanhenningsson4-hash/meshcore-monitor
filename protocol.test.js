import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parsePacket, commands } from './protocol.js';

test('parses device status and battery from byte views with offsets', () => {
  const self = new Uint8Array(64);
  self[0] = 5;
  const view = new DataView(self.buffer);
  view.setUint32(48, 869525, true);
  view.setUint32(52, 62500, true);
  self[56] = 8;
  self.set(new TextEncoder().encode('Node'), 58);
  assert.deepEqual(parsePacket(self), { type: 'self', name: 'Node', frequency: 869.525, bandwidth: 62.5, spreadingFactor: 8, codingRate: 0 });
  const buffer = Uint8Array.of(99, 12, 0x74, 0x0e, 99);
  assert.deepEqual(parsePacket(new DataView(buffer.buffer, 1, 3)), { type: 'battery', millivolts: 3700 });
  assert.deepEqual(Array.from(commands.device), [0x16, 3]);
});

test('parses legacy and v3 channel and contact messages', () => {
  const channel = Uint8Array.of(8, 2, 255, 0, 1, 0, 0, 0, ...new TextEncoder().encode('Alice: hello'));
  assert.deepEqual(parsePacket(channel), { type: 'message', sender: 'Channel 2', kind: 'Channel', path: 255, textType: 0, timestamp: 1, text: 'Alice: hello', snr: null });
  const contact = Uint8Array.of(0x10, 0xf6, 0, 0, 1, 2, 3, 4, 5, 6, 3, 2, 42, 0, 0, 0, 9, 8, 7, 6, ...new TextEncoder().encode('hello'));
  assert.deepEqual(parsePacket(contact), { type: 'message', sender: '010203040506', kind: 'Contact', path: 3, textType: 2, timestamp: 42, text: 'hello', snr: -2.5 });
  assert.equal(parsePacket(Uint8Array.of(0x11, 4, 0, 0, ...channel.slice(1))).text, 'Alice: hello');
  assert.equal(parsePacket(Uint8Array.of(7, ...contact.slice(4, 20), ...new TextEncoder().encode('test'))).text, 'test');
});

test('validates truncated packets and handles datagrams', () => {
  assert.throws(() => parsePacket(Uint8Array.of(8, 0)), /Incomplete/);
  assert.throws(() => parsePacket(Uint8Array.of(0x1b, 0, 0, 0, 1, 0, 1, 0, 3, 5)), /Incomplete/);
  assert.deepEqual(parsePacket(Uint8Array.of(0x1b, 0, 0, 0, 1, 0, 0xff, 0xff, 1, 5)), { type: 'datagram', sender: 'Channel 1', dataType: 65535, length: 1 });
});
