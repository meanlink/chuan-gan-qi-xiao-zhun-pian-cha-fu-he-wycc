import time, json, logging, os
from pathlib import Path
from sqlalchemy import select, update
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report
from src.services.business import prepare, advance, complete, finalize, initial_progress, progress_meta, DEFAULT_SEGMENT_SIZE
from src.services.jobs import QUEUE, fingerprint
from src.services.reports import deliver
from src.services.audit import record
logging.basicConfig(level=logging.INFO)

STALE_AFTER = float(os.getenv('WORKER_STALE_AFTER', '30'))


def _claim(db, job_id):
    """原子领取任务：排队中，或心跳已过期的执行中任务，才能由新的 attempt 接管。"""
    now = time.time()
    claimed = db.execute(update(Job).where(
        (Job.id == job_id) &
        ((Job.status == 'queued') |
         ((Job.status == 'running') & ((Job.heartbeat_at == None) | (Job.heartbeat_at < now - STALE_AFTER))))
    ).values(status='running', attempt=Job.attempt + 1, heartbeat_at=now, error='', finished_at=None)).rowcount
    db.commit()
    return bool(claimed)


def _guarded(db, job_id, attempt, values):
    """只有仍由同一 attempt 执行且未被暂停时，该次写入才生效；旧执行晚到会被拒绝。"""
    changed = db.execute(update(Job).where(
        (Job.id == job_id) & (Job.attempt == attempt) & (Job.status == 'running')
    ).values(**values)).rowcount
    db.commit()
    return bool(changed)


def execute(job_id):
    with Session() as db:
        job = db.get(Job, job_id)
        if not job or job.status not in ('queued', 'running'):
            return
        if not _claim(db, job_id):
            return
        db.refresh(job)
        attempt = job.attempt
        try:
            dataset = db.get(Dataset, job.dataset_id)
            expected = fingerprint(dataset, job.params)
            if not job.fingerprint:
                job.fingerprint = expected
            if job.fingerprint != expected:
                raise ValueError('数据批次或分析口径已变化，请新建分析任务')
            prepared = prepare(dataset.records, job.params)
            progress = job.progress or {}
            if not progress.get('bands'):
                # 保留创建、暂停或追加时指定的目标与分段大小，只补齐空进度结构。
                progress = initial_progress(prepared, job.fingerprint, progress.get('segment_size') or DEFAULT_SEGMENT_SIZE,
                                            progress.get('target'))
            if not progress.get('fingerprint'):
                progress['fingerprint'] = job.fingerprint
            if progress.get('fingerprint') != job.fingerprint:
                raise ValueError('数据批次或分析口径已变化，请新建分析任务')
            if int(progress.get('target') or prepared['target']) != prepared['target']:
                raise ValueError('已存采样目标与当前参数不一致，无法续算')
            step = int(progress.get('segment_size') or DEFAULT_SEGMENT_SIZE)
            while not complete(progress, prepared):
                progress = advance(progress, prepared, step)
                if not _guarded(db, job_id, attempt, {'progress': progress, 'progress_meta': progress_meta(progress), 'heartbeat_at': time.time()}):
                    logging.info('Job %s attempt %s superseded before segment write', job_id, attempt)
                    return
            result = finalize(prepared, progress)
            json.dumps(result, allow_nan=False)
            if not _guarded(db, job_id, attempt, {
                    'result': result, 'progress': progress, 'progress_meta': progress_meta(progress), 'status': 'completed',
                    'finished_at': time.time(), 'heartbeat_at': None}):
                logging.info('Job %s attempt %s superseded before completion', job_id, attempt)
                return
            record(db, 'worker', 'job.completed', {'id': job_id, 'resamples': int(progress['target'])})
            db.commit()
        except Exception as e:
            logging.exception('Analysis failed')
            db.rollback()
            latest = db.get(Job, job_id)
            if latest and latest.attempt == attempt and latest.status == 'running':
                latest.status = 'failed'
                latest.error = str(e)[:990]
                latest.finished_at = time.time()
                latest.heartbeat_at = None
                record(db, 'worker', 'job.failed', {'id': job_id, 'error': latest.error})
                db.commit()


def tick():
    with Session() as db:
        now = time.time()
        pending = list(db.scalars(select(Job.id).where(
            (Job.status == 'queued') |
            ((Job.status == 'running') & ((Job.heartbeat_at == None) | (Job.heartbeat_at < now - STALE_AFTER)))
        ).order_by(Job.id).limit(3)))
    for job_id in pending:
        execute(job_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled == True, Report.next_run <= time.time())):
            d = deliver(db, r)
            if d:
                record(db, 'worker', 'report.delivered', {'id': r.id, 'delivery': d.id})
        db.commit()


def main():
    r = Redis.from_url(REDIS_URL, socket_timeout=3)
    # 中断后不重置进行中的任务：心跳过期的任务由下一次领取按 attempt 接管，已存分段采样继续使用。
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item = r.blpop(QUEUE, timeout=1)
            if item:
                execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry')
            time.sleep(2)


if __name__ == '__main__':
    main()
