import { useCallback, useEffect, useRef, useState } from 'react';
import { Archive, ArrowUpRight, Check, CheckCheck, ChevronRight, Download, FolderOpen, Headphones, Layers3, LoaderCircle, Music2, Plus, Search, Settings, ShieldCheck, SlidersHorizontal, Sparkles, Upload, X, FolderHeart, RefreshCw } from 'lucide-react';
import { request, native } from './api';
import { Modal, Progress, StageBadge } from './components';
import Editor from './Editor';
import { keys, stages } from './types';
import type { Collection, Overview, Project, Stage } from './types';
import { CollectionManager, formatSize, workedDate } from './LibraryExtras';

const initialOverview: Overview = { active: 0, archived: 0, done: 0, genres: [], tags: [] };
type Notice = { text: string; error: boolean };

function CreateForm({ busy, submit, close }: { busy: boolean; submit: (data: object) => Promise<void>; close: () => void }) {
  const [title, setTitle] = useState('');
  const [bpm, setBpm] = useState('');
  const [key, setKey] = useState('');
  const [genre, setGenre] = useState('');
  return <form onSubmit={e => { e.preventDefault(); submit({ title: title.trim(), bpm: bpm ? Number(bpm) : null, musical_key: key || null, genre: genre.trim() || null }); }}>
    <p className="modal-description">Каждый трек начинается с идеи. Остальные детали можно заполнить позже.</p>
    <label>Название трека <span className="required">*</span><input data-autofocus placeholder="Как назовём новый трек?" value={title} onChange={e => setTitle(e.target.value)} required maxLength={200} disabled={busy} /></label>
    <div className="field-pair"><label>BPM<input type="number" min="0.001" step="any" placeholder="120" value={bpm} onChange={e => setBpm(e.target.value)} disabled={busy} /></label><label>Тональность<select value={key} onChange={e => setKey(e.target.value)} disabled={busy}><option value="">Не указана</option>{keys.map(k => <option key={k}>{k}</option>)}</select></label></div>
    <label>Жанр<input placeholder="Hip-hop, House, Ambient…" maxLength={100} value={genre} onChange={e => setGenre(e.target.value)} disabled={busy} /></label>
    <div className="modal-actions"><button type="button" className="button secondary" onClick={close} disabled={busy}>Отмена</button><button className="button primary" disabled={busy || !title.trim()}>{busy ? <LoaderCircle className="spin" size={17} /> : <Plus size={17} />}Создать проект</button></div>
  </form>;
}

