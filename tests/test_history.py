import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from musicflow.api import create_app
from musicflow.database import Database


@pytest.fixture
def library(tmp_path):
    database = Database(tmp_path / 'data')
    app = create_app(database, 'token')
    with TestClient(app, headers={'X-MusicFlow-Token': 'token'}) as client:
        yield client, database, tmp_path, app
    database.engine.dispose()


def period(client, project=1, since=None, until=None):
    today = datetime.now(timezone.utc)
    result = client.get(f'/api/projects/{project}/history', params={'since': (since or today-timedelta(days=1)).isoformat(), 'until': (until or today+timedelta(days=1)).isoformat()})
    assert result.status_code == 200, result.text
    return result.json()['events']


def scan(client, project=1):
    result = client.get(f'/api/projects/{project}/folder-info?refresh=true').json()
    deadline = time.monotonic()+5
    while result['state'] == 'pending':
        assert time.monotonic() < deadline
        time.sleep(.01)
        result = client.get(f'/api/projects/{project}/folder-info').json()
    return result


def test_project_and_task_events_noops_and_cascade(library):
    client, database, _, _ = library
    client.post('/api/projects', json={'title': 'Ночь'})
    client.patch('/api/projects/1', json={'title': 'Ночь', 'status': 'idea'})
    assert len(period(client)) == 1
    client.patch('/api/projects/1', json={'status':'mixing','notes':'Записан вокал','tags':['демка']})
    task = client.post('/api/projects/1/tasks', json={'title':'Свести трек'}).json()['tasks'][0]
    client.patch(f"/api/projects/1/tasks/{task['id']}", json={'completed':True})
    client.patch(f"/api/projects/1/tasks/{task['id']}", json={'completed':True})
    events = period(client)
    assert [item['kind'] for item in reversed(events)] == ['project_created','status_changed','project_updated','task_added','task_completed']
    changed = next(item for item in events if item['kind']=='project_updated')
    assert changed['details']['changes']['notes'] == {'before':'','after':'Записан вокал'}
    automatic = events[0]['id']
    assert client.delete(f'/api/projects/1/history/{automatic}').status_code == 403
    client.delete('/api/projects/1')
    with sqlite3.connect(database.path) as db:
        assert db.execute('select count(*) from activity_events').fetchone()[0] == 0


def test_manual_timezones_crud_validation_and_isolation(library):
    client, _, _, _ = library
    client.post('/api/projects', json={'title':'Ночь'})
    client.post('/api/projects', json={'title':'Утро'})
    entry = {'summary':'Записал припев', 'occurred_at':'2025-12-31T23:30:00-03:00','duration_minutes':45}
    response = client.post('/api/projects/1/history', json=entry)
    assert response.status_code == 201
    item = response.json()
    assert item['occurred_at']=='2026-01-01T02:30:00Z'
    start=datetime(2026,1,1,tzinfo=timezone.utc);end=start+timedelta(days=1)
    assert period(client,since=start,until=end)[0]['summary']=='Записал припев'
    assert period(client,project=2,since=start,until=end)==[]
    assert client.put(f"/api/projects/2/history/{item['id']}",json=entry).status_code==404
    assert client.delete(f"/api/projects/2/history/{item['id']}").status_code==404
    for fields in ({'summary':' '},{'occurred_at':'2026-01-01T02:30:00'},{'occurred_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()},{'duration_minutes':0},{'duration_minutes':1441},{'duration_minutes':1.5}):
        assert client.post('/api/projects/1/history',json={**entry,**fields}).status_code==422
    result=client.put(f"/api/projects/1/history/{item['id']}",json={**entry,'summary':'Записал и свёл припев','duration_minutes':60}).json()
    assert result['summary']=='Записал и свёл припев' and result['duration_minutes']==60
    assert result['recorded_at']==item['recorded_at']
    client.delete(f"/api/projects/1/history/{item['id']}")
    assert period(client,since=start,until=end)==[]
    assert client.get('/api/projects/1/history',params={'since':start.isoformat(),'until':(start+timedelta(days=33)).isoformat()}).status_code==422
    assert client.get('/api/projects/1/history',params={'since':'2026-01-01','until':end.isoformat()}).status_code==422
    assert client.get('/api/projects/1/history',params={'since':start.isoformat(),'until':end.isoformat()},headers={'X-MusicFlow-Token':'bad'}).status_code==403


def test_file_baseline_survives_restart_and_does_not_repeat(library):
    client, database, tmp, app = library
    folder=tmp/'Трек';folder.mkdir()
    daw=folder/'Трек.flp';daw.write_bytes(b'old')
    demo=folder/'demo.wav';demo.write_bytes(b'old-demo')
    client.post('/api/projects',json={'title':'Трек','folder_path':str(folder),'daw_path':str(daw)})
    scan(client)
    assert len(period(client))==1
    scan(client)
    assert len(period(client))==1
    # Saving unchanged parameters must not reset the observation baseline.
    client.patch('/api/projects/1',json={'title':'Трек','folder_path':str(folder),'daw_path':str(daw)})
    daw.write_bytes(b'new DAW version');demo.write_bytes(b'new demo version')
    scan(client)
    kinds=[item['kind'] for item in period(client)]
    assert kinds.count('daw_saved')==1 and kinds.count('demo_updated')==1
    scan(client)
    assert len(period(client))==3
    # A newly created scanner loads the persisted baseline, rather than fabricating history.
    from musicflow.files import FolderScanner
    scanner=FolderScanner(database)
    try:
        scanner.get(1,True)
        deadline=time.monotonic()+5
        while scanner.pending():
            assert time.monotonic()<deadline
            time.sleep(.01)
        assert len(period(client))==3
    finally:
        scanner.close()
    daw.unlink()
    scan(client)
    assert len(period(client))==3


def test_history_backup_and_damaged_event_rejected(library):
    client,database,tmp,_=library
    client.post('/api/projects',json={'title':'Трек'})
    client.post('/api/projects/1/history',json={'summary':'Бит готов','occurred_at':(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),'duration_minutes':30})
    copy=tmp/'history.sqlite3';database.backup(copy)
    events=period(client)
    database.restore(copy)
    assert period(client)==events
    with sqlite3.connect(copy) as db:
        db.execute("update activity_events set kind='fake'")
    before=database.path.read_bytes()
    with pytest.raises(ValueError):database.restore(copy)
    assert database.path.read_bytes()==before


def test_v02_migration_and_restore_keep_fields_without_invented_events(library):
    client,database,tmp,_=library
    old=tmp/'old.sqlite3'
    engine=create_engine(f'sqlite:///{old}')
    config=Config();config.set_main_option('script_location',str(Path('musicflow/migrations').resolve()))
    with engine.begin() as connection:
        config.attributes['connection']=connection
        command.upgrade(config,'0002')
        connection.exec_driver_sql("INSERT INTO projects (title,status,notes,archived,created_at,updated_at,tags) VALUES ('Редкость','working','Идея',0,'2026-01-01 00:00:00','2026-01-01 00:00:00','[\"ночь\"]')")
    engine.dispose()
    assert Database.validate_backup(old)=='0002'
    original=old.read_bytes()
    database.restore(old)
    assert old.read_bytes()==original and Database.validate_backup(database.path)=='0003'
    project=client.get('/api/projects/1').json()
    assert project['title']=='Редкость' and project['tags']==['ночь']
    assert period(client)==[]
