from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import Job
from src.schemas.job import JobInput, ResumeInput, AppendInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import jobs
from src.services.audit import record
from src.utils.serialization import job_dict
router=APIRouter(prefix='/jobs')
@router.get('')
def listing(db=Depends(get_db),u=Depends(current_user)):
    return [job_dict(j) for j in db.scalars(select(Job).order_by(Job.id.desc()).limit(100))]
@router.post('',status_code=201)
def create(data:JobInput,db=Depends(get_db),u=Depends(can_write)):
    j=jobs.create(db,data,u); record(db,u.email,'job.create',{'id':j.id,'params':j.params,'segment_size':(j.progress or {}).get('segment_size')})
    db.commit(); jobs.enqueue(j.id); return job_dict(j)
@router.get('/{id}')
def detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    return job_dict(j)
@router.post('/{id}/approve')
def approve(id:int,db=Depends(get_db),u=Depends(admin_only)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    if j.status!='completed':raise HTTPException(409,'仅已完成结果可以批准')
    if j.superseded_by:raise HTTPException(409,'该版本已另有待审版本，请复核最新版本后再批准')
    j.approved=True; record(db,u.email,'job.approve',{'id':id,'resamples':(j.progress or {}).get('target')}); db.commit()
    return job_dict(j)
@router.post('/{id}/pause')
def pause(id:int,db=Depends(get_db),u=Depends(can_write)):
    j=db.get(Job,id)
    if not j:raise HTTPException(404,'分析任务不存在')
    j=jobs.pause(db,j,u); record(db,u.email,'job.pause',{'id':id,'completed':j.progress_meta.get('completed',0)}); db.commit()
    return job_dict(j)
@router.post('/{id}/resume')
def resume(id:int,data:ResumeInput|None=None,db=Depends(get_db),u=Depends(can_write)):
    j=db.get(Job,id)
    if not j:raise HTTPException(404,'分析任务不存在')
    j=jobs.resume(db,j,u,(data or ResumeInput()).segment_size); record(db,u.email,'job.resume',{'id':id,'completed':j.progress_meta.get('completed',0)}); db.commit()
    return job_dict(j)
@router.post('/{id}/append')
def append(id:int,data:AppendInput,db=Depends(get_db),u=Depends(can_write)):
    j=db.get(Job,id)
    if not j:raise HTTPException(404,'分析任务不存在')
    target,versioned=jobs.append_samples(db,j,u,data.additional,data.resamples,data.segment_size)
    record(db,u.email,'job.append',{'id':j.id,'target':target.id,'resamples':(target.progress or {}).get('target'),'versioned':versioned})
    db.commit()
    return job_dict(target)
