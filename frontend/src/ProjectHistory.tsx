import { useEffect, useMemo, useState } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight, Clock3, FilePenLine, Pencil, Plus, Trash2 } from 'lucide-react';
import { request } from './api';
import { Modal } from './components';
import type { ActivityEvent, Project } from './types';

export const dayKey = (date: Date) => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
const localInput = (date: Date) => `${dayKey(date)}T${String(date.getHours()).padStart(2,'0')}:${String(date.getMinutes()).padStart(2,'0')}`;
const fullDate = (date: Date) => date.toLocaleDateString('ru-RU', {day:'numeric',month:'long',year:'numeric'});
const durationLabel = (minutes: number) => `${Math.floor(minutes/60) ? `${Math.floor(minutes/60)} ч ` : ''}${minutes%60 ? `${minutes%60} мин` : ''}`.trim();
const eventCount = (count: number) => `${count} ${count%100>=11&&count%100<=14 ? 'событий' : count%10===1 ? 'событие' : count%10>=2&&count%10<=4 ? 'события' : 'событий'}`;
const valueLabel = (value: unknown) => value === null || value === '' ? 'Не указано' : Array.isArray(value) ? value.join(', ') || 'Пусто' : typeof value === 'boolean' ? value ? 'Да' : 'Нет' : String(value);
const fieldLabels: Record<string,string> = {title:'Название',bpm:'BPM',musical_key:'Тональность',genre:'Жанр',notes:'Заметки',folder_path:'Папка',daw_path:'Файл DAW',preview_path:'Демка',preview_auto:'Автопоиск',tags:'Теги',collections:'Подборки'};

type Props = {project: Project; active: boolean; busy: boolean; run: (action:()=>Promise<void>)=>Promise<boolean>; dirtyChanged:(value:boolean)=>void; changed:(project:Project)=>void};
type Draft = {summary:string; occurred_at:string; duration:string};

