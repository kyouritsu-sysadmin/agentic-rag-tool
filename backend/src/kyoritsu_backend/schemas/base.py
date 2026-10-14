from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from kyoritsu_backend.rag.taxonomy import canonical, valid_scope


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ScopeSchema(Schema):
    @field_validator("company", "dept", "section", "doc_type", mode="before", check_fields=False)
    @classmethod
    def normalize_scope(cls, value, info):
        return canonical(info.field_name, value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_scope(self):
        if not valid_scope(self.company, self.dept, self.section):
            raise ValueError("Filters do not describe a valid organization scope")
        return self


class ResponseModel(BaseModel):
    """Wire responses do not strip document/answer whitespace."""

    model_config = ConfigDict(extra="forbid")
