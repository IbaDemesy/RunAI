"""Record models. Run this module to print the JSON Schema."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Counts(Model):
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    xfailed: int = Field(default=0, ge=0)
    xpassed: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)


class Failure(Model):
    id: str
    message: str


class TestResult(Model):
    id: str
    outcome: Literal["passed", "failed", "skipped", "xfailed", "xpassed", "error"]
    duration_s: float = Field(default=0, ge=0)


class Suite(Model):
    verdict: Literal["pass", "fail", "skip", "error"]
    duration_s: float = Field(default=0, ge=0)
    counts: Counts = Field(default_factory=Counts)
    failures: list[Failure] = Field(default_factory=list)
    tests: list[TestResult] = Field(default_factory=list)
    reason: str | None = None


class Git(Model):
    sha: str
    branch: str
    dirty: bool


class CI(Model):
    provider: str
    run_id: str | None
    run_url: str | None


class Suites(Model):
    ruff: Suite
    pytest: Suite
    node: Suite


class RunRecord(Model):
    schema_version: Literal["test-history.v1"] = "test-history.v1"
    run_id: str
    started_at: str
    finished_at: str
    duration_s: float = Field(ge=0)
    git: Git
    wave: str | None
    ci: CI | None
    verdict: Literal["pass", "fail"]
    suites: Suites


if __name__ == "__main__":
    import json

    print(json.dumps(RunRecord.model_json_schema(), indent=2))
