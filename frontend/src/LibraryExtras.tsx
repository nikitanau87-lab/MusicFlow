import { useEffect, useRef, useState } from 'react';
import { Check, FolderHeart, Music2, Pencil, Plus, Trash2, X, Play, Pause, Volume2 } from 'lucide-react';
import { ensureMediaSession, request } from './api';
import type { Collection, FolderInfo, Project } from './types';

export function formatSize(bytes: number | null): string {
  if (bytes === null) return 'Не рассчитан';
  if (bytes < 1024) return `${bytes} Б`;
  const units = ['КБ', 'МБ', 'ГБ', 'ТБ'];
  let value = bytes / 1024, index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index++; }
  return `${new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 1}).format(value)} ${units[index]}`;
}

export function workedDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString('ru-RU', {day:'numeric', month:'short', year:'numeric'}) : 'Нет данных DAW';
}

export function AudioPreview({project, info, busy, change, choose}: {project: Project; info: FolderInfo | null; busy: boolean; change: (path: string) => void; choose: () => void}) {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const timeLabel = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) audio.play().catch(() => setError('Не удалось начать воспроизведение. Проверьте аудиофайл и повторите попытку.'));
    else audio.pause();
  };
  const modified = info?.audio.find(file => file.path === project.preview_path)?.mtime ?? '';
  useEffect(() => {
    let cancelled = false;
    setError(''); setReady(false); setPlaying(false); setPosition(0); setDuration(0);
    if (project.preview_path) ensureMediaSession().then(() => {if (!cancelled) setReady(true);}).catch(() => {if (!cancelled) setError('Не удалось открыть аудиопревью. Повторите поиск.');});
    return () => {cancelled = true;};
  }, [project.preview_path, modified]);
  const files = info?.audio ?? [];
  return <section className="editor-section audio-section"><h3><Music2 size={17} />Аудиопревью <span className="auto-badge">{project.preview_auto ? 'Автопоиск' : 'Выбранное'}</span></h3>
    <label>Демка<select aria-label="Демка для прослушивания" disabled={busy} value={project.preview_auto ? 'auto' : project.preview_path || 'auto'} onChange={event => change(event.target.value)}><option value="auto">Автоматически — демо и экспорты</option>{project.preview_path && !files.some(file => file.path === project.preview_path) && <option value={project.preview_path}>{project.preview_path.split('/').pop()}</option>}{files.map(file => <option key={file.path} value={file.path}>{file.name}</option>)}</select></label>
    {project.preview_path ? <div className="audio-card"><div className="audio-heading"><div className="audio-glyph"><span /><span /><span /><span /><span /></div><div><strong title={project.preview_path}>{project.preview_path.split('/').pop()}</strong><span>{project.preview_path.split('.').pop()?.toUpperCase()} · демка проекта</span></div></div>{ready && <><audio ref={audioRef} key={`${project.id}:${project.preview_path}:${modified}`} preload="metadata" src={`/api/projects/${project.id}/audio?v=${encodeURIComponent(String(modified))}`} aria-label="Прослушать демку" onLoadedMetadata={() => {const value=audioRef.current?.duration || 0; setDuration(Number.isFinite(value) ? value : 0); if(audioRef.current) audioRef.current.volume=volume;}} onTimeUpdate={() => setPosition(audioRef.current?.currentTime || 0)} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onError={() => setError('Не удалось воспроизвести файл. Он может быть перемещён или иметь неподдерживаемый формат аудио.')} /><div className="audio-controls"><button type="button" className="audio-play" onClick={togglePlay} aria-label={playing ? 'Пауза демки' : 'Воспроизвести демку'}>{playing ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" />}</button><span>{timeLabel(position)}</span><input type="range" aria-label="Позиция воспроизведения" min={0} max={duration || 1} step="0.1" value={position} disabled={!duration} onChange={event => {const value=Number(event.target.value); if(audioRef.current) audioRef.current.currentTime=value; setPosition(value);}} /><span>{timeLabel(duration)}</span></div><div className="audio-volume"><Volume2 size={13} /><input type="range" aria-label="Громкость демки" min={0} max={1} step="0.05" value={volume} onChange={event => {const value=Number(event.target.value); setVolume(value); if(audioRef.current) audioRef.current.volume=value;}} /><span>{Math.round(volume*100)}%</span></div></>}{error && <p className="field-error">{error}</p>}</div> : <p className="section-hint">{info?.state === 'pending' ? 'Ищем аудиофайлы в папке…' : files.length ? 'Аудиофайлы найдены. Выберите демку в списке выше.' : project.folder_path ? 'Демка пока не найдена. Добавьте экспорт в папку проекта и обновите поиск.' : 'Привяжите папку проекта — MusicFlow найдёт демку автоматически.'}</p>}
    <button type="button" className="button subtle small" disabled={busy} onClick={choose}><Music2 size={14} />Выбрать другой аудиофайл</button>
  </section>;
}

export function CollectionManager({collections, busy, run, updated}: {collections: Collection[]; busy: boolean; run: (action: () => Promise<void>) => Promise<boolean>; updated: () => void}) {
  const [name, setName] = useState('');
  const [editing, setEditing] = useState<number | null>(null);
  const [renamed, setRenamed] = useState('');
  const [deleting, setDeleting] = useState<Collection | null>(null);
  const rename = (item: Collection) => run(async () => {await request(`/collections/${item.id}`, {method:'PATCH', body:JSON.stringify({name:renamed})}); setEditing(null); updated();});
  if (deleting) return <><p className="modal-description">Удалить подборку «{deleting.name}»? Все проекты и музыкальные файлы сохранятся.</p><div className="modal-actions"><button className="button secondary" disabled={busy} onClick={() => setDeleting(null)}>Отмена</button><button className="button danger" disabled={busy} onClick={() => run(async () => {await request(`/collections/${deleting.id}`, {method:'DELETE'}); setDeleting(null); updated();})}>Удалить подборку</button></div></>;
  return <><p className="modal-description">Собирайте треки для EP, релиза или настроения. Один трек может входить в несколько подборок.</p><form className="collection-add" onSubmit={event => {event.preventDefault(); run(async () => {await request('/collections', {method:'POST', body:JSON.stringify({name})}); setName(''); updated();});}}><input aria-label="Название новой подборки" data-autofocus placeholder="Например, Первый EP" value={name} maxLength={80} disabled={busy} onChange={event => setName(event.target.value)} /><button className="button primary small" disabled={busy || !name.trim()}><Plus size={16} />Создать</button></form><div className="collection-manager-list">{collections.length ? collections.map(item => <div key={item.id} className="collection-manager-row"><FolderHeart size={17} />{editing === item.id ? <><input aria-label="Новое название подборки" value={renamed} maxLength={80} onChange={event => setRenamed(event.target.value)} onKeyDown={event => {if(event.key === 'Enter') rename(item); if(event.key === 'Escape') setEditing(null);}} autoFocus /><button className="icon-button" disabled={busy || !renamed.trim()} aria-label="Сохранить название подборки" onClick={() => rename(item)}><Check size={16} /></button><button className="icon-button" aria-label="Отменить переименование подборки" onClick={() => setEditing(null)}><X size={16} /></button></> : <><span>{item.name}<small>{item.project_count} активных треков</small></span><button className="icon-button" disabled={busy} aria-label={`Переименовать подборку: ${item.name}`} onClick={() => {setEditing(item.id); setRenamed(item.name);}}><Pencil size={14} /></button><button className="icon-button danger-hover" disabled={busy} aria-label={`Удалить подборку: ${item.name}`} onClick={() => setDeleting(item)}><Trash2 size={14} /></button></>}</div>) : <p className="section-hint">Создайте первую подборку, затем добавьте в неё треки из их карточек.</p>}</div></>;
}
