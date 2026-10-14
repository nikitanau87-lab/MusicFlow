import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { stages } from './types';
import type { Collection, Project } from './types';

const api = vi.hoisted(() => ({ request: vi.fn(), native: vi.fn(), ensureMediaSession: vi.fn().mockResolvedValue({ready:true}) }));
vi.mock('./api', () => api);
let projects: Project[];
let collectionsData: Collection[];

function project(id: number, title: string): Project {
  return { id, title, bpm: 120, musical_key: 'A minor', genre: 'House', status: 'idea', notes: '', folder_path: null, archived: false, created_at: '2026-10-14T12:00:00Z', updated_at: '2026-10-14T12:00:00Z', tasks: [], task_count: 0, completed_tasks: 0, progress: null, daw_path:null, preview_path:null, preview_auto:true, tags:[], collection_ids:[], collections:[], folder_size_bytes:null, folder_file_count:null, folder_scanned_at:null, folder_scan_partial:false, folder_unavailable:false, last_worked_at:null };
}

beforeEach(() => {
  projects = [];
  collectionsData = [];
  api.request.mockReset(); api.native.mockReset(); api.native.mockResolvedValue({ ok: true });
  api.request.mockImplementation(async (path: string, options: RequestInit = {}) => {
    if (path === '/collections') {
      if (options.method === 'POST') {const item={id:collectionsData.length+1, name:JSON.parse(options.body as string).name, project_count:0}; collectionsData.push(item); return structuredClone(item);}
      return structuredClone(collectionsData);
    }
    if (path === '/files/refresh' || path === '/files/status') return {pending:0};
    if (path === '/overview') return { active: projects.filter(p => !p.archived).length, archived: projects.filter(p => p.archived).length, done: projects.filter(p => p.status === 'done').length, genres: ['House'], tags: [...new Set(projects.flatMap(p => p.tags))] };
    if (path.startsWith('/projects?')) {
      const params = new URLSearchParams(path.split('?')[1]);
      return structuredClone(projects.filter(p => p.archived === (params.get('archived') === 'true') && p.title.toLowerCase().includes((params.get('search') || '').toLowerCase()) && (!params.get('status') || p.status === params.get('status')) && (!params.get('tag') || p.tags.includes(params.get('tag')!)) && (!params.get('collection_id') || p.collection_ids.includes(Number(params.get('collection_id'))))));
    }
    if (path === '/projects' && options.method === 'POST') {
      const created = { ...project(projects.length + 1, ''), ...JSON.parse(options.body as string) };
      projects.push(created); return structuredClone(created);
    }
    const id = Number(path.split('/')[2]);
    const item = projects.find(p => p.id === id)!;
    if(path.endsWith('/folder-info') || path.includes('/folder-info?')) return {state:'empty', audio:[], error:null, project:structuredClone(item)};
    if (options.method === 'PATCH') Object.assign(item, JSON.parse(options.body as string));
    return structuredClone(item);
  });
});

