SCHEMA_VERSION = 1


class SchemaVersionError(ValueError):
    pass


SCHEMA_STATEMENTS = (
    'CREATE TABLE IF NOT EXISTS metadata(version INTEGER NOT NULL)',
    'CREATE TABLE IF NOT EXISTS measurement_history('
    'measurement_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0), '
    'payload TEXT NOT NULL, PRIMARY KEY(measurement_id,revision))',
    'CREATE TABLE IF NOT EXISTS measurement_current('
    'measurement_id TEXT PRIMARY KEY,revision INTEGER NOT NULL, '
    'FOREIGN KEY(measurement_id,revision) REFERENCES measurement_history)',
    'CREATE TABLE IF NOT EXISTS cohorts(cohort_id TEXT PRIMARY KEY,payload TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS result_heads('
    'result_id TEXT PRIMARY KEY,kind TEXT NOT NULL CHECK(kind IN ("fit","prediction")),'
    'cohort_id TEXT REFERENCES cohorts(cohort_id),fit_id TEXT REFERENCES result_heads(result_id),'
    'CHECK((kind="fit" AND cohort_id IS NOT NULL AND fit_id IS NULL) OR '
    '(kind="prediction" AND fit_id IS NOT NULL AND cohort_id IS NULL)))',
    'CREATE TABLE IF NOT EXISTS result_payloads('
    'result_id TEXT PRIMARY KEY REFERENCES result_heads(result_id),payload TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS publication_guard(value INTEGER CHECK(value=0))',
)


def initialize_schema(connection):
    connection.execute('BEGIN IMMEDIATE')
    try:
        present = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone()
        if present:
            versions = connection.execute('SELECT version FROM metadata').fetchall()
            if versions != [(SCHEMA_VERSION,)]:
                raise SchemaVersionError('incompatible database schema')
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        if not present:
            connection.execute('INSERT INTO metadata VALUES(?)', (SCHEMA_VERSION,))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
