import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';
import type { Project, Stage } from './types';
import { stages } from './types';

export function StageBadge({ stage }: { stage: Stage }) {
  return <span className={`stage-badge stage-${stage}`}><i />{stages[stage]}</span>;
}

export function Progress({ project }: { project: Project }) {
  if (!project.task_count) return <span className="muted no-tasks">Нет задач</span>;
  return <div className="progress-cell"><div className="progress-label"><span>{project.completed_tasks}/{project.task_count}</span><span>{project.progress}%</span></div><div className="progress-track" role="progressbar" aria-label="Выполнение задач" aria-valuemin={0} aria-valuemax={100} aria-valuenow={project.progress ?? 0}><div style={{ width: `${project.progress}%`, height: 4 }} /></div></div>;
}

export function Modal({ title, children, close, busy = false, wide = false }: { title: string; children: ReactNode; close: () => void; busy?: boolean; wide?: boolean }) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = root.current!;
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]'));
    const first = dialog.querySelector<HTMLElement>('[data-autofocus]') ?? focusable()[0];
    first?.focus();
    return () => previous?.focus();
  }, []);
  return <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget && !busy) close(); }}>
    <div ref={root} className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title} onKeyDown={e => {
      if (e.key === 'Escape' && !busy) { e.stopPropagation(); close(); }
      if (e.key === 'Tab') {
        const elements = Array.from(root.current!.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]'));
        const first = elements[0], last = elements[elements.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
      }
    }}>
      <header><h2>{title}</h2><button type="button" className="icon-button" onClick={close} disabled={busy} aria-label="Закрыть окно"><X size={18} /></button></header>
      {children}
    </div>
  </div>;
}
