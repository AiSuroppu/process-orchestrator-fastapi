from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime

class ServiceStatus(BaseModel):
    name: str
    group_id: str
    status: Literal["running", "stopped", "crashed"]
    pid: Optional[int] = None
    start_time: Optional[datetime] = None
    detail: str