describe('MusicFlow interaction', () => {
  it('creates a project from the empty state and opens its card', async () => {
    const user = userEvent.setup(); render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Создать первый проект' }));
    const dialog = screen.getByRole('dialog', { name: 'Новый проект' });
    await user.type(within(dialog).getByPlaceholderText('Как назовём новый трек?'), 'Ночной трек');
    await user.click(within(dialog).getByRole('button', { name: 'Создать проект' }));
    expect(await screen.findByRole('button', { name: 'Открыть проект: Ночной трек' })).toBeTruthy();
    expect(screen.getByRole('complementary', { name: 'Карточка проекта' })).toBeTruthy();
    expect(screen.getByText('Нет задач')).toBeTruthy();
  });

  it('protects unsaved edits and saves a manual stage independently of tasks', async () => {
    projects = [project(1, 'Тест')]; const user = userEvent.setup(); render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Открыть проект: Тест' }));
    const title = screen.getByLabelText('Название трека');
    await user.clear(title); await user.type(title, 'Изменённый');
    await user.click(screen.getByRole('button', { name: 'Закрыть карточку' }));
    expect(screen.getByRole('dialog', { name: 'Есть несохранённые изменения' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Вернуться к проекту' }));
    await user.selectOptions(screen.getByLabelText('Стадия'), 'done');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(projects[0].title).toBe('Изменённый'));
    expect(projects[0].status).toBe('done'); expect(projects[0].task_count).toBe(0);
    expect(await screen.findByRole('button', { name: 'Открыть проект: Изменённый' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Закрыть карточку' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('shows combined search and stage filters and can clear an empty result', async () => {
    projects = [project(1, 'Ночь'), { ...project(2, 'Утро'), status: 'done' }];
    const user = userEvent.setup(); render(<App />);
    await screen.findByRole('button', { name: 'Открыть проект: Утро' });
    await user.selectOptions(screen.getByLabelText('Фильтр по стадии'), 'done');
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Открыть проект: Ночь' })).toBeNull());
    await user.type(screen.getByLabelText('Поиск проектов'), 'Ночь');
    expect(await screen.findByText('Ничего не найдено')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Сбросить фильтры' }));
    expect(await screen.findByRole('button', { name: 'Открыть проект: Ночь' })).toBeTruthy();
  });

  it('handles a cancelled native backup without claiming success', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByRole('button', { name: 'Создать первый проект' });
    await user.click(screen.getByRole('button', { name: 'Настройки' }));
    api.native.mockResolvedValue({ ok: true, cancelled: true });
    await user.click(screen.getByRole('button', { name: /Сохранить резервную копию/ }));
    await waitFor(() => expect(api.native).toHaveBeenCalledWith('export_backup'));
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('reports failed writes and keeps entered text for retry', async () => {
    const user = userEvent.setup(); render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Создать первый проект' }));
    await user.type(screen.getByPlaceholderText('Как назовём новый трек?'), 'Не потерять');
    const original = api.request.getMockImplementation()!;
    api.request.mockImplementation((path: string, options?: RequestInit) => options?.method === 'POST' ? Promise.reject(new Error('Нет доступа к базе')) : original(path, options));
    await user.click(screen.getByRole('button', { name: 'Создать проект' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect((screen.getByPlaceholderText('Как назовём новый трек?') as HTMLInputElement).value).toBe('Не потерять');
  });

  it('saves tags and membership, then filters the library by a tag', async () => {
    projects=[project(1,'Ночь')]; collectionsData=[{id:5,name:'Первый EP',project_count:0}];
    const user=userEvent.setup(); render(<App />);
    await user.click(await screen.findByRole('button',{name:'Открыть проект: Ночь'}));
    await user.type(screen.getByLabelText('Новый тег'),'ночной{Enter}');
    await user.click(screen.getByRole('checkbox',{name:'Первый EP'}));
    await user.click(screen.getByRole('button',{name:'Сохранить'}));
    await waitFor(() => expect(projects[0].tags).toEqual(['ночной']));
    expect(projects[0].collection_ids).toEqual([5]);
    await user.click(screen.getByRole('button',{name:'Закрыть карточку'}));
    await user.selectOptions(screen.getByLabelText('Фильтр по тегу'),'ночной');
    expect(await screen.findByRole('button',{name:'Открыть проект: Ночь'})).toBeTruthy();
  });

  it('creates a collection from the sidebar manager', async () => {
    const user=userEvent.setup(); render(<App />);
    await screen.findByRole('button',{name:'Создать первый проект'});
    await user.click(screen.getByRole('button',{name:'Управлять подборками'}));
    await user.type(screen.getByLabelText('Название новой подборки'),'EP 2026');
    await user.click(screen.getByRole('button',{name:'Создать'}));
    await waitFor(() => expect(collectionsData[0].name).toBe('EP 2026'));
    expect(await screen.findByRole('button',{name:'Переименовать подборку: EP 2026'})).toBeTruthy();
  });

  it('shows discovered demo audio without overwriting unsaved title edits', async () => {
    projects=[{...project(1,'Трек'),folder_path:'/tmp/music'}];
    const original=api.request.getMockImplementation()!;
    let finish: (value: unknown) => void = () => {};
    api.request.mockImplementation((path:string,options?:RequestInit) => path.includes('/folder-info') ? new Promise(resolve => {finish=resolve;}) : original(path,options));
    const user=userEvent.setup(); render(<App />);
    await user.click(await screen.findByRole('button',{name:'Открыть проект: Трек'}));
    const title=screen.getByLabelText('Название трека');
    await user.clear(title); await user.type(title,'Не потерять название');
    const discovered={...projects[0],preview_path:'/tmp/music/demo.wav',folder_size_bytes:32000};
    await act(async () => finish({state:'ready',error:null,audio:[{path:discovered.preview_path,name:'demo.wav',mtime:100,size:32000,score:100}],project:discovered}));
    expect((title as HTMLInputElement).value).toBe('Не потерять название');
    expect(await screen.findByLabelText('Прослушать демку')).toBeTruthy();
    expect((screen.getByLabelText('Прослушать демку') as HTMLAudioElement).src).toContain('/api/projects/1/audio');
    expect(api.ensureMediaSession).toHaveBeenCalled();
  });

  it('uses audio metadata for seeking and volume controls', async () => {
    projects=[{...project(1,'Демка'),preview_path:'/tmp/demo.wav'}];
    const user=userEvent.setup(); render(<App />);
    await user.click(await screen.findByRole('button',{name:'Открыть проект: Демка'}));
    const media=await screen.findByLabelText('Прослушать демку') as HTMLAudioElement;
    Object.defineProperty(media,'duration',{configurable:true,value:45});
    fireEvent.loadedMetadata(media);
    expect((screen.getByLabelText('Позиция воспроизведения') as HTMLInputElement).max).toBe('45');
    fireEvent.change(screen.getByLabelText('Позиция воспроизведения'),{target:{value:'13'}});
    expect(media.currentTime).toBe(13);
    expect(screen.getByText('0:13')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Громкость демки'),{target:{value:'0.4'}});
    expect(media.volume).toBe(.4);
    fireEvent.play(media);
    expect(screen.getByRole('button',{name:'Пауза демки'})).toBeTruthy();
    fireEvent.pause(media);
    expect(screen.getByRole('button',{name:'Воспроизвести демку'})).toBeTruthy();
  });
});
