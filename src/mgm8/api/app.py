from datetime import datetime
from uuid import UUID

from flask import Flask, jsonify, request

from mgm8.application.pass_predictor import DiscoverPassesRequest, PassPredictionService
from mgm8.application.pass_scheduler import PassSchedulerService, SchedulePassRequest
from mgm8.application.tc_scheduler import ScheduleTelecommandRequest, TCSchedulerService
from mgm8.domain.models import TLE, GroundStationLocation
from mgm8.domain.services import SchedulingConflictDetector
from mgm8.infrastructure.in_memory import (InMemoryOperationalEventRepository, InMemoryScheduledPassRepository,
                                             InMemoryScheduledTelecommandRepository,
                                             InMemorySchedulingConflictRepository)
from mgm8.web.routes import web_bp

_PROPAGATION_UNAVAILABLE = "Propagation support is not installed. Install it with: pip install \"mgm8[propagation]\"."


def _build_predictor(scheduler: PassSchedulerService) -> PassPredictionService | None:
    try:
        from mgm8.infrastructure.skyfield_propagator import SkyfieldPropagator
    except ImportError:
        return None
    return PassPredictionService(SkyfieldPropagator(), scheduler, scheduler.event_repository)


def _parse_tle(payload: dict) -> TLE:
    tle = payload.get("tle") or {}
    return TLE(line1=tle["line1"], line2=tle["line2"], name=tle.get("name", ""))


