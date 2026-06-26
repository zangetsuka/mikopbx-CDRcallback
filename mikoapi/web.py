from __future__ import annotations

import csv
import io
import logging
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

from .callback import normalize_phone
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
        return _db().get_callback_settings(config.callback.settings_defaults())

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
        tasks = _db().get_callback_tasks(limit=limit, status=status, phone=phone)
        return jsonify({"tasks": tasks, "total": len(tasks)})

    @app.route("/api/callback/task", methods=["POST"])
    def callback_create_task():
        payload = request.get_json(silent=True) or {}
        phone = normalize_phone(payload.get("phone"))
        if not phone:
            return jsonify({"error": "Phone number is required"}), 400

        delay_seconds = payload.get("delay_seconds")
        if delay_seconds in (None, ""):
            delay_seconds = int(_callback_settings().get("delay_minutes", 0)) * 60
        try:
            delay_seconds = int(delay_seconds or 0)
            priority = int(payload.get("priority") or 5)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid delay or priority value"}), 400

        task_id = _db().create_callback_task(
            phone=phone,
            call_type=str(payload.get("call_type") or "manual"),
            call_id=payload.get("call_id"),
            linkedid=payload.get("linkedid"),
            delay_seconds=delay_seconds,
            priority=priority,
            source="manual",
            max_retries=config.callback.max_retries,
        )
        logger.info("Created manual callback task #%s for %s", task_id, phone)
        return jsonify(
            {
                "success": True,
                "task_id": task_id,
                "message": f"Task #{task_id} created for {phone}",
            }
        )

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
        updates: dict[str, Any] = {}
        for key, value in payload.items():
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
        payload = request.get_json(silent=True) or {}
        phone = normalize_phone(payload.get("phone"))
        if not phone:
            return jsonify({"error": "Phone number is required"}), 400

        task_id = _db().create_callback_task(
            phone=phone,
            call_type="test",
            delay_seconds=10,
            priority=10,
            source="test",
            max_retries=1,
        )
        logger.info("Created test callback task #%s for %s", task_id, phone)
        return jsonify(
            {
                "success": True,
                "task_id": task_id,
                "message": f"Test callback scheduled for {phone}",
            }
        )

    @app.errorhandler(Exception)
    def handle_exception(exc: Exception):
        if isinstance(exc, HTTPException):
            return exc
        logger.exception("Unhandled web exception: %s", exc)
        return jsonify({"error": "Internal server error"}), 500

    return app