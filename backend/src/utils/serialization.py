import hashlib, json
from src.services.business import progress_meta
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def _progress(j):
    if j.progress_meta:
        return j.progress_meta
    meta = progress_meta(getattr(j, 'progress', None) or {})
    if not meta.get('target') and getattr(j, 'params', None):
        # 旧库升级的任务没有进度列：按参数和目标状态给出可读的兼容展示。
        target = int(j.params.get('resamples') or 0)
        if target:
            complete = j.status == 'completed'
            meta = {'target': target, 'completed': target if complete else 0, 'percent': 100.0 if complete else 0,
                    'segment_size': 0, 'bands': [], 'legacy': True}
    return meta
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at','parent_id','superseded_by','paused_at']}|{'progress':_progress(j),'fingerprint':j.fingerprint}
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