def _parse_location(payload: dict) -> GroundStationLocation:
    location = payload.get("location")
    if not location:
        return GroundStationLocation.spacelab_ufsc()
    return GroundStationLocation(
        float(location["latitude_degrees"]),
        float(location["longitude_degrees"]),
        float(location.get("altitude_meters", 0.0)),
    )


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "dev-secret-key-change-in-production"
    pass_repo = InMemoryScheduledPassRepository()
    event_repo = InMemoryOperationalEventRepository()
    telecommand_repo = InMemoryScheduledTelecommandRepository()
    service = PassSchedulerService(pass_repo, InMemorySchedulingConflictRepository(),
                                   event_repo, SchedulingConflictDetector())
    tc_service = TCSchedulerService(telecommand_repo, pass_repo, event_repo)
    app.config["PASS_SCHEDULER"] = service
    app.config["TC_SCHEDULER"] = tc_service
    predictor = _build_predictor(service)
    app.config["PASS_PREDICTOR"] = predictor
    app.register_blueprint(web_bp)

    @app.get("/health")
    def health() -> tuple[dict[str, str], int]:
        return {"status": "ok"}, 200

    @app.post("/api/passes")
    def schedule_pass():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Expected a JSON object."), 400
        try:
            result = service.schedule_pass(SchedulePassRequest(
                satellite_id=UUID(payload["satellite_id"]),
                aos=datetime.fromisoformat(payload["aos"]),
                los=datetime.fromisoformat(payload["los"]),
                center_frequency_hz=int(payload["center_frequency_hz"]),
                doppler_source=payload.get("doppler_source"),
                max_elevation_degrees=payload.get("max_elevation_degrees"),
                auto_execute=payload.get("auto_execute", True),
                notes=payload.get("notes"),
                created_by=payload.get("created_by"),
            ))
        except (KeyError, TypeError, ValueError) as error:
            return jsonify(error=str(error)), 400

        if not result.succeeded:
            return jsonify(error="Scheduling conflict.", conflicts=[{
                "id": str(item.id), "pass_a_id": str(item.pass_a_id), "pass_b_id": str(item.pass_b_id),
                "resource": item.resource, "detected_at": item.detected_at.isoformat(),
            } for item in result.conflicts]), 409

        scheduled_pass = result.scheduled_pass
        return jsonify(id=str(scheduled_pass.id), status=scheduled_pass.status.value), 201

    @app.post("/api/passes/predict")
    def predict_passes():
        if predictor is None:
            return jsonify(error=_PROPAGATION_UNAVAILABLE), 503
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Expected a JSON object."), 400
        try:
            predictions = predictor.preview_passes(
                _parse_tle(payload),
                _parse_location(payload),
                horizon_hours=float(payload.get("horizon_hours", 24.0)),
                min_elevation_degrees=float(payload.get("min_elevation_degrees", 5.0)),
            )
        except (KeyError, TypeError, ValueError) as error:
            return jsonify(error=str(error)), 400
        return jsonify(passes=[PassPredictionService.prediction_to_dict(item) for item in predictions])

    @app.post("/api/passes/discover")
    def discover_passes():
        if predictor is None:
            return jsonify(error=_PROPAGATION_UNAVAILABLE), 503
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Expected a JSON object."), 400
        try:
            result = predictor.discover_and_schedule(DiscoverPassesRequest(
                satellite_id=UUID(payload["satellite_id"]),
                tle=_parse_tle(payload),
                center_frequency_hz=int(payload["center_frequency_hz"]),
                location=_parse_location(payload),
                horizon_hours=float(payload.get("horizon_hours", 24.0)),
                min_elevation_degrees=float(payload.get("min_elevation_degrees", 5.0)),
                doppler_source=payload.get("doppler_source", "propagator"),
                auto_execute=payload.get("auto_execute", True),
                created_by=payload.get("created_by"),
            ))
        except (KeyError, TypeError, ValueError) as error:
            return jsonify(error=str(error)), 400
        return jsonify(
            scheduled=[PassPredictionService.discovered_to_dict(item) for item in result.scheduled],
            conflicts=[PassPredictionService.discovered_to_dict(item) for item in result.conflicts],
            duplicates=[PassPredictionService.discovered_to_dict(item) for item in result.duplicates],
        ), 201

    @app.get("/api/telecommands")
    def list_telecommands():
        return jsonify(telecommands=[
            TCSchedulerService.telecommand_to_dict(item) for item in tc_service.list_telecommands()
        ])

    @app.post("/api/telecommands")
    def schedule_telecommand():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Expected a JSON object."), 400
        try:
            result = tc_service.schedule_telecommand(ScheduleTelecommandRequest(
                telecommand_definition_id=UUID(payload["telecommand_definition_id"]),
                execute_at=datetime.fromisoformat(payload["execute_at"]),
                scheduled_pass_id=UUID(payload["scheduled_pass_id"]) if payload.get("scheduled_pass_id") else None,
                parameters=payload.get("parameters") or {},
                frame_hex=payload.get("frame_hex"),
                priority=int(payload.get("priority", 5)),
                requires_approval=bool(payload.get("requires_approval", False)),
                created_by=payload.get("created_by"),
            ))
        except (KeyError, TypeError, ValueError) as error:
            return jsonify(error=str(error)), 400

        if not result.succeeded:
            return jsonify(error="Telecommand scheduling rejected.", reason=result.reason,
                           conflicting_ids=[str(item) for item in result.conflicting_ids]), 409

        telecommand = result.scheduled_telecommand
        return jsonify(id=str(telecommand.id), status=telecommand.status.value), 201

    @app.post("/api/telecommands/<telecommand_id>/cancel")
    def cancel_telecommand(telecommand_id: str):
        try:
            telecommand = tc_service.cancel_telecommand(UUID(telecommand_id))
        except LookupError as error:
            return jsonify(error=str(error)), 404
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return jsonify(id=str(telecommand.id), status=telecommand.status.value)

    @app.post("/api/telecommands/<telecommand_id>/approve")
    def approve_telecommand(telecommand_id: str):
        payload = request.get_json(silent=True) or {}
        approved_by = payload.get("approved_by")
        if not approved_by:
            return jsonify(error="approved_by is required."), 400
        try:
            telecommand = tc_service.approve_telecommand(UUID(telecommand_id), approved_by)
        except LookupError as error:
            return jsonify(error=str(error)), 404
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return jsonify(id=str(telecommand.id), status=telecommand.status.value,
                       approved_by=telecommand.approved_by)

    return app


app = create_app()
