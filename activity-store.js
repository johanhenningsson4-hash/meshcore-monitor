const STORAGE_KEY = 'meshcore-monitor.activity.v1';
const MAX_MESSAGES = 500;

export function loadMessages(storage = localStorage) {
  const value = storage.getItem(STORAGE_KEY);
  if (!value) return [];

  const parsed = JSON.parse(value);
  if (!Array.isArray(parsed)) throw new Error('Saved activity data is invalid.');
  return parsed.filter(message =>
    message &&
    typeof message === 'object' &&
    typeof message.packet === 'object' &&
    Number.isFinite(message.receivedAt)
  ).slice(0, MAX_MESSAGES);
}

export function saveMessages(messages, storage = localStorage) {
  storage.setItem(STORAGE_KEY, JSON.stringify(messages.slice(0, MAX_MESSAGES)));
}

export function clearMessages(storage = localStorage) {
  storage.removeItem(STORAGE_KEY);
}

export function createExport(messages) {
  return JSON.stringify({
    exportedAt: new Date().toISOString(),
    application: 'MeshCore Monitor',
    messages,
  }, null, 2);
}

export function addStoredMessage(messages, packet, receivedAt = Date.now()) {
  return [{ receivedAt, packet }, ...messages].slice(0, MAX_MESSAGES);
}
