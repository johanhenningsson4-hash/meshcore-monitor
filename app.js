import { MeshConnection } from './connection.js';
import { addStoredMessage, clearMessages, createExport, loadMessages, saveMessages } from './activity-store.js';

const $ = id => document.getElementById(id);
let connection;
let activity = [];

function showNotice(message, error = false) {
  $('notice').classList.toggle('error', error);
  $('notice').lastElementChild.textContent = message;
}

const queueNotice = 'Connecting reads and removes queued messages from your device. They stay in this page only and may not reach another companion app.';

function setStatus(status, detail) {
  const connected = status === 'connected';
  $('status').textContent = status === 'connecting' ? 'Connecting…' : connected ? 'Connected' : 'Disconnected';
  $('status-dot').classList.toggle('online', connected);
  $('connection-detail').textContent = detail || (connected ? 'Companion radio connected' : 'Connect a companion radio to get started.');
  $('connection-footer').textContent = connected ? 'ONLINE' : 'OFFLINE';
  $('feed-status').lastChild.textContent = connected ? ' LISTENING' : ' WAITING FOR CONNECTION';
  $('feed-status').classList.toggle('online-text', connected);
  $('connect').disabled = status === 'connecting';
  $('connect').textContent = connected ? 'Disconnect' : status === 'connecting' ? 'Connecting…' : 'ᛒ  Connect device ↗';
}

function clearFeed() {
  try {
    clearMessages();
    activity = [];
    renderFeed();
  } catch (error) {
    showNotice(`Could not clear saved activity: ${error.message}`, true);
  }
}

function resetDevice() {
  $('battery').replaceChildren(document.createTextNode('— '), unit('V'));
  $('battery-detail').textContent = 'Waiting for device data';
  $('frequency').replaceChildren(document.createTextNode('— '), unit('MHz'));
  $('radio-detail').textContent = 'Waiting for device data';
  $('firmware').textContent = '—';
}

function unit(label) {
  const element = document.createElement('small');
  element.textContent = label;
  return element;
}

function matchesFilter(entry) {
  const { packet } = entry;
  const filter = $('message-filter').value;
  if (filter === 'channel' && packet.kind !== 'Channel') return false;
  if (filter === 'contact' && packet.kind !== 'Contact') return false;
  if (filter === 'datagram' && packet.type !== 'datagram') return false;

  const query = $('search').value.trim().toLocaleLowerCase();
  if (!query) return true;
  return [packet.sender, packet.text, packet.kind, packet.type]
    .filter(value => typeof value === 'string')
    .some(value => value.toLocaleLowerCase().includes(query));
}

function messageElement(entry) {
  const packet = entry.packet;
  const item = document.createElement('li');
  const header = document.createElement('div');
  header.className = 'message-header';
  const sender = document.createElement('strong');
  sender.textContent = packet.kind === 'Contact' ? `Contact ${packet.sender}` : packet.sender;
  const time = document.createElement('time');
  const timestamp = packet.timestamp ? packet.timestamp * 1000 : entry.receivedAt;
  const date = new Date(timestamp);
  time.dateTime = date.toISOString();
  time.textContent = `${date.toLocaleString()}${packet.timestamp ? '' : ' · received'}`;
  header.append(sender, time);
  const body = document.createElement('p');
  body.textContent = packet.type === 'datagram'
    ? `Binary datagram · type 0x${packet.dataType.toString(16).padStart(4, '0')} · ${packet.length} bytes`
    : packet.text || '(Empty message)';
  const meta = document.createElement('div');
  meta.className = 'message-meta';
  meta.textContent = packet.type === 'datagram' ? 'CHANNEL DATA' :
    `${(packet.kind || 'MESSAGE').toUpperCase()}${packet.snr === null ? '' : ` · SNR ${packet.snr} dB`}${packet.textType ? ` · TEXT TYPE ${packet.textType}` : ''}`;
  item.append(header, body, meta);
  return item;
}

function renderFeed() {
  const visible = activity.filter(matchesFilter);
  $('messages').replaceChildren(...visible.map(messageElement));
  $('empty').hidden = visible.length > 0;
  $('message-count').textContent = String(activity.length);
  $('feed-count').textContent = visible.length === activity.length
    ? `${activity.length} saved`
    : `${visible.length} of ${activity.length} shown`;
  $('export').disabled = activity.length === 0;
  $('clear').disabled = activity.length === 0;

  const filtering = $('search').value.trim() || $('message-filter').value !== 'all';
  $('empty-title').textContent = filtering ? 'No matching activity' : 'Nothing here yet';
  $('empty-detail').textContent = filtering
    ? 'Try a different search or message type filter.'
    : 'Connect your radio to see incoming messages.\nNew activity will appear here as it arrives.';
  $('empty-detail').style.whiteSpace = 'pre-line';
}

function addMessage(packet) {
  activity = addStoredMessage(activity, packet);
  try {
    saveMessages(activity);
  } catch (error) {
    showNotice(`Message received, but activity could not be saved: ${error.message}`, true);
  }
  renderFeed();
}

function exportFeed() {
  const blob = new Blob([createExport(activity)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `meshcore-activity-${new Date().toISOString().replaceAll(':', '-')}.json`;
  link.click();
  URL.revokeObjectURL(url);
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
$('export').addEventListener('click', exportFeed);
$('search').addEventListener('input', renderFeed);
$('message-filter').addEventListener('change', renderFeed);

try {
  activity = loadMessages();
} catch (error) {
  showNotice(`Saved activity could not be loaded: ${error.message}`, true);
}
renderFeed();
