from datetime import datetime, timezone
from uuid import UUID

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for

from mgm8.application.pass_scheduler import PassSchedulerService, SchedulePassRequest
from mgm8.application.tc_scheduler import ScheduleTelecommandRequest, TCSchedulerService

web_bp = Blueprint("web", __name__, template_folder="templates")


def _service() -> PassSchedulerService:
    return current_app.config["PASS_SCHEDULER"]


def _tc_service() -> TCSchedulerService:
    return current_app.config["TC_SCHEDULER"]


def _parse_form_datetime(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


@web_bp.route("/")
def index():
    service = _service()
    all_passes = service.list_passes()
    scheduled = [item for item in all_passes if item.status.value == "Scheduled"]
    in_progress = [item for item in all_passes if item.status.value == "InProgress"]
    history = [item for item in all_passes if item.status.value in {"Completed", "Cancelled", "Failed", "Missed"}]
    satellite_ids = sorted({str(item.satellite_id) for item in all_passes})

    telecommands = _tc_service().list_telecommands()
    tc_active = [item for item in telecommands if item.status.value in {"Scheduled", "InProgress"}]
    tc_pending_approval = [item for item in tc_active if item.requires_approval and item.approved_at is None]

    return render_template(
        "index.html",
        scheduled_passes=scheduled[:10],
        in_progress_passes=in_progress[:10],
        history_passes=history[:20],
        all_passes=all_passes,
        satellite_ids=satellite_ids,
        events=service.list_events(30),
        conflicts=service.list_conflicts(10),
        telecommands=telecommands,
        tc_active=tc_active,
        tc_pending_approval=tc_pending_approval,
    )


@web_bp.route("/pass/create", methods=["POST"])
def create_pass():
    service = _service()
    data = request.form

    try:
        aos = datetime.fromisoformat(data["aos"])
        los = datetime.fromisoformat(data["los"])
        if aos.tzinfo is None:
            aos = aos.replace(tzinfo=timezone.utc)
        if los.tzinfo is None:
            los = los.replace(tzinfo=timezone.utc)

        result = service.schedule_pass(SchedulePassRequest(
            satellite_id=UUID(data["satellite_id"]),
            aos=aos,
            los=los,
            center_frequency_hz=int(data["center_frequency_hz"]),
            doppler_source=data.get("doppler_source") or None,
            max_elevation_degrees=float(data["max_elevation_degrees"]) if data.get("max_elevation_degrees") else None,
            auto_execute=data.get("auto_execute") == "on",
            notes=data.get("notes") or None,
            created_by=data.get("created_by") or None,
        ))
    except (KeyError, TypeError, ValueError) as error:
        flash(f"Invalid pass data: {error}", "danger")
        return redirect(url_for("web.index"))

    if not result.succeeded:
        flash(f"Scheduling conflict detected ({len(result.conflicts)} conflict(s)).", "danger")
        return redirect(url_for("web.index"))

    flash("Pass scheduled successfully.", "success")
    return redirect(url_for("web.index"))


@web_bp.route("/pass/cancel/<pass_id>", methods=["POST"])
def cancel_pass(pass_id: str):
    service = _service()
    try:
        service.cancel_pass(UUID(pass_id))
    except (ValueError, LookupError) as error:
        if request.is_json:
            return jsonify(success=False, error=str(error)), 400
        flash(str(error), "danger")
        return redirect(url_for("web.index"))

    if request.is_json:
        return jsonify(success=True, message="Pass cancelled.")
    flash("Pass cancelled.", "success")
    return redirect(url_for("web.index"))


@web_bp.route("/telecommand/create", methods=["POST"])
def create_telecommand():
    data = request.form
    try:
        result = _tc_service().schedule_telecommand(ScheduleTelecommandRequest(
            telecommand_definition_id=UUID(data["telecommand_definition_id"]),
            execute_at=_parse_form_datetime(data["execute_at"]),
            scheduled_pass_id=UUID(data["scheduled_pass_id"]) if data.get("scheduled_pass_id") else None,
            frame_hex=data.get("frame_hex") or None,
            priority=int(data["priority"]) if data.get("priority") else 5,
            requires_approval=data.get("requires_approval") == "on",
            created_by=data.get("created_by") or None,
        ))
    except (KeyError, TypeError, ValueError) as error:
        flash(f"Invalid telecommand data: {error}", "danger")
        return redirect(url_for("web.index"))

    if not result.succeeded:
        flash(f"Telecommand rejected: {result.reason}", "danger")
        return redirect(url_for("web.index"))

    flash("Telecommand scheduled successfully.", "success")
    return redirect(url_for("web.index"))


@web_bp.route("/telecommand/cancel/<telecommand_id>", methods=["POST"])
def cancel_telecommand(telecommand_id: str):
    try:
        _tc_service().cancel_telecommand(UUID(telecommand_id))
    except (ValueError, LookupError) as error:
        flash(str(error), "danger")
        return redirect(url_for("web.index"))
    flash("Telecommand cancelled.", "success")
    return redirect(url_for("web.index"))


@web_bp.route("/telecommand/approve/<telecommand_id>", methods=["POST"])
def approve_telecommand(telecommand_id: str):
    approved_by = request.form.get("approved_by") or "operator"
    try:
        _tc_service().approve_telecommand(UUID(telecommand_id), approved_by)
    except (ValueError, LookupError) as error:
        flash(str(error), "danger")
        return redirect(url_for("web.index"))
    flash("Telecommand approved.", "success")
    return redirect(url_for("web.index"))