export default function ProjectHistory({project, active, busy, run, dirtyChanged, changed}: Props) {
  const today = new Date();
  const [month, setMonth] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1));
  const [selectedDay, setSelectedDay] = useState<string|null>(() => dayKey(today));
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [truncated, setTruncated] = useState(false);
  const [revision, setRevision] = useState(0);
  const [form, setForm] = useState<{id:number|null; initial:Draft}|null>(null);
  const [draft, setDraft] = useState<Draft>({summary:'',occurred_at:'',duration:''});
  const [discard, setDiscard] = useState(false);
  const [deleting, setDeleting] = useState<ActivityEvent|null>(null);
  const dirty = !!form && JSON.stringify(draft) !== JSON.stringify(form.initial);
  useEffect(() => {dirtyChanged(dirty);}, [dirty,dirtyChanged]);
  useEffect(() => () => dirtyChanged(false), [dirtyChanged]);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    const until = new Date(month.getFullYear(),month.getMonth()+1,1);
    const params = new URLSearchParams({since:month.toISOString(),until:until.toISOString()});
    setLoading(true); setError('');
    request<{events:ActivityEvent[];truncated:boolean}>(`/projects/${project.id}/history?${params}`,{signal:controller.signal})
      .then(result => {if(!controller.signal.aborted) {setEvents(result.events);setTruncated(result.truncated);}})
      .catch(reason => {if(!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Не удалось загрузить историю.');})
      .finally(() => {if(!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [active,project.id,project.updated_at,project.folder_scanned_at,month,revision]);

  const byDay = useMemo(() => {
    const days = new Map<string,ActivityEvent[]>();
    for(const item of events) {const key=dayKey(new Date(item.occurred_at)); days.set(key,[...(days.get(key)||[]),item]);}
    return days;
  }, [events]);
  const visible = selectedDay ? byDay.get(selectedDay)||[] : events;
  const daysInMonth = new Date(month.getFullYear(),month.getMonth()+1,0).getDate();
  const offset = (month.getDay()+6)%7;
  const moveMonth = (offset:number) => {setMonth(new Date(month.getFullYear(),month.getMonth()+offset,1));setSelectedDay(null);setEvents([]);};
  const selectToday = () => {const date=new Date();setMonth(new Date(date.getFullYear(),date.getMonth(),1));setSelectedDay(dayKey(date));};
  const openForm = (entry?:ActivityEvent) => {
    const date = entry ? new Date(entry.occurred_at) : selectedDay ? new Date(`${selectedDay}T${localInput(new Date()).slice(11)}`) : new Date();
    const initial={summary:entry?.summary||'',occurred_at:localInput(date),duration:entry?.duration_minutes ? String(entry.duration_minutes) : ''};
    setDraft(initial);setForm({id:entry?.id||null,initial});setDiscard(false);
  };
  const closeForm = () => {if(dirty) setDiscard(true);else setForm(null);};
  const save = (event:React.FormEvent) => {
    event.preventDefault();
    run(async () => {
      const item = await request<ActivityEvent>(`/projects/${project.id}/history${form?.id ? `/${form.id}` : ''}`, {method:form?.id ? 'PUT' : 'POST',body:JSON.stringify({summary:draft.summary,occurred_at:new Date(draft.occurred_at).toISOString(),duration_minutes:draft.duration ? Number(draft.duration) : null})});
      const date=new Date(item.occurred_at);
      setMonth(new Date(date.getFullYear(),date.getMonth(),1));setSelectedDay(dayKey(date));setForm(null);setRevision(value=>value+1);
      changed(await request<Project>(`/projects/${project.id}`));
    });
  };

  return <section className="history-view" aria-label="История проекта" hidden={!active}>
    <div className="history-heading"><div><h2>История работы</h2><p>Каждый шаг к готовому треку.</p></div><button className="button primary" onClick={()=>openForm()} disabled={busy}><Plus size={17}/>Записать результат работы</button></div>
    <div className="history-layout">
      <section className="project-calendar" aria-label="Календарь работы">
        <header><h3>{month.toLocaleDateString('ru-RU',{month:'long',year:'numeric'})}</h3><div><button className="icon-button" aria-label="Предыдущий месяц" onClick={()=>moveMonth(-1)}><ChevronLeft size={18}/></button><button className="button subtle small" onClick={selectToday}>Сегодня</button><button className="icon-button" aria-label="Следующий месяц" onClick={()=>moveMonth(1)}><ChevronRight size={18}/></button></div></header>
        <div className="calendar-weekdays">{['ПН','ВТ','СР','ЧТ','ПТ','СБ','ВС'].map(day=><span key={day}>{day}</span>)}</div>
        <div className="calendar-days">{Array.from({length:offset},(_,i)=><span key={`empty-${i}`} aria-hidden="true"/>)}{Array.from({length:daysInMonth},(_,i)=>{
          const date=new Date(month.getFullYear(),month.getMonth(),i+1),key=dayKey(date),items=byDay.get(key)||[];
          return <button key={key} id={`day-${key}`} className={`calendar-day ${key===selectedDay ? 'selected' : ''} ${key===dayKey(today) ? 'today' : ''}`} aria-label={`${fullDate(date)}${items.length ? `, событий: ${items.length}` : ', нет событий'}`} aria-pressed={key===selectedDay} onClick={()=>setSelectedDay(key)} onKeyDown={event=>{
            const step=({ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7} as Record<string,number>)[event.key];
            if(step) {event.preventDefault();const next=new Date(date);next.setDate(date.getDate()+step);setSelectedDay(dayKey(next));if(next.getMonth()!==month.getMonth()||next.getFullYear()!==month.getFullYear()) setMonth(new Date(next.getFullYear(),next.getMonth(),1));requestAnimationFrame(()=>document.getElementById(`day-${dayKey(next)}`)?.focus());}
          }}><span>{i+1}</span><div className="calendar-markers" aria-hidden="true">{items.some(item=>item.kind==='manual')&&<i className="manual-dot"/>}{items.some(item=>item.kind==='task_completed')&&<i className="task-dot"/>}{items.some(item=>item.kind!=='manual'&&item.kind!=='task_completed')&&<i className="change-dot"/>}</div></button>;
        })}</div>
        <div className="calendar-legend"><span><i className="manual-dot"/>Запись</span><span><i className="task-dot"/>Задача выполнена</span><span><i className="change-dot"/>Изменение</span></div>
        <p className="history-hint">История накапливается с обновления MusicFlow. Предыдущую работу можно добавить вручную.</p>
      </section>
      <section className="activity-panel" aria-label="Журнал событий">
        <header><div><h3>{selectedDay ? fullDate(new Date(`${selectedDay}T12:00`)) : 'Весь месяц'}</h3><span>{loading ? 'Загружаем…' : eventCount(visible.length)}</span></div>{selectedDay&&<button className="button subtle small" onClick={()=>setSelectedDay(null)}>Весь месяц</button>}</header>
        {error ? <div className="history-empty"><p className="field-error">{error}</p><button className="button secondary" onClick={()=>setRevision(value=>value+1)}>Повторить</button></div> : loading ? <div className="history-empty"><CalendarDays size={25}/><p>Загружаем историю…</p></div> : visible.length ? <ol className="activity-list">{visible.map(item=><li key={item.id} className={`activity-item kind-${item.kind}`}><div className="event-marker">{item.kind==='manual' ? <FilePenLine size={16}/> : <span/>}</div><div className="event-content"><div className="event-meta"><time dateTime={item.occurred_at}>{selectedDay ? new Date(item.occurred_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}) : new Date(item.occurred_at).toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})}</time><span>{item.kind==='manual' ? 'Запись о работе' : item.kind==='daw_saved'||item.kind==='demo_updated' ? 'По файлу' : 'MusicFlow'}</span>{item.duration_minutes&&<span><Clock3 size={12}/>{durationLabel(item.duration_minutes)}</span>}</div><p>{item.summary}</p>{item.details.changes&&<details className="event-details"><summary>Что изменилось</summary>{Object.entries(item.details.changes).map(([key,change])=><div key={key}><strong>{fieldLabels[key]||key}</strong><span>{valueLabel(change.before)} → {valueLabel(change.after)}</span></div>)}</details>}{(item.kind==='daw_saved'||item.kind==='demo_updated')&&<small className="event-observed">Обнаружено {new Date(item.recorded_at).toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})}. Дата события — по сохранению файла.</small>}</div>{item.kind==='manual'&&<div className="event-actions"><button className="icon-button" aria-label="Изменить запись" disabled={busy} onClick={()=>openForm(item)}><Pencil size={14}/></button><button className="icon-button danger-hover" aria-label="Удалить запись" disabled={busy} onClick={()=>setDeleting(item)}><Trash2 size={14}/></button></div>}</li>)}</ol> : <div className="history-empty"><CalendarDays size={28}/><h3>Пока нет записей</h3><p>Здесь появятся изменения проекта и результаты твоей работы.</p><button className="button secondary" disabled={busy} onClick={()=>openForm()}>Добавить запись</button></div>}
        {truncated&&<p className="field-error">Показаны последние 5000 событий месяца.</p>}
      </section>
    </div>
    {form&&<Modal title={discard ? 'Не сохранять запись?' : form.id ? 'Изменить запись о работе' : 'Результат работы'} close={discard ? ()=>setDiscard(false) : closeForm} busy={busy} wide>{discard ? <><p className="modal-description">Введённый текст будет потерян.</p><div className="modal-actions"><button className="button secondary" onClick={()=>setDiscard(false)}>Продолжить запись</button><button className="button danger" onClick={()=>{setForm(null);setDiscard(false);}}>Не сохранять</button></div></> : <form onSubmit={save}><p className="modal-description">Что удалось сделать и с чего продолжить в следующий раз?</p><label>Описание работы<textarea data-autofocus value={draft.summary} maxLength={5000} required placeholder="Например, записал припев и поправил переход…" onChange={event=>setDraft({...draft,summary:event.target.value})} disabled={busy}/></label><div className="field-pair"><label>Дата и время<input type="datetime-local" value={draft.occurred_at} max={localInput(new Date())} required onChange={event=>setDraft({...draft,occurred_at:event.target.value})} disabled={busy}/></label><label>Длительность, минут · необязательно<input type="number" min={1} max={1440} step={1} value={draft.duration} placeholder="Например, 45" onChange={event=>setDraft({...draft,duration:event.target.value})} disabled={busy}/></label></div><div className="modal-actions"><button type="button" className="button secondary" onClick={closeForm} disabled={busy}>Отмена</button><button className="button primary" disabled={busy||!draft.summary.trim()||!draft.occurred_at}>Сохранить запись</button></div></form>}</Modal>}
    {deleting&&<Modal title="Удалить запись о работе?" close={()=>setDeleting(null)} busy={busy}><p className="modal-description">Эта запись будет удалена навсегда. Проект, задачи и файлы сохранятся.</p><div className="modal-actions"><button className="button secondary" disabled={busy} onClick={()=>setDeleting(null)}>Отмена</button><button className="button danger" disabled={busy} onClick={()=>run(async()=>{await request(`/projects/${project.id}/history/${deleting.id}`,{method:'DELETE'});setDeleting(null);setRevision(value=>value+1);changed(await request<Project>(`/projects/${project.id}`));})}>Удалить запись</button></div></Modal>}
  </section>;
}
