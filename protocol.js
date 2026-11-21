export const SERVICE = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
export const RX = '6e400002-b5a3-f393-e0a9-e50e24dcca9e';
export const TX = '6e400003-b5a3-f393-e0a9-e50e24dcca9e';

export const commands = {
  start: Uint8Array.of(1, 0, 0, 0, 0, 0, 0, 0, ...new TextEncoder().encode('Monitor')),
  device: Uint8Array.of(0x16, 3),
  battery: Uint8Array.of(0x14),
  next: Uint8Array.of(0x0a),
};

const decoder = new TextDecoder();
const text = bytes => decoder.decode(bytes).replace(/\0.*$/s, '').trim();
const hex = bytes => Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');

export function parsePacket(value) {
  const bytes = value instanceof Uint8Array
    ? value
    : new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  if (!bytes.length) throw new Error('Empty response from device.');
  const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const code = bytes[0];
  const requireLength = length => {
    if (bytes.length < length) throw new Error(`Incomplete device response (0x${code.toString(16)}).`);
  };
  if (code === 0x05) {
    requireLength(58);
    return { type: 'self', name: text(bytes.subarray(58)), frequency: data.getUint32(48, true) / 1000,
      bandwidth: data.getUint32(52, true) / 1000, spreadingFactor: bytes[56], codingRate: bytes[57] };
  }
  if (code === 0x0d) {
    requireLength(2);
    return { type: 'device', protocolVersion: bytes[1],
      model: bytes.length >= 60 ? text(bytes.subarray(20, 60)) : '',
      version: bytes.length >= 80 ? text(bytes.subarray(60, 80)) : '' };
  }
  if (code === 0x0c) {
    requireLength(3);
    return { type: 'battery', millivolts: data.getUint16(1, true) };
  }
  if ([0x07, 0x08, 0x10, 0x11].includes(code)) {
    const v3 = code === 0x10 || code === 0x11;
    const contact = code === 0x07 || code === 0x10;
    let offset = v3 ? 4 : 1;
    requireLength(offset + (contact ? 12 : 7));
    const sender = contact ? hex(bytes.subarray(offset, offset + 6)) : `Channel ${bytes[offset]}`;
    offset += contact ? 6 : 1;
    const path = bytes[offset++];
    const textType = bytes[offset++];
    const timestamp = data.getUint32(offset, true);
    offset += 4;
    if (contact && textType === 2) {
      requireLength(offset + 4);
      offset += 4;
    }
    return { type: 'message', sender, kind: contact ? 'Contact' : 'Channel', path, textType, timestamp,
      text: text(bytes.subarray(offset)), snr: v3 ? data.getInt8(1) / 4 : null };
  }
  if (code === 0x1b) {
    requireLength(9);
    requireLength(9 + bytes[8]);
    return { type: 'datagram', sender: `Channel ${bytes[4]}`, length: bytes[8], dataType: data.getUint16(6, true) };
  }
  if (code === 0x0a) return { type: 'empty' };
  if (code === 0x83) return { type: 'waiting' };
  if (code === 0x01) return { type: 'error', code: bytes[1] };
  return { type: 'other', code };
}
