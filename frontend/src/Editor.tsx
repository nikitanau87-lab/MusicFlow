import { useEffect, useRef, useState } from 'react';
import { Archive, ArchiveRestore, ArrowDown, ArrowLeft, ArrowUp, Check, CheckCheck, ExternalLink, Folder, FolderOpen, Plus, Save, Trash2, X, Pencil, FileText, Tags, FolderHeart, RefreshCw, Play, Music2 } from 'lucide-react';
import { native, request } from './api';
import { Progress, StageBadge } from './components';
import { keys, stages } from './types';
import type { Collection, FolderInfo, Project, Stage, Task } from './types';
import { AudioPreview, formatSize, workedDate } from './LibraryExtras';

type Props = { project: Project; collections: Collection[]; knownTags: string[]; busy: boolean; changed: (project: Project) => void; run: (action: () => Promise<void>) => Promise<boolean>; dirtyChanged: (dirty: boolean) => void; close: () => void; remove: () => void };
const draftFor = (p: Project) => ({ title: p.title, bpm: p.bpm?.toString() ?? '', musical_key: p.musical_key ?? '', genre: p.genre ?? '', status: p.status, notes: p.notes, folder_path: p.folder_path ?? '', daw_path: p.daw_path ?? '', tags: p.tags ?? [], collection_ids: [...(p.collection_ids ?? [])].sort((a,b) => a-b) });

function TaskRow({ task, index, total, busy, modify, move, remove, editingChanged }: { task: Task; index: number; total: number; busy: boolean; modify: (data: object) => Promise<boolean>; move: (offset: number) => void; remove: () => void; editingChanged: (value: boolean) => void }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(task.title);
  const commit = async () => {
    if (!title.trim()) return;
    if (await modify({ title: title.trim() })) { setEditing(false); editingChanged(false); }
  };
  return <div className={`task-row ${task.completed ? 'completed' : ''}`}>
    <button className="task-check" disabled={busy} onClick={() => modify({ completed: !task.completed })} aria-label={`${task.completed ? 'Отметить невыполненной' : 'Выполнить'}: ${task.title}`} aria-pressed={task.completed}>{task.completed && <Check size={14} strokeWidth={3} />}</button>
    {editing ? <div className="task-edit"><input autoFocus aria-label="Название задачи" maxLength={300} value={title} onChange={e => setTitle(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { setTitle(task.title); setEditing(false); editingChanged(false); } }} /><button className="icon-button" disabled={busy || !title.trim()} onClick={commit} aria-label="Сохранить название задачи"><Check size={16} /></button><button className="icon-button" onClick={() => { setEditing(false); editingChanged(false); }} aria-label="Отменить переименование"><X size={16} /></button></div> : <><span className="task-title">{task.title}</span><div className="task-actions"><button className="icon-button" disabled={busy} onClick={() => { setTitle(task.title); setEditing(true); editingChanged(true); }} title="Переименовать" aria-label={`Переименовать: ${task.title}`}><Pencil size={13} /></button><button className="icon-button" disabled={busy || index === 0} onClick={() => move(-1)} title="Выше" aria-label={`Переместить выше: ${task.title}`}><ArrowUp size={13} /></button><button className="icon-button" disabled={busy || index === total - 1} onClick={() => move(1)} title="Ниже" aria-label={`Переместить ниже: ${task.title}`}><ArrowDown size={13} /></button><button className="icon-button danger-hover" disabled={busy} onClick={remove} title="Удалить задачу" aria-label={`Удалить: ${task.title}`}><Trash2 size={13} /></button></div></>}
  </div>;
}

