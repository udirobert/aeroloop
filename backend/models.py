"""Pydantic schemas for AeroLoop."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Prediction(BaseModel):
    id: Optional[int] = None
    station_id: str
    timestamp: datetime
    predicted_pm25: float
    units: str = "ug/m3"
    confidence: Optional[float] = None
    strategy_version: str
    agent_version: str
    inputs: dict = Field(default_factory=dict)
    source_timestamps: dict = Field(default_factory=dict)


class GroundReading(BaseModel):
    id: Optional[int] = None
    station_id: str
    timestamp: datetime
    measured_pm25: float
    units: str = "ug/m3"
    source: str = "DEFRA AURN"


class ErrorRecord(BaseModel):
    id: Optional[int] = None
    prediction_id: int
    station_id: str
    timestamp: datetime
    predicted: float
    actual: float
    error: float
    abs_error: float
    squared_error: float


class Strategy(BaseModel):
    version: str
    description: str
    params: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    parent_version: Optional[str] = None


class EvaluationResult(BaseModel):
    strategy_version: str
    n: int
    mae: float
    rmse: float
    bias: float
    by_station: dict = Field(default_factory=dict)
    by_condition: dict = Field(default_factory=dict)


class AgentReport(BaseModel):
    what_went_wrong: str
    pattern_discovered: str
    change_made: str
    why_it_should_help: str
    improved: bool
    before: EvaluationResult
    after: EvaluationResult
