from pydantic import BaseModel


class ApiResult(BaseModel):
    success: bool
    message: str
    data: None