export default function App() {
  const [mode, setMode] = useState<'active' | 'archive'>('active');
  const [projects, setProjects] = useState<Project[]>([]);
  const [overview, setOverview] = useState(initialOverview);
  const [selected, setSelected] = useState<Project | null>(null);
  const [search, setSearch] = useState('');
  const [stage, setStage] = useState('');
  const [genre, setGenre] = useState('');
  const [tag, setTag] = useState('');
  const [collection, setCollection] = useState('');
  const [collections, setCollections] = useState<Collection[]>([]);
  const [manageCollections, setManageCollections] = useState(false);
  const [fileRevision, setFileRevision] = useState(0);
  const [filesRefreshing, setFilesRefreshing] = useState(false);
  const [sort, setSort] = useState('updated');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const operation = useRef(false);
  const [dirty, setDirty] = useState(false);
  const dirtyChanged = useCallback((value: boolean) => setDirty(value), []);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [create, setCreate] = useState(false);
  const [settings, setSettings] = useState(false);
  const [remove, setRemove] = useState(false);
  const [restore, setRestore] = useState<string | null>(null);
  const [discard, setDiscard] = useState<(() => void) | null>(null);
  const refresh = () => setRevision(current => current + 1);

  useEffect(() => { window.musicflowUnsaved = dirty; void native('set_dirty', dirty).catch(() => {}); return () => { window.musicflowUnsaved = false; }; }, [dirty]);
  useEffect(() => {
    if (!notice || notice.error) return;
    const timer = setTimeout(() => setNotice(null), 4500);
    return () => clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams({ archived: String(mode === 'archive'), search, sort });
        if (stage) params.set('status', stage);
        if (genre) params.set('genre', genre);
        if (tag) params.set('tag', tag);
        if (collection) params.set('collection_id', collection);
        const [list, summary, groups] = await Promise.all([request<Project[]>(`/projects?${params}`, { signal: controller.signal }), request<Overview>('/overview', { signal: controller.signal }), request<Collection[]>('/collections', { signal: controller.signal })]);
        if (!controller.signal.aborted) { setProjects(list); setOverview(summary); setCollections(groups); setLoadError(''); }
      } catch (error) {
        if (!controller.signal.aborted) setLoadError(error instanceof Error ? error.message : 'Не удалось загрузить проекты.');
      } finally { if (!controller.signal.aborted) setLoading(false); }
    }, search ? 180 : 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [mode, search, stage, genre, tag, collection, sort, revision]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async (initial: boolean) => {
      try {
        const status = await request<{pending:number}>(initial ? '/files/refresh' : '/files/status', initial ? {method:'POST'} : {});
        if(cancelled) return;
        setFilesRefreshing(status.pending > 0);
        if(status.pending > 0) timer = setTimeout(() => poll(false), 1000);
        else if(!initial) setRevision(current => current+1);
      } catch {if(!cancelled) setFilesRefreshing(false);}
    };
    poll(true);
    return () => {cancelled=true; if(timer) clearTimeout(timer);};
  }, [fileRevision]);

  const run = async (action: () => Promise<void>): Promise<boolean> => {
    if (operation.current) return false;
    operation.current = true; setBusy(true);
    try { await action(); return true; }
    catch (error) { setNotice({ text: error instanceof Error ? error.message : 'Не удалось выполнить действие.', error: true }); return false; }
    finally { operation.current = false; setBusy(false); }
  };
  const navigate = (action: () => void) => { if (busy) return; if (dirty) setDiscard(() => action); else action(); };
  const showCreate = () => navigate(() => setCreate(true));
  const selectProject = (project: Project) => { if (selected?.id !== project.id) navigate(() => { setDirty(false); setSelected(project); }); };
  const switchMode = (next: 'active' | 'archive') => navigate(() => { setSelected(null); setDirty(false); setMode(next); setSearch(''); setStage(''); setGenre(''); setTag(''); setCollection(''); });
  const changed = (project: Project) => { setSelected(project); refresh(); };
  const allEmpty = (mode === 'active' ? overview.active : overview.archived) === 0;
  const filtered = Boolean(search || stage || genre || tag || collection);

  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'n') { event.preventDefault(); if (!create && !settings && !restore && !remove && !discard && !manageCollections) showCreate(); }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'f') { event.preventDefault(); document.getElementById('project-search')?.focus(); }
    };
    window.addEventListener('keydown', listener);
    return () => window.removeEventListener('keydown', listener);
  });

  return <div className={`app-shell ${selected ? 'has-selection' : ''}`}>
    <nav className="sidebar" aria-label="Навигация">
      <div className="brand"><div className="brand-mark"><span /><span /><span /><span /><span /></div><strong>Music<span>Flow</span></strong></div>
      <div className="workspace-tag"><span className="online-dot" />Личная студия</div>
      <div className="nav-label">БИБЛИОТЕКА</div>
      <button className={`nav-item ${mode === 'active' && !collection ? 'is-active' : ''}`} onClick={() => switchMode('active')} disabled={busy}><Layers3 size={18} /><span>Проекты</span><b>{overview.active}</b></button>
      <button className={`nav-item ${mode === 'archive' ? 'is-active' : ''}`} onClick={() => switchMode('archive')} disabled={busy}><Archive size={18} /><span>Архив</span>{overview.archived > 0 && <b>{overview.archived}</b>}</button>
      <div className="collection-nav-heading"><div className="nav-label">ПОДБОРКИ</div><button className="icon-button" aria-label="Управлять подборками" title="Подборки" disabled={busy} onClick={() => navigate(() => setManageCollections(true))}><Plus size={16} /></button></div><div className="collection-nav-list">{collections.map(item => <button key={item.id} className={`nav-item ${mode === 'active' && collection === String(item.id) ? 'is-active' : ''}`} disabled={busy} onClick={() => navigate(() => {setMode('active'); setCollection(String(item.id)); setSelected(null); setDirty(false);})}><FolderHeart size={16} /><span title={item.name}>{item.name}</span><b>{item.project_count}</b></button>)}{!collections.length && <p className="collection-nav-empty">Треки для релиза<br />или одного настроения</p>}</div>
      <div className="sidebar-bottom"><div className="local-card"><ShieldCheck size={17} /><div><strong>Всё на вашем Mac</strong><span>Работает без интернета</span></div></div><button className="nav-item" onClick={() => setSettings(true)} disabled={busy}><Settings size={18} /><span>Настройки</span></button><div className="sidebar-version"><span>MusicFlow</span><span>v0.2.0</span></div></div>
    </nav>
    <main className="workspace">
      <header className="workspace-header"><div className="breadcrumb">Личная студия <ChevronRight size={13} /><span>{mode === 'active' ? 'Проекты' : 'Архив'}</span></div><span className="local-status"><span className="online-dot" />Локально</span></header>
      <div className="workspace-content">
        <section className="page-heading"><div><div className="eyebrow">ВАША МУЗЫКА. ВАШ РИТМ.</div><h1>{mode === 'active' ? 'Проекты' : 'Архив'}</h1><p>{mode === 'active' ? 'От первой идеи до последнего штриха.' : 'Отложенные проекты. Вернитесь к ним, когда придёт время.'}</p></div><button className="button primary" onClick={showCreate} disabled={busy}><Plus size={18} />Новый проект</button></section>
        <div className="summary-row"><div className="summary-card"><div className="summary-icon violet"><Music2 size={19} /></div><div><span>Всего проектов</span><strong>{overview.active}</strong></div></div><div className="summary-card"><div className="summary-icon amber"><Headphones size={19} /></div><div><span>В процессе</span><strong>{overview.active - overview.done}</strong></div></div><div className="summary-card"><div className="summary-icon green"><CheckCheck size={19} /></div><div><span>Завершено</span><strong>{overview.done}</strong></div></div></div>
        <section className="library" aria-label="Список треков"><div className="library-toolbar"><div className="library-caption"><h2>{mode === 'active' ? 'Ваши треки' : 'Треки в архиве'}</h2><span className="count-pill">{mode === 'active' ? overview.active : overview.archived}</span></div><div className="sort-control"><button className="icon-button" disabled={filesRefreshing} aria-label="Обновить информацию о файлах" title="Обновить размеры и даты DAW" onClick={() => setFileRevision(current => current+1)}><RefreshCw size={14} className={filesRefreshing ? 'spin' : ''} /></button><SlidersHorizontal size={14} /><select aria-label="Сортировка проектов" value={sort} onChange={e => setSort(e.target.value)}><option value="updated">Последние изменения</option><option value="created">Сначала новые</option><option value="title">По названию</option><option value="size">Сначала большие папки</option><option value="worked">Последняя работа в DAW</option></select></div></div>
          <div className="filters"><div className="search-field"><Search size={17} /><input id="project-search" placeholder="Найти трек…" aria-label="Поиск проектов" value={search} onChange={e => setSearch(e.target.value)} />{search ? <button className="icon-button" onClick={() => setSearch('')} aria-label="Очистить поиск"><X size={14} /></button> : <kbd>⌘ F</kbd>}</div><select aria-label="Фильтр по стадии" value={stage} onChange={e => setStage(e.target.value)}><option value="">Все стадии</option>{Object.entries(stages).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><select aria-label="Фильтр по жанру" value={genre} onChange={e => setGenre(e.target.value)}><option value="">Все жанры</option>{overview.genres.map(g => <option key={g}>{g}</option>)}</select><select aria-label="Фильтр по тегу" value={tag} onChange={e => setTag(e.target.value)}><option value="">Все теги</option>{overview.tags.map(item => <option key={item}>{item}</option>)}</select><select aria-label="Фильтр по подборке" value={collection} onChange={e => setCollection(e.target.value)}><option value="">Все подборки</option>{collections.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>
          {loadError ? <div className="empty-state"><p className="field-error">{loadError}</p><button className="button secondary" onClick={refresh}>Повторить загрузку</button></div> : loading && !projects.length ? <div className="empty-state"><LoaderCircle className="spin" size={25} /><p>Открываем вашу библиотеку…</p></div> : projects.length ? <div className={`track-table ${loading ? 'loading' : ''}`}><div className="table-head"><span>ТРЕК / ЖАНР</span><span>BPM</span><span title="Тональность">ТОНАЛЬН.</span><span>СТАДИЯ</span><span>ПРОГРЕСС</span></div>{projects.map(project => <button key={project.id} className={`track-row ${selected?.id === project.id ? 'selected' : ''}`} onClick={() => selectProject(project)} disabled={busy} aria-label={`Открыть проект: ${project.title}`} aria-pressed={selected?.id === project.id}><div className="track-name"><div className={`track-art art-${project.status}`}><span>{project.title.slice(0, 1).toUpperCase()}</span><i /></div><div><strong title={project.title}>{project.title}</strong><span>{project.genre || 'Без жанра'}{project.tags.length > 0 && <em className="track-tags"> · {project.tags.slice(0,2).map(item => `#${item}`).join(' ')}</em>}</span><small className="track-file-meta" title={`Последняя работа по сохранению DAW: ${workedDate(project.last_worked_at)}`}><span>{project.folder_unavailable ? 'Папка недоступна' : project.folder_size_bytes !== null ? `${project.folder_scan_partial ? '≥ ' : ''}${formatSize(project.folder_size_bytes)}` : 'Размер не рассчитан'}</span>{project.last_worked_at && <span> · {workedDate(project.last_worked_at)}</span>}{project.preview_path && <Music2 size={10} aria-label="Есть демка" />}</small></div></div><span className="track-bpm">{project.bpm ?? '—'}</span><span className="track-key">{project.musical_key || '—'}</span><StageBadge stage={project.status} /><Progress project={project} /></button>)}</div> : <div className="empty-state"><div className="empty-art"><div className="empty-disc"><Music2 size={34} strokeWidth={1.5} /></div><span className="empty-spark"><Sparkles size={16} /></span><span className="empty-note">♫</span></div><h3>{filtered ? 'Ничего не найдено' : mode === 'archive' ? 'В архиве пока пусто' : 'Здесь начнётся ваш следующий трек'}</h3><p>{filtered ? 'Попробуйте другое название или измените фильтры.' : mode === 'archive' ? 'Отложенные проекты будут ждать вас здесь.' : 'Соберите идеи, задачи и детали проекта в одном месте.'}</p>{filtered ? <button className="button secondary" onClick={() => { setSearch(''); setStage(''); setGenre(''); setTag(''); setCollection(''); }}>Сбросить фильтры</button> : mode === 'active' && <button className="button primary" onClick={showCreate}><Plus size={17} />Создать первый проект</button>}</div>}
          {!loadError && projects.length > 0 && <div className="library-footer"><span>{filtered ? `Найдено: ${projects.length}` : `Треков: ${projects.length}`}</span><span>Выберите трек, чтобы открыть детали <ArrowUpRight size={13} /></span></div>}
        </section>
        {allEmpty && !filtered && mode === 'active' && !loading && <div className="getting-started"><div><FolderOpen size={20} /><strong>Идея → Проект → Готовый трек</strong></div><p>Укажите название, привяжите папку и добавьте первый шаг.<br />Темп творчества задаёте вы.</p></div>}
        <div className="workspace-bottom"><span>Меньше поисков. Больше музыки.</span><span><span className="online-dot" />Данные хранятся на этом Mac</span></div>
      </div>
    </main>
    {selected && <Editor key={selected.id} project={selected} collections={collections} knownTags={overview.tags} busy={busy} changed={changed} run={run} dirtyChanged={dirtyChanged} close={() => navigate(() => { setSelected(null); setDirty(false); })} remove={() => setRemove(true)} />}
    {notice && <div className={`toast ${notice.error ? 'toast-error' : ''}`} role={notice.error ? 'alert' : 'status'}>{notice.error ? <span>!</span> : <Check size={17} />}<p>{notice.text}</p><button className="icon-button" onClick={() => setNotice(null)} aria-label="Закрыть уведомление"><X size={16} /></button></div>}
    {create && <Modal title="Новый проект" close={() => setCreate(false)} busy={busy}><CreateForm busy={busy} close={() => setCreate(false)} submit={async data => { await run(async () => { const project = await request<Project>('/projects', { method: 'POST', body: JSON.stringify(data) }); setMode('active'); setSearch(''); setStage(''); setGenre(''); setTag(''); setCollection(''); setSelected(project); setDirty(false); setCreate(false); refresh(); }); }} /></Modal>}
    {manageCollections && <Modal title="Подборки" close={() => setManageCollections(false)} busy={busy} wide><CollectionManager collections={collections} busy={busy} run={run} updated={() => {refresh(); if(selected) request<Project>(`/projects/${selected.id}`).then(setSelected).catch(() => {}); if(collection) setCollection('');}} /></Modal>}
    {settings && <Modal title="Настройки" close={() => setSettings(false)} busy={busy} wide><div className="settings-intro"><div className="summary-icon violet"><ShieldCheck size={23} /></div><div><h3>Ваша библиотека под рукой</h3><p>Проекты и задачи сохраняются автоматически после подтверждения изменений.</p></div></div><div className="settings-section"><h3>Резервное копирование</h3><p>Копия включает сохранённые проекты, задачи, заметки и пути к папкам. Музыкальные файлы остаются в своих папках.</p><button className="settings-action" disabled={busy} onClick={() => run(async () => { const result = await native('export_backup'); if (!result.cancelled) setNotice({ text: `Копия сохранена: ${result.value}`, error: false }); })}><Download size={20} /><div><strong>Сохранить резервную копию</strong><span>Выбрать место для файла базы</span></div><ChevronRight size={17} /></button><button className="settings-action" disabled={busy} onClick={() => run(async () => { const result = await native('prepare_restore'); if (!result.cancelled && result.value) { setSettings(false); setRestore(result.value); } })}><Upload size={20} /><div><strong>Восстановить из копии</strong><span>Текущая база будет сохранена перед заменой</span></div><ChevronRight size={17} /></button></div><div className="settings-about"><div className="brand-mark"><span /><span /><span /><span /><span /></div><div><strong>MusicFlow 0.2.0</strong><p>Личная музыкальная студия · macOS · офлайн</p></div></div></Modal>}
    {remove && selected && <Modal title="Удалить проект?" close={() => setRemove(false)} busy={busy}><p className="modal-description">Проект «{selected.title}», его задачи и заметки будут удалены навсегда. Файлы в папке проекта сохранятся.</p><div className="modal-actions"><button className="button secondary" disabled={busy} onClick={() => setRemove(false)}>Отмена</button><button className="button danger" disabled={busy} onClick={() => run(async () => { await request(`/projects/${selected.id}`, { method: 'DELETE' }); setSelected(null); setDirty(false); setRemove(false); refresh(); })}>Удалить проект</button></div></Modal>}
    {discard && <Modal title="Есть несохранённые изменения" close={() => setDiscard(null)}><p className="modal-description">Сохраните изменения в карточке проекта или продолжите без сохранения.</p><div className="modal-actions"><button className="button secondary" onClick={() => setDiscard(null)}>Вернуться к проекту</button><button className="button danger" onClick={() => { setSelected(null); setDirty(false); discard(); setDiscard(null); }}>Продолжить без сохранения</button></div></Modal>}
    {restore && <Modal title="Восстановить библиотеку?" close={() => setRestore(null)} busy={busy}><p className="modal-description">Будут загружены данные из «{restore}». Текущая база будет заменена; её защитная копия сохранится на Mac.{dirty && ' Несохранённые изменения в карточке будут потеряны.'}</p><div className="modal-actions"><button className="button secondary" disabled={busy} onClick={() => setRestore(null)}>Отмена</button><button className="button primary" disabled={busy} onClick={() => run(async () => { await native('restore_backup'); setSelected(null); setDirty(false); setRestore(null); setMode('active'); setSearch(''); setStage(''); setGenre(''); setTag(''); setCollection(''); setFileRevision(current => current+1); refresh(); setNotice({ text: 'Библиотека восстановлена из резервной копии.', error: false }); })}><Upload size={16} />Восстановить</button></div></Modal>}
  </div>;
}
