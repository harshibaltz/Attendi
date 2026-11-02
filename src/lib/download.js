import api from './api';

/**
 * Download a CSV endpoint as a file through the authenticated API client.
 *
 * Using axios (not a plain <a href>) keeps the dev base URL and cookies in
 * play, and lets us surface a real error instead of navigating to JSON.
 */
export const downloadCsv = async (path, fallbackName) => {
  const res = await api.get(path, { responseType: 'blob' });
  const disposition = res.headers?.['content-disposition'] || '';
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  const filename = match ? decodeURIComponent(match[1]) : fallbackName;

  const url = URL.createObjectURL(res.data);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
};

export default downloadCsv;
