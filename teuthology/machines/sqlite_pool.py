from typing import Any

import functools
import contextlib
import logging
import sqlite3
import time

from teuthology.config import config
from teuthology.machines.base import MachinePool


log = logging.getLogger(__name__)


class TooFewMachines(Exception):
    pass


class _SqliteDBManager:
    def __init__(self, path: str) -> None:
        assert path
        self._path = path
        self._connect()
        self._create_tables()
        self.automatic_release = False

    def _connect(self) -> None:
        path = self._path
        if path.startswith('sqlite://'):
            path = path[9:]
        if path.startswith('sqlite:'):
            path = path[7:]
        log.info("sqlite3 db path: %s", path)
        self._conn = sqlite3.connect(path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row

    def _create_tables(self) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS machines (
                        name TEXT UNIQUE,
                        machine_type TEXT,
                        up INTEGER,
                        in_use INTEGER,
                        cookie TEXT,
                        info JSON
                    )
                    """
                )
        except sqlite3.OperationalError:
            pass

    @contextlib.contextmanager
    def _tx(self):
        try:
            cur = self._conn.cursor()
            cur.execute('BEGIN;')
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()

    def select(
        self,
        *,
        machine_type: str | None = None,
        up: bool | None = None,
        locked: bool | None = None,
        cookie: str | None = None,
        limit: int | None = None,
    ):
        query = "SELECT name, machine_type, up, in_use, cookie, info FROM machines"
        where = _Where()
        where.add_if('machine_type', machine_type)
        where.add_if('up', up)
        where.add_if('in_use', locked)
        where.add_if('cookie', cookie)
        where_params = where.parameters()
        if where_params:
            query += f' {where}'
        if limit is not None:
            query += ' LIMIT ' + str(int(limit))

        with self._tx() as cur:
            cur.execute(query, tuple(where_params))
            rows = cur.fetchall()
            log.info("Rows: %r", rows)
        return rows

    def add_machine(self, name, machine_type, info):
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO machines VALUES (?,?, 1, 0, '', ?)",
                (name, machine_type, info),
            )

    def remove_machine(self, name):
        with self._tx() as cur:
            cur.execute("DELETE FROM machines WHERE name=?", (name,))

    def remove_all_machines(self):
        with self._tx() as cur:
            cur.execute('DELETE FROM machines')

    def take(self, machine_type: str, count: int, cookie: str):
        count = int(count)
        query = "UPDATE machines SET in_use=1, cookie=? WHERE rowid IN (SELECT rowid FROM machines WHERE in_use=0 AND machine_type=? LIMIT ?)"
        with self._tx() as cur:
            cur.execute(query, (cookie, machine_type, count))
            if cur.rowcount != count:
                raise TooFewMachines()

    def release(self, name: str, cookie: str | None = None) -> bool:
        if not self.automatic_release:
            return False
        where = _Where()
        where.add_if('name', name)
        where.add_if('cookie', cookie)
        query = f'UPDATE machines SET in_use=0, cookie="" {where}'
        with self._tx() as cur:
            cur.execute(query, tuple(where.parameters()))
            modified = cur.rowcount >= 1
        return modified


class _Where:
    def __init__(self):
        self._where = []

    def add(self, key: str, value: Any) -> None:
        self._where.append((key, value))

    def add_if(self, key: str, value: Any) -> None:
        if value is not None:
            self.add(key, value)

    def __str__(self) -> str:
        wh = ' AND '.join(f'{k}=?' for k, _ in self._where)
        return f'WHERE ({wh})'

    def parameters(self) -> list[Any]:
        return [v for _, v in self._where]


def _job_cookie(ctx: Any, user: str, description: str) -> str:
    """Create a compact string describing the job. Cache said
    string on the ctx if the ctx is valid.
    """
    cookie = getattr(ctx, 'job_cookie', None)
    if cookie is None:
        user = user or 'default'
        description = description or 'missing'
        cookie = f"{user}/{description}"
        if ctx:
            setattr(ctx, "job_cookie", None)
    return cookie


def _track(fn):
    functools.wraps(fn)

    def _fn(*args, **kwargs):
        log.warning('CALLING sqlite_pool fn %s: %r, %r', fn, args, kwargs)
        result = fn(*args, **kwargs)
        log.warning('CALLED sqlite_pool fn %s, got %r', fn, result)
        return result

    return _fn



class SqliteMachinePool(MachinePool):
    def __init__(self, *, path=None):
        if not path:
            path = config.machine_pool
        self.dbmgr = _SqliteDBManager(path)
        self._delay_sec = 15

    def description(self) -> str:
        return "Machine Pool Managed via Local SQLite3 DB"

    @_track
    def list(
        self,
        machine_type=None,
        up=None,
        locked=None,
        count=None,
        tries=None,
    ):
        return {v['name']:None for v in self._list()}

    def _list(
        self,
        machine_type=None,
        up=None,
        locked=None,
        count=None,
        tries=None,
    ):
        result = {
            v
            for v in self.dbmgr.select(
                machine_type=machine_type, up=up, locked=locked, limit=count
            )
        }
        return result

    @_track
    def everything(self):
        return [dict(v) for v in self.dbmgr.select()]

    @_track
    def reserve(
        self,
        ctx,
        num,
        machine_type,
        user=None,
        description=None,
        os_type=None,
        os_version=None,
        arch=None,
        reimage=True,
        min_spare: int = 0,
    ) -> None:
        while True:
            available = self.dbmgr.select(
                machine_type=machine_type,
                up=True,
                locked=False,
                limit=(num + min_spare),
            )
            if len(available) < (num + min_spare):
                log.info(
                    'too few free nodes: requested %d, need %d spare, have %d',
                    num,
                    min_spare,
                    len(available),
                )
                time.sleep(self._delay_sec)
                continue
            cookie = _job_cookie(ctx, user, description)
            try:
                self.dbmgr.take(
                    machine_type,
                    num,
                    cookie,
                )
            except TooFewMachines:
                log.warning('too few nodes to take (possible race)')
                time.sleep(self._delay_sec)
                continue
            reserved = self.dbmgr.select(
                machine_type=machine_type,
                up=True,
                locked=True,
                cookie=cookie,
            )
            assert num == len(reserved), f"needed {num} machines, got {len(reserved)}"
            ctx.config['targets'] = {v['name']: None for v in reserved}
            return

    @_track
    def release(
        self,
        ctx,
        name,
        user=None,
        description=None,
        status_hint=None,
        constraints=None,
    ) -> bool:
        # TODO constraints
        return self.dbmgr.release(name)

    @_track
    def is_vm(self, name: str) -> bool:
        # always return false. this may be a lie, but teuthology's
        # meaning of is_vm doesn't really mean it's actually a vm, but
        # that it needs special handling. It doesn't, because this
        # machine pool abstracts that away.
        return False

    @_track
    def statuses(self, machines: 'list[str]') -> 'list[dict]':
        out = []
        for v in self._list():
            if machines and v['name'] not in machines:
                continue
            out.append({
                'name': v['name'],
                'machine_type': v['machine_type'],
                'locked': v['in_use'],
                'description': v['cookie'],
                'info': v['info'],
            })
        return out

    @_track
    def reimage_machines(self, machines, machine_type):
        return {m: None for m in machines}


def main():
    import argparse
    import sys
    import yaml

    class Context:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--add', action='append')
    parser.add_argument('--rm-all', action='store_true')
    parser.add_argument('--rm', action='append')
    parser.add_argument('--reserve', type=int)
    parser.add_argument('--cookie', type=str)
    parser.add_argument('--machine-type')
    parser.add_argument('--info')
    cli = parser.parse_args()

    mpool = SqliteMachinePool()
    if cli.rm_all:
        mpool.dbmgr.remove_all_machines()
    for name in cli.rm or []:
        mpool.dbmgr.remove_machine(name)
    for name in cli.add or []:
        mpool.dbmgr.add_machine(name, cli.machine_type, cli.info)
    if cli.reserve:
        ctx = Context()
        setattr(ctx, 'job_cookie', cli.cookie)
        mpool.reserve(ctx, cli.reserve, cli.machine_type)
    if cli.list:
        yaml.safe_dump(mpool.everything(), sys.stdout, sort_keys=False)


if __name__ == '__main__':
    main()
