export type Stage = 'idea' | 'working' | 'mixing' | 'mastering' | 'done';
export const stages: Record<Stage, string> = { idea: 'Идея', working: 'В работе', mixing: 'Сведение', mastering: 'Мастеринг', done: 'Завершён' };
export const keys = ['C', 'C♯', 'D', 'D♯', 'E', 'F', 'F♯', 'G', 'G♯', 'A', 'A♯', 'B'].flatMap(k => [`${k} major`, `${k} minor`]);
export type Task = { id: number; title: string; completed: boolean; position: number };
export type Collection = { id: number; name: string; project_count: number };
export type Project = { id: number; title: string; bpm: number | null; musical_key: string | null; genre: string | null; status: Stage; notes: string; folder_path: string | null; archived: boolean; created_at: string; updated_at: string; tasks: Task[]; task_count: number; completed_tasks: number; progress: number | null; daw_path: string | null; preview_path: string | null; preview_auto: boolean; tags: string[]; collection_ids: number[]; collections: {id: number; name: string}[]; folder_size_bytes: number | null; folder_file_count: number | null; folder_scanned_at: string | null; folder_scan_partial: boolean; folder_unavailable: boolean; last_worked_at: string | null };
export type Overview = { active: number; archived: number; done: number; genres: string[]; tags: string[] };
export type FolderInfo = { state: 'empty' | 'pending' | 'ready' | 'partial' | 'missing' | 'error'; error: string | null; audio: {path: string; name: string; size: number; mtime: number; score: number}[]; project: Project };
export type NativeResult = { ok: boolean; cancelled?: boolean; value?: string | null; folder?: string; error?: string; missing?: boolean };
export type Bridge = {
  set_dirty(dirty: boolean): Promise<NativeResult>;
  choose_folder(): Promise<NativeResult>;
  open_project_folder(id: number): Promise<NativeResult>;
  choose_daw_file(id: number): Promise<NativeResult>;
  choose_audio_file(id: number): Promise<NativeResult>;
  open_daw_project(id: number): Promise<NativeResult>;
  export_backup(): Promise<NativeResult>;
  prepare_restore(): Promise<NativeResult>;
  restore_backup(): Promise<NativeResult>;
};
declare global {
  interface Window { pywebview?: { token: string; api: Bridge }; musicflowUnsaved?: boolean; }
}
