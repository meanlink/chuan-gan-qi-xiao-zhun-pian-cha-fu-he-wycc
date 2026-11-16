from pydantic import BaseModel, Field
class JobInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    dataset_id: int
    params: dict = Field(default_factory=dict)
    segment_size: int | None = Field(default=None, ge=1, le=5000)
class ResumeInput(BaseModel):
    segment_size: int | None = Field(default=None, ge=1, le=5000)
class AppendInput(BaseModel):
    additional: int | None = Field(default=None, ge=1, le=4500)
    resamples: int | None = Field(default=None, ge=500, le=5000)
    segment_size: int | None = Field(default=None, ge=1, le=5000)
