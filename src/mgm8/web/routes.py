from datetime import datetime, timezone
from uuid import UUID

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for

from mgm8.application.pass_scheduler import PassSchedulerService, SchedulePassRequest

web_bp = Blueprint("web", __name__, template_folder="templates")


def _service() -> PassSchedulerService:
    return current_app.config["PASS_SCHEDULER"]


@web_bp.route("/")
def index():
    service = _service()
    all_passes = service.list_passes()
    scheduled = [item for item in all_passes if item.status.value == "Scheduled"]
    in_progress = [item for item in all_passes if item.status.value == "InProgress"]
    history = [item for item in all_passes if item.status.value in {"Completed", "Cancelled", "Failed", "Missed"}]
    satellite_ids = sorted({str(item.satellite_id) for item in all_passes})

    return render_template(
        "index.html",
        scheduled_passes=scheduled[:10],
        in_progress_passes=in_progress[:10],
        history_passes=history[:20],
        all_passes=all_passes,
        satellite_ids=satellite_ids,
        events=service.list_events(30),
        conflicts=service.list_conflicts(10),
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
