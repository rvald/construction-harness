from __future__ import annotations
from dataclasses import dataclass

from jsonschema import Draft202012Validator

@dataclass(frozen=True)
class ValidationError:
    message: str
    path: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" 
    
def validate(args: dict, schema: dict) -> list[ValidationError]:
    """Validate a dict against a JSON schema.

    Returns a list of ValidationError objects for any violations.
    """
    validator = Draft202012Validator(schema)
    errors: list[ValidationError] = []
    for error in validator.iter_errors(args):
        path = "args" + "".join(f".{p}" for p in error.absolute_path)
        errors.append(ValidationError(message=error.message, path=path))
    return errors