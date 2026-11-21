import { MeshConnection } from './connection.js';

const $ = id => document.getElementById(id);
let connection;
let count = 0;

function showNotice(message, error = false) {
  $('notice').classList.toggle('error', error);
  $('notice').lastElementChild.textContent = message;
}

const queueNotice = 'Connecting reads and removes queued messages from your device. They stay in this page only and may not reach another companion app.';

function setStatus(status, detail) {
  const connected = status === 'connected';
  $('status').textContent = status === 'connecting' ? 'Connecting…' : connected ? 'Connected' : 'Disconnected';
  $('status-dot').classList.toggle('online', connected);
  $('connection-detail').textContent = connected ? (detail || 'Companion radio connected') : (detail || 'Connect a companion radio to get started.');
  $('connection-footer').textContent = connected ? 'ONLINE' : 'OFFLINE';
  $('feed-status').lastChild.textContent = connected ? ' LISTENING' : ' WAITING FOR CONNECTION';
  $('feed-status').classList.toggle('online-text', connected);
  $('connect').disabled = status === 'connecting';
  $('connect').textContent = connected ? 'Disconnect' : status === 'connecting' ? 'Connecting…' : 'ᛒ  Connect device ↗';
}

function clearFeed() {
  $('messages').replaceChildren();
  $('empty').hidden = false;
  count = 0;
  $('message-count').textContent = '0';
}

function resetDevice() {
  $('battery').replaceChildren(document.createTextNode('— '), unit('V'));
  $('battery-detail').textContent = 'Waiting for device data';
  $('frequency').replaceChildren(document.createTextNode('— '), unit('MHz'));
  $('radio-detail').textContent = 'Waiting for device data';
  $('firmware').textContent = '—';
  clearFeed();
}

function unit(label) {
  const element = document.createElement('small');
  element.textContent = label;
  return element;
}

function addMessage(packet) {
  const item = document.createElement('li');
  const header = document.createElement('div');
  header.className = 'message-header';
  const sender = document.createElement('strong');
  sender.textContent = packet.kind === 'Contact' ? `Contact ${packet.sender}` : packet.sender;
  const time = document.createElement('time');
  if (packet.timestamp) {
    const date = new Date(packet.timestamp * 1000);
    time.dateTime = date.toISOString();
    time.textContent = date.toLocaleString();
  } else {
    time.textContent = 'Time unavailable';
  }
  header.append(sender, time);
  const body = document.createElement('p');
  body.textContent = packet.type === 'datagram'
    ? `Binary datagram · type 0x${packet.dataType.toString(16).padStart(4, '0')} · ${packet.length} bytes`
    : packet.text || '(Empty message)';
  const meta = document.createElement('div');
  meta.className = 'message-meta';
  meta.textContent = packet.type === 'datagram' ? 'CHANNEL DATA' :
    `${packet.kind.toUpperCase()}${packet.snr === null ? '' : ` · SNR ${packet.snr} dB`}${packet.textType ? ` · TEXT TYPE ${packet.textType}` : ''}`;
  item.append(header, body, meta);
  $('messages').prepend(item);
  $('empty').hidden = true;
  $('message-count').textContent = String(++count);
}

function onPacket(packet) {
  if (packet.type === 'self') {
    $('frequency').replaceChildren(document.createTextNode(`${packet.frequency.toFixed(3)} `), unit('MHz'));
    $('radio-detail').textContent = `${packet.name || 'Companion radio'} · SF${packet.spreadingFactor} / ${packet.bandwidth} kHz`;
  } else if (packet.type === 'device') {
    $('firmware').textContent = packet.version || `PROTOCOL V${packet.protocolVersion}`;
    if (packet.model) $('connection-detail').textContent = packet.model;
  } else if (packet.type === 'battery') {
    $('battery').replaceChildren(document.createTextNode(packet.millivolts ? `${(packet.millivolts / 1000).toFixed(2)} ` : '— '), unit('V'));
    $('battery-detail').textContent = packet.millivolts ? 'Reported by your radio' : 'Battery reading unavailable';
  } else if (packet.type === 'message' || packet.type === 'datagram') {
    addMessage(packet);
  }
}

$('connect').addEventListener('click', async () => {
  if (connection && !connection.closed) {
    connection.close('Disconnected by you.');
    return;
  }
  if (!navigator.bluetooth) {
    showNotice('Web Bluetooth is unavailable. Use a supported browser on HTTPS or localhost with Bluetooth enabled.', true);
    return;
  }
  resetDevice();
  showNotice(queueNotice);
  connection = new MeshConnection({
    onPacket,
    onStatus: setStatus,
    onError: error => showNotice(error.message, true),
  });
  try {
    await connection.connect(navigator.bluetooth);
  } catch (error) {
    showNotice(error.name === 'NotFoundError' ? 'No device was selected. Try connecting again.' : `Could not connect: ${error.message}`, true);
  }
});

$('clear').addEventListener('click', clearFeed);
