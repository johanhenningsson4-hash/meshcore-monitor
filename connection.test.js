import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MeshConnection } from './connection.js';

function fakeDevice(replies) {
  const tx = new EventTarget();
  tx.startNotifications = async () => tx;
  const writes = [];
  const rx = {
    async writeValueWithResponse(command) {
      writes.push(command[0]);
      const reply = replies.shift();
      if (reply) {
        tx.value = new DataView(Uint8Array.from(reply).buffer);
        tx.dispatchEvent(new Event('characteristicvaluechanged'));
      }
    },
  };
  const device = new EventTarget();
  device.name = 'Test radio';
  device.gatt = {
    connected: false,
    async connect() {
      this.connected = true;
      return { getPrimaryService: async () => ({ getCharacteristic: async uuid => uuid.includes('0002') ? rx : tx }) };
    },
    disconnect() { this.connected = false; },
  };
  return { bluetooth: { requestDevice: async () => device }, device, tx, writes };
}

const self = [5, ...new Array(57).fill(0)];
const battery = [12, 0x74, 0x0e];

test('initializes in order, drains the queue and handles waiting notifications', async () => {
  const mock = fakeDevice([self, [13, 3], battery, battery, [8, 1, 0xff, 0, 1, 0, 0, 0, 72, 105], [10], battery, [10]]);
  const packets = [];
  const statuses = [];
  const connection = new MeshConnection({ onPacket: p => packets.push(p), onStatus: s => statuses.push(s), onError: error => { throw error; } });
  await connection.connect(mock.bluetooth);
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.deepEqual(mock.writes, [1, 0x16, 0x14, 0x14, 0x0a, 0x0a]);
  assert.equal(packets.find(p => p.type === 'message').text, 'Hi');
  mock.tx.value = new DataView(Uint8Array.of(0x83).buffer);
  mock.tx.dispatchEvent(new Event('characteristicvaluechanged'));
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.deepEqual(mock.writes.slice(-2), [0x14, 0x0a]);
  connection.close();
  assert.deepEqual(statuses, ['connecting', 'connected', 'disconnected']);
  assert.equal(mock.device.gatt.connected, false);
});

test('times out and disconnects rather than continuing with an ambiguous response', async () => {
  const mock = fakeDevice([self]);
  const connection = new MeshConnection({ onPacket() {}, onStatus() {}, onError() {}, timeout: 10 });
  await assert.rejects(connection.connect(mock.bluetooth), /did not respond/);
  assert.equal(mock.device.gatt.connected, false);
  assert.deepEqual(mock.writes, [1, 0x16]);
});

test('surfaces a malformed packet and disconnects', async () => {
  const mock = fakeDevice([[5]]);
  const errors = [];
  const connection = new MeshConnection({ onPacket() {}, onStatus() {}, onError: e => errors.push(e.message) });
  await assert.rejects(connection.connect(mock.bluetooth));
  assert.match(errors[0], /Incomplete/);
  assert.equal(mock.device.gatt.connected, false);
});

test('reconnects to an authorized device after an unexpected disconnect', async () => {
  const mock = fakeDevice([self, [13, 3], battery, battery, [10], self, [13, 3], battery, battery, [10]]);
  const statuses = [];
  const connection = new MeshConnection({
    onPacket() {},
    onStatus: (status, detail) => statuses.push([status, detail]),
    onError: error => { throw error; },
    retryDelay: 1,
    maxReconnectAttempts: 2,
  });
  await connection.connect(mock.bluetooth);
  await new Promise(resolve => setTimeout(resolve, 10));

  mock.device.gatt.connected = false;
  mock.device.dispatchEvent(new Event('gattserverdisconnected'));
  await new Promise(resolve => setTimeout(resolve, 20));

  assert.deepEqual(statuses.map(status => status[0]), ['connecting', 'connected', 'connecting', 'connected']);
  assert.equal(statuses[2][1], 'Device disconnected. Reconnecting…');
  assert.equal(mock.device.gatt.connected, true);
  connection.close();
});
