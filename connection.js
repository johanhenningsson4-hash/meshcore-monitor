import { commands, parsePacket, SERVICE, RX, TX } from './protocol.js';

export class MeshConnection {
  constructor({
    onPacket,
    onStatus,
    onError,
    timeout = 5000,
    retryDelay = 1000,
    maxReconnectAttempts = 5,
  }) {
    this.onPacket = onPacket;
    this.onStatus = onStatus;
    this.onError = onError;
    this.timeout = timeout;
    this.retryDelay = retryDelay;
    this.maxReconnectAttempts = maxReconnectAttempts;
    this.pending = null;
    this.closed = false;
    this.draining = false;
    this.drainAgain = false;
    this.reconnecting = false;
    this.reconnectAttempts = 0;
    this.notification = event => this.receive(event.target.value);
    this.disconnected = () => this.handleDisconnect();
  }

  async connect(bluetooth) {
    this.onStatus('connecting');
    try {
      this.device = await bluetooth.requestDevice({ filters: [{ services: [SERVICE] }] });
      this.device.addEventListener('gattserverdisconnected', this.disconnected);
      await this.openDevice();
    } catch (error) {
      this.close();
      throw error;
    }
  }

  async openDevice() {
    const server = await this.device.gatt.connect();
    const service = await server.getPrimaryService(SERVICE);
    this.rx = await service.getCharacteristic(RX);
    this.tx = await service.getCharacteristic(TX);
    this.tx.addEventListener('characteristicvaluechanged', this.notification);
    await this.tx.startNotifications();
    await this.request(commands.start, ['self']);
    await this.request(commands.device, ['device']);
    await this.request(commands.battery, ['battery']);
    this.reconnecting = false;
    this.reconnectAttempts = 0;
    this.onStatus('connected', this.device.name || 'Companion radio connected');
    clearInterval(this.poll);
    this.poll = setInterval(() => this.refresh(), 30000);
    this.refresh();
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
    if (this.reconnecting) return;
    this.onError(error);
    this.close('Monitoring stopped. Reconnect to try again.');
  }

  handleDisconnect() {
    if (this.closed || this.reconnecting) return;
    this.reconnecting = true;
    this.resetTransport();
    this.onStatus('connecting', 'Device disconnected. Reconnecting…');
    this.scheduleReconnect();
  }

  scheduleReconnect() {
    const delay = this.retryDelay * (2 ** this.reconnectAttempts);
    this.reconnectTimer = setTimeout(() => this.reconnect(), delay);
  }

  async reconnect() {
    if (this.closed) return;
    try {
      await this.openDevice();
    } catch (error) {
      this.resetTransport();
      this.reconnectAttempts += 1;
      if (this.reconnectAttempts >= this.maxReconnectAttempts) {
        const message = `Could not reconnect after ${this.maxReconnectAttempts} attempts: ${error.message}`;
        this.onError(new Error(message));
        this.close('Device disconnected. Select it to reconnect.');
        return;
      }
      this.scheduleReconnect();
    }
  }

  resetTransport() {
    clearInterval(this.poll);
    this.poll = null;
    if (this.pending) {
      clearTimeout(this.pending.timer);
      this.pending.reject(new Error('Device disconnected during the request.'));
      this.pending = null;
    }
    this.tx?.removeEventListener('characteristicvaluechanged', this.notification);
    this.rx = null;
    this.tx = null;
    this.draining = false;
  }

  close(reason) {
    if (this.closed) return;
    this.closed = true;
    clearTimeout(this.reconnectTimer);
    this.resetTransport();
    if (this.pending) this.pending.reject(new Error(reason || 'Connection closed.'));
    this.device?.removeEventListener('gattserverdisconnected', this.disconnected);
    if (this.device?.gatt.connected) this.device.gatt.disconnect();
    this.onStatus('disconnected', reason);
  }
}
