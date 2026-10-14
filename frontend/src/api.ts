import type { Bridge, NativeResult } from './types';

let token: string | undefined;
const ready = new Promise<void>((resolve) => {
  const accept = () => { token = window.pywebview?.token; resolve(); };
  if (window.pywebview) accept();
  else window.addEventListener('pywebviewready', accept, { once: true });
});

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  await ready;
  const response = await fetch(`/api${path}`, { ...options, headers: { 'Content-Type': 'application/json', 'X-MusicFlow-Token': token!, ...options.headers } });
  if (!response.ok) {
    let message = 'Не удалось связаться с MusicFlow. Повторите попытку.';
    try { const body = await response.json(); if (typeof body.detail === 'string') message = body.detail; } catch { /* keep useful default */ }
    throw new Error(message);
  }
  return response.status === 204 ? undefined as T : response.json();
}

export async function native<K extends keyof Bridge>(method: K, ...args: Parameters<Bridge[K]>): Promise<NativeResult> {
  await ready;
  const fn = window.pywebview?.api[method];
  if (!fn) throw new Error('Эта функция доступна в приложении MusicFlow для Mac.');
  const result = await (fn as (...args: unknown[]) => Promise<NativeResult>)(...args);
  if (!result.ok) throw new Error(result.error || 'Не удалось выполнить действие.');
  return result;
}

let mediaSession: Promise<unknown> | null = null;
export function ensureMediaSession(): Promise<unknown> {
  if (!mediaSession) mediaSession = request('/media-session', {method: 'POST'}).catch(error => { mediaSession = null; throw error; });
  return mediaSession;
}
