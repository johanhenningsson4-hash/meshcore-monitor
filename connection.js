import { commands, parsePacket, SERVICE, RX, TX } from './protocol.js';

export class MeshConnection {
  constructor({ onPacket, onStatus, onError, timeout = 5000 }) {
    this.onPacket = onPacket;
    this.onStatus = onStatus;
    this.onError = onError;
    this.timeout = timeout;
    this.pending = null;
    this.closed = false;
    this.draining = false;
    this.drainAgain = false;
    this.notification = event => this.receive(event.target.value);
    this.disconnected = () => this.close('Device disconnected.');
  }

  async connect(bluetooth) {
    this.onStatus('connecting');
    try {
      this.device = await bluetooth.requestDevice({ filters: [{ services: [SERVICE] }] });
      this.device.addEventListener('gattserverdisconnected', this.disconnected);
      const server = await this.device.gatt.connect();
      const service = await server.getPrimaryService(SERVICE);
      this.rx = await service.getCharacteristic(RX);
      this.tx = await service.getCharacteristic(TX);
      this.tx.addEventListener('characteristicvaluechanged', this.notification);
      await this.tx.startNotifications();
      await this.request(commands.start, ['self']);
      await this.request(commands.device, ['device']);
      await this.request(commands.battery, ['battery']);
      this.onStatus('connected', this.device.name);
      this.poll = setInterval(() => this.refresh(), 30000);
      this.refresh();
    } catch (error) {
      this.close();
      throw error;
    }
  }

  request(command, expected) {
    if (this.closed || !this.rx) return Promise.reject(new Error('Device is disconnected.'));
    if (this.pending) return Promise.reject(new Error('A device request is already in progress.'));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending = null;
        reject(new Error('Device did not respond. Reconnect and try again.'));
      }, this.timeout);
      this.pending = { expected, resolve, reject, timer };
      Promise.resolve().then(() => this.rx.writeValueWithResponse
        ? this.rx.writeValueWithResponse(command)
        : this.rx.writeValue(command)).catch(error => {
        if (this.pending?.timer === timer) {
          clearTimeout(timer);
          this.pending = null;
          reject(error);
        }
      });
    });
  }

  receive(value) {
    let packet;
    try {
      packet = parsePacket(value);
    } catch (error) {
      this.fail(error);
      return;
    }
    if (packet.type === 'waiting') {
      this.drainAgain = true;
      if (!this.pending && !this.draining) this.refresh();
      return;
    }
    if (this.pending && (this.pending.expected.includes(packet.type) || packet.type === 'error')) {
      const pending = this.pending;
      clearTimeout(pending.timer);
      this.pending = null;
      if (packet.type === 'error') pending.reject(new Error(`Device rejected the request${packet.code === undefined ? '' : ` (code ${packet.code})`}.`));
      else {
        this.onPacket(packet);
        pending.resolve(packet);
      }
    }
  }

  async refresh() {
    if (this.closed) return;
    if (this.draining || this.pending) {
      this.drainAgain = true;
      return;
    }
    this.draining = true;
    try {
      await this.request(commands.battery, ['battery']);
      do {
        this.drainAgain = false;
        let packet;
        do {
          packet = await this.request(commands.next, ['message', 'datagram', 'empty']);
        } while (packet.type !== 'empty');
      } while (this.drainAgain);
    } catch (error) {
      if (!this.closed) this.fail(error);
    } finally {
      this.draining = false;
    }
  }

  fail(error) {
    this.onError(error);
    this.close('Monitoring stopped. Reconnect to try again.');
  }

  close(reason) {
    if (this.closed) return;
    this.closed = true;
    clearInterval(this.poll);
    if (this.pending) {
      clearTimeout(this.pending.timer);
      this.pending.reject(new Error(reason || 'Connection closed.'));
      this.pending = null;
    }
    this.tx?.removeEventListener('characteristicvaluechanged', this.notification);
    this.device?.removeEventListener('gattserverdisconnected', this.disconnected);
    if (this.device?.gatt.connected) this.device.gatt.disconnect();
    this.onStatus('disconnected', reason);
  }
}
