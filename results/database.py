import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4
from results.schema import initialize_schema


class StorageError(RuntimeError):
    pass


class ResultNotFound(LookupError):
    pass


_BOUND_DATABASE = ContextVar('laboratory_database', default=None)


class Database:
    def __init__(self, path):
        self.connection = None
        self.failure_kind = None
        try:
            self.connection = sqlite3.connect(str(path), isolation_level=None)
            self.connection.execute('PRAGMA foreign_keys=ON')
            initialize_schema(self.connection)
        except sqlite3.Error as exc:
            if self.connection is not None:
                self.connection.close()
            raise StorageError(str(exc)) from exc
        except BaseException:
            if self.connection is not None:
                self.connection.close()
            raise

    @contextmanager
    def transaction(self):
        if self.connection.in_transaction:
            raise StorageError('nested business transactions are unsupported')
        try:
            self.connection.execute('BEGIN IMMEDIATE')
            yield self
            self.connection.commit()
        except BaseException as exc:
            self.connection.rollback()
            if isinstance(exc, sqlite3.Error):
                raise StorageError(str(exc)) from exc
            raise

    def execute(self, sql, parameters=()):
        try:
            return self.connection.execute(sql, parameters)
        except sqlite3.Error as exc:
            raise StorageError(str(exc)) from exc

    def query(self, sql, parameters=()):
        return self.execute(sql, parameters).fetchall()

    def fail_next_publication(self, kind):
        if kind not in ('fit', 'prediction'):
            raise ValueError('failure kind must be fit or prediction')
        self.failure_kind = kind

    def _publish(self, kind, parent_id, payload):
        identity = kind + '-' + uuid4().hex
        with self.transaction():
            if kind == 'fit':
                if not self.query('SELECT 1 FROM cohorts WHERE cohort_id=?', (parent_id,)):
                    raise StorageError('missing frozen cohort')
                cohort_id, fit_id = parent_id, None
            else:
                parent = self.query('SELECT kind FROM result_heads WHERE result_id=?', (parent_id,))
                if parent != [('fit',)]:
                    raise StorageError('prediction parent must be a published fit')
                if not self.query('SELECT 1 FROM result_payloads WHERE result_id=?', (parent_id,)):
                    raise StorageError('incomplete parent fit')
                cohort_id, fit_id = None, parent_id
            self.execute('INSERT INTO result_heads VALUES(?,?,?,?)',
                         (identity, kind, cohort_id, fit_id))
            if self.failure_kind == kind:
                self.failure_kind = None
                self.execute('INSERT INTO publication_guard VALUES(1)')
            self.execute('INSERT INTO result_payloads VALUES(?,?)', (identity, payload))
        return identity

    def publish_fit(self, cohort_id, payload):
        return self._publish('fit', cohort_id, payload)

    def publish_prediction(self, fit_id, payload):
        return self._publish('prediction', fit_id, payload)

    def read_published(self, identity):
        rows = self.query(
            'SELECT h.kind,h.cohort_id,h.fit_id,p.payload FROM result_heads h '
            'JOIN result_payloads p ON h.result_id=p.result_id WHERE h.result_id=?', (identity,))
        if not rows:
            raise ResultNotFound(identity)
        kind, cohort_id, fit_id, payload = rows[0]
        return {'result_id': identity, 'kind': kind, 'cohort_id': cohort_id,
                'fit_id': fit_id, 'payload': payload}

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None


@contextmanager
def database_session(database):
    if database.connection is None:
        raise StorageError('database is closed')
    token = _BOUND_DATABASE.set(database)
    try:
        yield database
    finally:
        _BOUND_DATABASE.reset(token)


def current_database():
    database = _BOUND_DATABASE.get()
    if database is None or database.connection is None:
        raise StorageError('open database_session required')
    return database
