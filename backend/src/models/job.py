from sqlalchemy import String, JSON, Double, ForeignKey, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column, deferred
from src.config.database import Base
class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    # 分段续算：progress 保存每个温区已完成的逐次重采样（按需加载），progress_meta 是页面所需的轻量进度。
    progress: Mapped[dict | None] = deferred(mapped_column(JSON, nullable=True))
    progress_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), default='')
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    heartbeat_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    paused_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey('jobs.id'), nullable=True)
    superseded_by: Mapped[int | None] = mapped_column(ForeignKey('jobs.id'), nullable=True)