export default function Editor({ project, collections, knownTags, busy, changed, run, dirtyChanged, close, remove }: Props) {
  const [draft, setDraft] = useState(() => draftFor(project));
  const [newTask, setNewTask] = useState('');
  const [folderError, setFolderError] = useState(false);
  const [editingTasks, setEditingTasks] = useState<Record<number, boolean>>({});
  const [tagText, setTagText] = useState('');
  const [tagError, setTagError] = useState('');
  const [folderInfo, setFolderInfo] = useState<FolderInfo | null>(null);
  const [scanError, setScanError] = useState('');
  const [scanRevision, setScanRevision] = useState(0);
  const previousProject = useRef(project);
  const changedRef = useRef(changed);
  changedRef.current = changed;
  useEffect(() => {
    const before = draftFor(previousProject.current), incoming = draftFor(project);
    setDraft(current => {
      const next = {...current};
      for (const key of Object.keys(incoming) as (keyof typeof incoming)[]) {
        if (JSON.stringify(current[key]) === JSON.stringify(before[key])) Object.assign(next, {[key]: incoming[key]});
      }
      return next;
    });
    previousProject.current = project;
  }, [project]);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setFolderInfo(null); setScanError('');
    const load = async (refresh: boolean) => {
      try {
        const info = await request<FolderInfo>(`/projects/${project.id}/folder-info${refresh ? '?refresh=true' : ''}`);
        if (cancelled) return;
        setFolderInfo(info);
        if (info.state === 'pending') timer = setTimeout(() => load(false), 800);
        else {
          changedRef.current(info.project);
          if (project.folder_path || project.daw_path) timer = setTimeout(() => load(true), 20000);
        }
      } catch (error) { if (!cancelled) setScanError(error instanceof Error ? error.message : 'Не удалось проверить файлы.'); }
    };
    load(scanRevision > 0);
    return () => {cancelled = true; if(timer) clearTimeout(timer);};
  }, [project.id, project.folder_path, project.daw_path, scanRevision]);
  const mergedTags = () => {
    const values = [...draft.tags, ...tagText.split(',').map(tag => tag.trim().replace(/^#+/, '').replace(/\s+/g, ' ')).filter(Boolean)];
    return values.filter((tag, index) => values.findIndex(item => item.toLowerCase() === tag.toLowerCase()) === index);
  };
  const addTags = () => {
    const tags = mergedTags();
    if(tags.length > 30 || tags.some(tag => tag.length > 48)) {setTagError('До 30 тегов, каждый не длиннее 48 символов.'); return;}
    setDraft(current => ({...current, tags})); setTagText(''); setTagError('');
  };
  const dirty = JSON.stringify(draft) !== JSON.stringify(draftFor(project));
  useEffect(() => { dirtyChanged(dirty || Boolean(tagText.trim()) || Boolean(newTask.trim()) || Object.values(editingTasks).some(Boolean)); }, [dirty, tagText, newTask, editingTasks, dirtyChanged]);
  const field = <K extends keyof typeof draft>(name: K, value: typeof draft[K]) => setDraft(current => ({ ...current, [name]: value }));
  const mutate = (path: string, method: string, data?: object) => run(async () => changed(await request<Project>(`/projects/${project.id}${path}`, { method, body: data ? JSON.stringify(data) : undefined })));
  const save = () => run(async () => {
    const updated = await request<Project>(`/projects/${project.id}`, { method: 'PATCH', body: JSON.stringify({ ...draft, tags: mergedTags(), daw_path: draft.daw_path || null, bpm: draft.bpm ? Number(draft.bpm) : null, musical_key: draft.musical_key || null, genre: draft.genre || null, folder_path: draft.folder_path || null }) });
    setDraft(draftFor(updated)); setTagText(''); changed(updated);
  });
  const chooseFolder = () => run(async () => { const result = await native('choose_folder'); if (!result.cancelled && result.value) { field('folder_path', result.value); setFolderError(false); } });
  const chooseDaw = () => run(async () => {
    const result = await native('choose_daw_file', project.id);
    if (!result.cancelled && result.value) setDraft(current => ({...current, daw_path: result.value!, folder_path: current.folder_path || result.folder || ''}));
  });
  const changePreview = (path: string) => run(async () => {
    changed(await request<Project>(`/projects/${project.id}`, {method:'PATCH', body:JSON.stringify({preview_auto: path === 'auto', preview_path: path === 'auto' ? null : path})}));
    if(path === 'auto') setScanRevision(current => current+1);
  });
  const choosePreview = () => run(async () => {
    const result = await native('choose_audio_file', project.id);
    if (!result.cancelled && result.value) changed(await request<Project>(`/projects/${project.id}`, {method:'PATCH', body:JSON.stringify({preview_path:result.value, preview_auto:false})}));
  });
  const moveTask = (index: number, offset: number) => {
    const ids = project.tasks.map(t => t.id);
    [ids[index], ids[index + offset]] = [ids[index + offset], ids[index]];
    mutate('/tasks/order', 'PUT', { ids });
  };
  const dateLabel = new Date(project.created_at).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
  return <aside className="editor" aria-label="Карточка проекта">
    <header className="editor-header"><button className="icon-button" onClick={close} aria-label="Закрыть карточку"><ArrowLeft size={18} /></button><span>КАРТОЧКА ПРОЕКТА</span><StageBadge stage={project.status} /></header>
    <div className="editor-scroll">
      <div className="editor-title"><div className={`track-art art-${project.status}`}><span>{project.title.slice(0, 1).toUpperCase()}</span><i /></div><div><h2 title={project.title}>{project.title}</h2><p>Создан {dateLabel}</p></div></div>
      {project.archived && <div className="inline-note"><Archive size={16} />Этот проект находится в архиве</div>}
      <AudioPreview project={project} info={folderInfo} busy={busy} change={changePreview} choose={choosePreview} />
      <form id="project-form" onSubmit={e => { e.preventDefault(); save(); }}>
        <label>Название трека<input value={draft.title} onChange={e => field('title', e.target.value)} required maxLength={200} disabled={busy} /></label>
        <div className="field-pair"><label>BPM<input type="number" step="any" min="0.001" placeholder="Например, 120" value={draft.bpm} onChange={e => field('bpm', e.target.value)} disabled={busy} /></label><label>Тональность<select value={draft.musical_key} onChange={e => field('musical_key', e.target.value)} disabled={busy}><option value="">Не указана</option>{draft.musical_key && !keys.includes(draft.musical_key) && <option>{draft.musical_key}</option>}{keys.map(k => <option key={k}>{k}</option>)}</select></label></div>
        <div className="field-pair"><label>Жанр<input placeholder="Например, Hip-hop" maxLength={100} value={draft.genre} onChange={e => field('genre', e.target.value)} disabled={busy} /></label><label>Стадия<select value={draft.status} onChange={e => field('status', e.target.value as Stage)} disabled={busy}>{Object.entries(stages).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
        <section className="editor-section organization-section"><h3><Tags size={16} />Теги и подборки</h3><div className="tag-chips">{draft.tags.map(tag => <span key={tag} className="tag-chip">#{tag}<button type="button" disabled={busy} aria-label={`Убрать тег: ${tag}`} onClick={() => field('tags', draft.tags.filter(item => item !== tag))}><X size={12} /></button></span>)}</div><div className="tag-entry"><input aria-label="Новый тег" list={`known-tags-${project.id}`} placeholder="Тег, затем Enter…" value={tagText} onChange={event => setTagText(event.target.value)} disabled={busy} onKeyDown={event => {if (event.key === 'Enter' || event.key === ',') {event.preventDefault(); addTags();}}} /><button type="button" className="icon-button" aria-label="Добавить тег" onClick={addTags} disabled={busy || !tagText.trim()}><Plus size={16} /></button></div><datalist id={`known-tags-${project.id}`}>{knownTags.map(tag => <option key={tag} value={tag} />)}</datalist>{tagError && <p className="field-error">{tagError}</p>}<div className="collection-choices">{collections.length ? collections.map(collection => <label key={collection.id}><input type="checkbox" disabled={busy} checked={draft.collection_ids.includes(collection.id)} onChange={event => field('collection_ids', (event.target.checked ? [...draft.collection_ids, collection.id] : draft.collection_ids.filter(id => id !== collection.id)).sort((a,b) => a-b))} /><FolderHeart size={14} /><span>{collection.name}</span></label>) : <p className="section-hint">Создайте подборку кнопкой + в боковом меню.</p>}</div></section>
        <section className="editor-section"><h3><Music2 size={16} />Основной проект DAW</h3>{draft.daw_path ? <div className="folder-card"><Music2 size={17} /><span title={draft.daw_path}>{draft.daw_path.split('/').pop()}</span><button type="button" className="icon-button" aria-label="Убрать ссылку на файл DAW" disabled={busy} onClick={() => field('daw_path','')}><X size={14} /></button></div> : <p className="section-hint">Выберите основной .flp или файл другой DAW.</p>}<div className="folder-actions"><button type="button" className="button subtle small" disabled={busy} onClick={chooseDaw}><FolderOpen size={14} />{draft.daw_path ? 'Другой файл' : 'Выбрать файл DAW'}</button>{project.daw_path && project.daw_path === draft.daw_path && <button type="button" className="button primary small" disabled={busy} onClick={() => run(async () => {await native('open_daw_project',project.id);})}><Play size={14} />{project.daw_path.toLowerCase().endsWith('.flp') ? 'В FL Studio' : 'Открыть в DAW'}</button>}</div>{draft.daw_path !== (project.daw_path || '') && <p className="section-hint">Сохраните ссылку, чтобы открывать проект отсюда.</p>}</section>
        <section className="editor-section"><h3><Folder size={16} />Папка проекта</h3>{draft.folder_path ? <div className={`folder-card ${folderError ? 'folder-missing' : ''}`}><FolderOpen size={18} /><span title={draft.folder_path}>{draft.folder_path}</span><button type="button" className="icon-button" aria-label="Убрать ссылку на папку" disabled={busy} onClick={() => field('folder_path', '')}><X size={14} /></button></div> : <p className="section-hint">Свяжите трек с папкой вашего DAW-проекта.</p>}<div className="folder-actions"><button type="button" className="button subtle small" disabled={busy} onClick={chooseFolder}><Folder size={14} />{draft.folder_path ? 'Выбрать другую' : 'Выбрать папку'}</button>{project.folder_path && project.folder_path === draft.folder_path && <button type="button" className="button subtle small" disabled={busy} onClick={() => run(async () => { try { await native('open_project_folder', project.id); setFolderError(false); } catch (error) { setFolderError(true); throw error; } })}><ExternalLink size={14} />В Finder</button>}</div>{draft.folder_path !== (project.folder_path ?? '') && <p className="section-hint">Сохраните изменения, чтобы привязать папку.</p>}{folderError && <p className="field-error">Папка недоступна. Выберите её заново.</p>}{project.folder_path === draft.folder_path && project.folder_path && <><div className="folder-stats"><div><span>Размер папки</span><strong>{project.folder_unavailable ? 'Недоступна' : `${project.folder_scan_partial ? '≥ ' : ''}${formatSize(project.folder_size_bytes)}`}</strong><small>{project.folder_file_count !== null ? `${project.folder_file_count} файлов` : 'Ожидает проверки'}</small></div><div><span>Последняя работа</span><strong>{workedDate(project.last_worked_at)}</strong><small>По сохранению файла DAW</small></div></div><button type="button" className="template-button" disabled={folderInfo?.state === 'pending'} onClick={() => setScanRevision(current => current+1)}><RefreshCw size={13} className={folderInfo?.state === 'pending' ? 'spin' : ''} />{folderInfo?.state === 'pending' ? 'Проверяем файлы…' : 'Обновить размер и поиск демки'}</button>{(scanError || folderInfo?.error) && <p className="section-hint scan-note">{scanError || folderInfo?.error}</p>}</>}</section>
        <section className="editor-section"><h3><FileText size={16} />Заметки</h3><textarea rows={4} value={draft.notes} maxLength={100000} onChange={e => field('notes', e.target.value)} placeholder="Идея, референсы или то, что стоит попробовать…" disabled={busy} /></section>
      </form>
      <section className="editor-section task-section"><div className="section-heading"><h3><CheckCheck size={17} />Задачи <span className="count-pill">{project.task_count}</span></h3><span className="muted small-text">{project.completed_tasks} выполнено</span></div>{project.task_count > 0 && <Progress project={project} />}
        <div className="task-list">{project.tasks.map((task, index) => <TaskRow key={task.id} task={task} index={index} total={project.tasks.length} busy={busy} modify={data => mutate(`/tasks/${task.id}`, 'PATCH', data)} move={offset => moveTask(index, offset)} remove={() => mutate(`/tasks/${task.id}`, 'DELETE')} editingChanged={value => setEditingTasks(current => ({...current, [task.id]: value}))} />)}</div>
        {!project.task_count && <p className="section-hint">Разбейте трек на небольшие шаги.</p>}
        <form className="add-task" onSubmit={async e => { e.preventDefault(); if (newTask.trim() && await mutate('/tasks', 'POST', { title: newTask.trim() })) setNewTask(''); }}><input aria-label="Новая задача" placeholder="Добавить задачу…" value={newTask} onChange={e => setNewTask(e.target.value)} maxLength={300} disabled={busy} /><button className="icon-button" disabled={busy || !newTask.trim()} aria-label="Добавить задачу"><Plus size={18} /></button></form>
        <button className="template-button" disabled={busy} onClick={() => mutate('/tasks/template', 'POST')}><Plus size={14} />Добавить типовые задачи</button>
      </section>
      <div className="project-actions"><button className="button subtle small" disabled={busy} onClick={() => mutate('', 'PATCH', { archived: !project.archived })}>{project.archived ? <ArchiveRestore size={15} /> : <Archive size={15} />}{project.archived ? 'Вернуть из архива' : 'В архив'}</button><button className="icon-button danger-hover" disabled={busy} onClick={remove} title="Удалить проект" aria-label="Удалить проект"><Trash2 size={16} /></button></div>
    </div>
    <footer className="editor-footer"><span>{busy ? 'Сохраняем…' : dirty || tagText.trim() ? 'Есть несохранённые изменения' : newTask.trim() ? 'Добавьте новую задачу кнопкой +' : Object.values(editingTasks).some(Boolean) ? 'Завершите редактирование задачи' : 'Все изменения сохранены'}</span><button form="project-form" type="submit" className="button primary small" disabled={busy || (!dirty && !tagText.trim())}><Save size={15} />Сохранить</button></footer>
  </aside>;
}
