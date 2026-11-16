import copy
import time
from fastapi import HTTPException
from redis import Redis
from src.config.settings import REDIS_URL
from src.models import Dataset, Job
from src.services.business import metadata, prepare, progress_meta, DEFAULT_SEGMENT_SIZE, SEED
from src.utils.serialization import checksum

QUEUE = 'analysis:queue'


def _segment_size(value):
    if value is None:
        return DEFAULT_SEGMENT_SIZE
    try:
        size = int(value)
    except (TypeError, ValueError):
        raise HTTPException(422, '分段大小须为整数')
    if size < 1 or size > 5000:
        raise HTTPException(422, '分段大小须在 1–5000 之间')
    return size


def fingerprint(dataset, params):
    """标识本次分析的输入与口径；追加次数不改变该指纹，以便续算到同一份样本。"""
    relevant = {k: params.get(k) for k in ('offset', 'confidence')}
    return checksum({'dataset': dataset.id, 'checksum': dataset.checksum, 'seed': SEED, 'params': relevant})


def _params(data):
    allowed = {p['key']: p for p in metadata().get('parameters', [])}
    if set(data.params) - set(allowed):
        raise HTTPException(422, '包含未知分析参数')
    params = {k: p['default'] for k, p in allowed.items()}
    params.update(data.params)
    for key, p in allowed.items():
        v = params[key]
        if p['type'] == 'number':
            try:
                v = float(v)
                if not (p.get('min', -1e9) <= v <= p.get('max', 1e9)):
                    raise ValueError()
                if key == 'resamples':
                    if v != int(v):
                        raise ValueError()
                    v = int(v)
                params[key] = v
            except (ValueError, TypeError):
                raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(v) not in [str(o['value']) for o in p.get('options', [])]:
            raise HTTPException(422, f'{p["label"]} 不是有效选项')
    return params


def create(db, data, user):
    dataset = db.get(Dataset, data.dataset_id)
    if not dataset:
        raise HTTPException(404, '数据批次不存在')
    params = _params(data)
    segment_size = _segment_size(getattr(data, 'segment_size', None))
    fp = fingerprint(dataset, params)
    bands = []
    try:
        # 提前列出温区，便于页面在排队时就核对各温区目标；输入不合法仍留到执行时报错。
        prepared = prepare(dataset.records, params)
        bands = [{'band': band, 'n': int(prepared['values'][band].size), 'completed': 0} for band in prepared['bands']]
    except ValueError:
        pass
    j = Job(name=data.name, dataset_id=data.dataset_id, params=params, created_by=user.id, created_at=time.time(),
            status='queued', attempt=0, fingerprint=fp,
            progress={"segment_size": segment_size},
            progress_meta={"target": int(params["resamples"]), "completed": 0, "segment_size": segment_size, "bands": bands, "percent": 0})
    db.add(j)
    db.flush()
    return j


def enqueue(job_id):
    try:
        r = Redis.from_url(REDIS_URL)
        r.rpush(QUEUE, job_id)
        r.close()
    except Exception:
        pass  # SQL queued status is the durable fallback


def pause(db, job, user):
    if job.status not in ('queued', 'running'):
        raise HTTPException(409, '仅排队中或计算中的分析可以暂停')
    # 提升 attempt 使正在执行的旧 worker 在下一个分段边界失去写入资格。
    job.status = 'paused'
    job.paused_at = time.time()
    job.attempt = (job.attempt or 0) + 1
    job.heartbeat_at = None
    return job


def resume(db, job, user, segment_size=None):
    if job.status not in ('paused', 'failed'):
        raise HTTPException(409, '仅已暂停或失败的分析可以恢复')
    if segment_size is not None:
        progress = copy.deepcopy(job.progress or {})
        progress['segment_size'] = _segment_size(segment_size)
        job.progress = progress
        meta = dict(job.progress_meta or {})
        meta['segment_size'] = progress['segment_size']
        job.progress_meta = meta
    job.status = 'queued'
    job.paused_at = None
    job.error = ''
    db.flush()
    enqueue(job.id)
    return job


def _current_target(job):
    meta = job.progress_meta or {}
    return int(meta.get('target') or job.params.get('resamples', 2000))


def append_samples(db, job, user, additional=None, resamples=None, segment_size=None):
    """追加采样次数；只补算差异部分。已批准结果保留原版并派生待审的新版本。"""
    target = _current_target(job)
    if additional is not None:
        try:
            additional = int(additional)
        except (TypeError, ValueError):
            raise HTTPException(422, '追加次数须为整数')
        if additional < 1:
            raise HTTPException(422, '追加次数须大于 0')
        new_target = target + additional
    elif resamples is not None:
        try:
            new_target = int(resamples)
        except (TypeError, ValueError):
            raise HTTPException(422, '目标次数须为整数')
        if new_target <= target:
            raise HTTPException(422, '目标次数须大于当前已完成的目标')
    else:
        raise HTTPException(422, '请提供追加次数')
    if not 500 <= new_target <= 5000:
        raise HTTPException(422, '追加后总次数须在 500–5000 之间')
    if job.status not in ('completed', 'paused', 'failed'):
        raise HTTPException(409, '仅已完成、已暂停或失败的分析可以追加采样')
    if job.superseded_by:
        raise HTTPException(409, '该版本已被待审版本替代，请在最新版本上追加')
    if job.status == 'completed' and not (job.progress or {}).get('bands'):
        raise HTTPException(409, '该结果未保存逐次采样明细，无法只补算未完成部分；请新建分析任务')

    progress = copy.deepcopy(job.progress or {})
    progress['target'] = new_target
    if segment_size is not None:
        progress['segment_size'] = _segment_size(segment_size)
    progress.setdefault('segment_size', DEFAULT_SEGMENT_SIZE)
    params = dict(job.params)
    params['resamples'] = new_target
    meta = progress_meta(progress)
    meta['percent'] = round(min(meta['completed'], new_target) * 100 / new_target, 1)
    meta['target'] = new_target

    if job.approved:
        # 已批准结果不可改动：保留原版，另建待审版本，续用已存采样。
        child = Job(name=job.name, dataset_id=job.dataset_id, params=params, created_by=user.id,
                    created_at=time.time(), status='queued', attempt=0, approved=False,
                    fingerprint=job.fingerprint, progress=progress, progress_meta=meta, parent_id=job.id)
        db.add(child)
        db.flush()
        job.superseded_by = child.id
        enqueue(child.id)
        return child, True
    job.params = params
    job.progress = progress
    job.progress_meta = meta
    job.result = {}
    job.error = ''
    job.approved = False
    job.finished_at = None
    job.paused_at = time.time() if job.status == 'paused' else None
    if job.status != 'paused':
        # 暂停中的任务保留暂停状态，由用户显式恢复；其余状态立即续算。
        job.status = 'queued'
        enqueue(job.id)
    return job, False
