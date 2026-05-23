from pydantic import BaseModel


class SchemaSettings(BaseModel):
    persist_directory: str = "assets/schema"


DEFAULT_Schema_SETTINGS = SchemaSettings()
__ALL__ = ["SchemaSettings", "DEFAULT_Schema_SETTINGS"]
