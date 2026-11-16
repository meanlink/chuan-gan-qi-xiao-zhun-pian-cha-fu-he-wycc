from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models

# 旧库升级时补充的列；create_all 不会修改已存在的表。
_REAL = 'DOUBLE PRECISION' if engine.dialect.name == 'postgresql' else 'REAL'
JOB_COLUMNS = {
    'progress': 'JSON',
    'progress_meta': "JSON NOT NULL DEFAULT '{}'",
    'fingerprint': "VARCHAR(64) NOT NULL DEFAULT ''",
    'attempt': 'INTEGER NOT NULL DEFAULT 0',
    'heartbeat_at': _REAL,
    'paused_at': _REAL,
    'parent_id': 'INTEGER',
    'superseded_by': 'INTEGER',
}


def migrate():
    Base.metadata.create_all(engine)
    existing = {c['name'] for c in inspect(engine).get_columns('jobs')}
    missing = [(name, ddl) for name, ddl in JOB_COLUMNS.items() if name not in existing]
    if not missing:
        return
    with engine.begin() as connection:
        for name, ddl in missing:
            connection.execute(text(f'ALTER TABLE jobs ADD COLUMN {name} {ddl}'))


if __name__=='__main__':migrate()
