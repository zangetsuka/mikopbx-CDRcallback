from __future__ import annotations

import csv
import io
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from .callback import (
    build_task_schedule,
    format_work_days,
    gather_live_pbx_metrics,
    get_work_time_intervals,
    normalize_phone,
    normalize_work_time_intervals,
)
from .config import AppConfig
from .service import ServiceContainer


def create_app(config: AppConfig, services: ServiceContainer) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config["SECRET_KEY"] = config.secret_key
    app.config["SERVICES"] = services
    CORS(app)

    PUBLIC_PATHS = {"/login", "/logout", "/health", "/api/health"}

    @app.before_request
    def _require_login():
        if not config.web_auth_enabled:
            return None
        path = request.path or "/"
        if path in PUBLIC_PATHS or path.startswith("/static/"):
            return None
        if session.get("authed"):
            return None
        if path.startswith("/api/"):
            return jsonify({"error": "unauthorized"}), 401
        return redirect(url_for("login", next=path))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not config.web_auth_enabled or session.get("authed"):
            return redirect(url_for("index"))
        error = None
        if request.method == "POST":
            password = (request.form.get("password") or "").strip()
            if password and password == str(config.web_auth_password):
                session["authed"] = True
                session.permanent = True
                nxt = request.args.get("next") or request.form.get("next") or ""
                if not nxt.startswith("/"):
                    nxt = url_for("index")
                return redirect(nxt)
            error = "Неверный пароль"
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    logger = logging.getLogger("web")

    def _db():
        return services.db

    def _callback_settings() -> dict[str, Any]:
        settings = _db().get_callback_settings(config.callback.settings_defaults())
        intervals = get_work_time_intervals(settings)
        settings["work_time_intervals"] = intervals
        if intervals:
            first_interval = intervals[0]
            settings["work_hours_start"] = first_interval["start"]
            settings["work_hours_end"] = first_interval["end"]
            settings["work_days"] = format_work_days(first_interval["days"])
        return settings

    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @app.route("/")
    def index():
        return render_template("dashboard.html")

    @app.route("/calls")
    def calls_page():
        return render_template("calls.html")

    @app.route("/callback")
    def callback_page():
        return render_template("callback.html")

    @app.route("/callback/tasks")
    def callback_tasks_page():
        return render_template("tasks.html")

    @app.route("/api/callback/tasks/clear", methods=["POST"])
    def callback_tasks_clear():
        result = _db().clear_callback_tasks()
        return jsonify({"success": True, **result})

    @app.route("/api/maintenance/clear-cdr", methods=["POST"])
    def maintenance_clear_cdr():
        result = _db().clear_cdr()
        return jsonify({"success": True, **result})

    @app.route("/health")
    def health():
        return jsonify(
            {
                "ok": True,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "status": services.get_status(),
            }
        )

    _live_cache = {"ts": 0.0, "data": None}

    @app.route("/api/pbx/live")
    def pbx_live():
        now = time.time()
        if _live_cache["data"] is not None and (now - _live_cache["ts"]) < 5.0:
            return jsonify(_live_cache["data"])
        try:
            data = gather_live_pbx_metrics(config)
        except Exception as exc:  # pragma: no cover
            logging.getLogger("web").warning("live metrics failed: %s", exc)
            data = {"available": False, "error": str(exc)}
        _live_cache["ts"] = now
        _live_cache["data"] = data
        return jsonify(data)


    @app.route("/api/search")
    def global_search():
        q = (request.args.get("q") or "").strip()
        result = {"query": q, "calls": [], "tasks": [], "operators": []}
        if len(q) < 2:
            return jsonify(result)
        db = services.db
        try:
            calls = db.get_calls(search=q, limit=6)
            for c in calls:
                result["calls"].append({
                    "id": c.get("id"),
                    "src": c.get("src_num"),
                    "dst": c.get("dst_num"),
                    "type": c.get("call_type"),
                    "started_at": c.get("started_at") or c.get("start_time"),
                    "disposition": c.get("disposition"),
                })
        except Exception as exc:
            logging.getLogger("web").warning("search calls failed: %s", exc)
        try:
            for t in db.search_tasks(q, limit=6):
                result["tasks"].append({
                    "id": t.get("id"),
                    "phone": t.get("phone"),
                    "status": t.get("status"),
                    "operator": t.get("operator_extension"),
                    "attempts": t.get("attempts"),
                    "scheduled_at": t.get("scheduled_at"),
                })
        except Exception as exc:
            logging.getLogger("web").warning("search tasks failed: %s", exc)
        try:
            for o in db.search_operators(q, limit=6):
                result["operators"].append({
                    "ext": o.get("ext"),
                    "total": o.get("total"),
                    "completed": o.get("completed"),
                })
        except Exception as exc:
            logging.getLogger("web").warning("search operators failed: %s", exc)
        return jsonify(result)

    @app.route("/api/service/status")
    def service_status():
        return jsonify(services.get_status())

    @app.route("/api/stats")
    def api_stats():
        days = request.args.get("days", 7, type=int)
        stats = _db().get_statistics(days)
        total_calls = sum(item["total"] for item in stats.values())
        total_voicemail = sum(item["voicemail"] for item in stats.values())
        total_duration = sum(item["total_duration"] for item in stats.values())

        return jsonify(
            {
                "by_type": stats,
                "total": {
                    "calls": total_calls,
                    "voicemail": total_voicemail,
                    "duration": total_duration,
                    "total_in_db": _db().get_total_count(),
                },
                "daily": _db().get_daily_stats(days),
                "days": days,
            }
        )

    @app.route("/api/calls")
    def api_calls():
        call_type = request.args.get("type") or None
        search = request.args.get("search") or None
        limit = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)

        return jsonify(
            {
                "calls": _db().get_calls(
                    call_type=call_type,
                    search=search,
                    limit=limit,
                    offset=offset,
                ),
                "total": _db().get_total_count(call_type=call_type, search=search),
                "limit": limit,
                "offset": offset,
            }
        )

    @app.route("/api/call/<int:call_id>")
    def api_call_detail(call_id: int):
        call = _db().get_call(call_id)
        if not call:
            return jsonify({"error": "Call not found"}), 404

        call["segments"] = _db().get_call_segments(call_id)
        return jsonify(call)

    @app.route("/api/export/csv")
    def export_csv():
        call_type = request.args.get("type") or None
        search = request.args.get("search") or None
        calls = _db().get_calls(call_type=call_type, search=search, limit=5000, offset=0)

        output = io.StringIO()
        if calls:
            writer = csv.DictWriter(output, fieldnames=list(calls[0].keys()))
            writer.writeheader()
            writer.writerows(calls)

        return send_file(
            io.BytesIO(output.getvalue().encode("utf-8")),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"calls_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )

    @app.route("/api/voicemail/detailed")
    def api_voicemail_detailed():
        days = request.args.get("days", 7, type=int)
        calls = _db().get_calls(call_type="voicemail", limit=5000, offset=0)
        cutoff = datetime.now() - timedelta(days=max(1, days))
        filtered_calls = []
        for call in calls:
            start_time = str(call.get("start_time") or "")[:19]
            if not start_time:
                continue
            try:
                if datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S") >= cutoff:
                    filtered_calls.append(call)
            except ValueError:
                filtered_calls.append(call)
        durations = [
            int(call.get("voicemail_duration", 0) or 0) for call in filtered_calls
        ]

        return jsonify(
            {
                "days": days,
                "total": len(filtered_calls),
                "total_duration": sum(durations),
                "avg_duration": (sum(durations) / len(durations)) if durations else 0,
                "max_duration": max(durations) if durations else 0,
                "min_duration": min(durations) if durations else 0,
            }
        )

    @app.route("/api/callback/tasks")
    def callback_tasks():
        limit = request.args.get("limit", 50, type=int)
        status = request.args.get("status") or None
        phone = request.args.get("phone") or None
        operator = request.args.get("operator") or None
        tasks = _db().get_callback_tasks(limit=limit, status=status, phone=phone, operator=operator)
        return jsonify({"tasks": tasks, "total": len(tasks)})

    def _create_callback_task_response(payload: dict[str, Any], source: str, default_call_type: str, max_retries: int) -> tuple[dict[str, Any], int]:
        phone = normalize_phone(payload.get("phone"))
        if not phone:
            return {"error": "Phone number is required"}, 400

        delay_seconds = payload.get("delay_seconds")
        if delay_seconds in (None, ""):
            delay_seconds = int(_callback_settings().get("delay_minutes", 0)) * 60
        try:
            delay_seconds = int(delay_seconds or 0)
            priority = int(payload.get("priority") or 5)
        except (TypeError, ValueError):
            return {"error": "Invalid delay or priority value"}, 400

        settings = _callback_settings()
        schedule = build_task_schedule(settings, delay_seconds)

        task_id = _db().create_callback_task(
            phone=phone,
            call_type=str(payload.get("call_type") or default_call_type),
            call_id=payload.get("call_id"),
            linkedid=payload.get("linkedid"),
            delay_seconds=schedule["delay_seconds"],
            priority=priority,
            source=source,
            max_retries=max_retries,
            created_at=schedule["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
            requested_at=schedule["requested_at"].strftime("%Y-%m-%d %H:%M:%S"),
            scheduled_at=schedule["scheduled_at"].strftime("%Y-%m-%d %H:%M:%S"),
            schedule_reason=schedule["schedule_reason"],
        )
        logger.info("Created %s callback task #%s for %s", source, task_id, phone)
        message = f"Task #{task_id} created for {phone}"
        if schedule["deferred_to_work_hours"]:
            message += (
                f" and deferred to work hours at "
                f"{schedule['scheduled_at'].strftime('%Y-%m-%d %H:%M:%S')}"
            )
        return (
            {
                "success": True,
                "task_id": task_id,
                "message": message,
                "scheduled_at": schedule["scheduled_at"].strftime("%Y-%m-%d %H:%M:%S"),
                "requested_at": schedule["requested_at"].strftime("%Y-%m-%d %H:%M:%S"),
                "schedule_reason": schedule["schedule_reason"],
                "deferred_to_work_hours": schedule["deferred_to_work_hours"],
            },
            200,
        )

    @app.route("/api/callback/task", methods=["POST"])
    @app.route("/api/callback/tasks", methods=["POST"])
    def callback_create_task():
        payload = request.get_json(silent=True) or {}
        body, status_code = _create_callback_task_response(
            payload,
            source="manual",
            default_call_type="manual",
            max_retries=config.callback.max_retries,
        )
        return jsonify(body), status_code

    @app.route("/api/callback/task/<int:task_id>")
    def callback_get_task(task_id: int):
        task = _db().get_callback_task(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        return jsonify(task)

    @app.route("/api/callback/task/<int:task_id>/cancel", methods=["POST"])
    def callback_cancel_task(task_id: int):
        if not _db().cancel_callback_task(task_id):
            return jsonify({"error": "Task cannot be cancelled"}), 400
        return jsonify({"success": True, "message": f"Task #{task_id} cancelled"})

    @app.route("/api/callback/settings")
    def callback_get_settings():
        return jsonify(_callback_settings())

    @app.route("/api/callback/settings", methods=["POST"])
    def callback_update_settings():
        payload = request.get_json(silent=True) or {}
        defaults = config.callback.settings_defaults()
        current_settings = _callback_settings()
        updates: dict[str, Any] = {}
        for key, value in payload.items():
            if key == "work_time_intervals":
                intervals = normalize_work_time_intervals(
                    value,
                    current_settings.get("work_days"),
                )
                work_hours_enabled = _coerce_bool(
                    payload.get(
                        "work_hours_enabled",
                        current_settings.get("work_hours_enabled", False),
                    )
                )
                if work_hours_enabled and not intervals:
                    return jsonify(
                        {
                            "error": (
                                "Add at least one work time interval or disable work hours"
                            )
                        }
                    ), 400
                updates[key] = intervals
                if intervals:
                    first_interval = intervals[0]
                    updates["work_hours_start"] = first_interval["start"]
                    updates["work_hours_end"] = first_interval["end"]
                    updates["work_days"] = format_work_days(first_interval["days"])
                continue
            if key not in defaults:
                continue
            default_value = defaults[key]
            try:
                if isinstance(default_value, bool):
                    updates[key] = _coerce_bool(value)
                elif isinstance(default_value, int):
                    updates[key] = int(value)
                else:
                    updates[key] = value
            except (TypeError, ValueError):
                continue
        if (
            "work_time_intervals" not in updates
            and {"work_hours_start", "work_hours_end", "work_days"} & updates.keys()
        ):
            merged_settings = dict(current_settings)
            merged_settings.update(updates)
            updates["work_time_intervals"] = normalize_work_time_intervals(
                [
                    {
                        "start": merged_settings.get("work_hours_start"),
                        "end": merged_settings.get("work_hours_end"),
                        "days": merged_settings.get("work_days"),
                    }
                ],
                merged_settings.get("work_days"),
            )
        if updates:
            _db().update_callback_settings(updates)
        return jsonify(
            {
                "success": True,
                "settings": _callback_settings(),
                "message": "Settings updated",
            }
        )

    @app.route("/api/callback/task/<int:task_id>/call-now", methods=["POST"])
    def callback_call_now(task_id: int):
        if not _db().get_callback_task(task_id):
            return jsonify({"error": "Task not found"}), 404
        _db().reschedule_callback_task(task_id, 0)
        return jsonify({"success": True, "message": f"Task #{task_id} scheduled now"})

    @app.route("/api/callback/task/<int:task_id>/retry", methods=["POST"])
    def callback_retry(task_id: int):
        if not _db().get_callback_task(task_id):
            return jsonify({"error": "Task not found"}), 404
        payload = request.get_json(silent=True) or {}
        delay_seconds = int(payload.get("delay_seconds", 0) or 0)
        _db().reschedule_callback_task(task_id, delay_seconds)
        return jsonify({"success": True, "message": f"Task #{task_id} rescheduled"})

    @app.route("/api/callback/task/<int:task_id>/attempts")
    def callback_attempts(task_id: int):
        if not _db().get_callback_task(task_id):
            return jsonify({"error": "Task not found"}), 404
        return jsonify({"attempts": _db().get_callback_attempts(task_id)})

    @app.route("/api/callback/stats")
    def callback_stats():
        days = request.args.get("days", 7, type=int)
        return jsonify(_db().get_callback_statistics(days))

    @app.route("/api/callback/analytics")
    def callback_analytics():
        days = request.args.get("days", 7, type=int)
        return jsonify(_db().get_callback_analytics(days))

    @app.route("/api/callback/phone/<phone>")
    def callback_phone_tasks(phone: str):
        normalized = normalize_phone(phone)
        tasks = _db().get_callback_tasks_by_phone(normalized, limit=20)
        return jsonify({"phone": normalized, "tasks": tasks, "total": len(tasks)})

    @app.route("/api/callback/test", methods=["POST"])
    def callback_test():
        body, status_code = _create_callback_task_response(
            request.get_json(silent=True) or {},
            source="test",
            default_call_type="test",
            max_retries=1,
        )
        if status_code != 200:
            return jsonify(body), status_code
        body["message"] = body["message"].replace("Task #", "Test callback task #")
        return jsonify(body)

    @app.errorhandler(Exception)
    def handle_exception(exc: Exception):
        if isinstance(exc, HTTPException):
            return exc
        logger.exception("Unhandled web exception: %s", exc)
        return jsonify({"error": "Internal server error"}), 500

    return app
