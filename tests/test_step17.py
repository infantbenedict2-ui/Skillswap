import os
import re
import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import patch

os.environ["SKILLSWAP_DATABASE_URL"] = "sqlite://"

import app as app_module
from app import app, run_development_server, _ensure_upload_directories
from app import initialize_database
from models import (
    Message,
    PasswordResetToken,
    Skill,
    SkillRequest,
    SkillSession,
    User,
    UserSkill,
    db,
)
from PIL import Image
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash


class Step17IntegrationTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, MAX_CONTENT_LENGTH=10 * 1024 * 1024)
        self.original_instance_path = app.instance_path
        self.upload_directory = tempfile.TemporaryDirectory()
        app.instance_path = self.upload_directory.name
        with app.app_context():
            db.drop_all()
            db.create_all()
            self.teacher = User(
                name="Journey Teacher",
                username="journey_teacher",
                email="journey_teacher@example.test",
                password_hash=generate_password_hash("teacher-password"),
                location="North City",
            )
            self.learner = User(
                name="Journey Learner",
                username="journey_learner",
                email="journey_learner@example.test",
                password_hash=generate_password_hash("learner-password"),
            )
            self.other = User(
                name="Unrelated Member",
                username="journey_other",
                email="journey_other@example.test",
                password_hash=generate_password_hash("other-password"),
            )
            self.skill = Skill(
                name="Journey Python",
                category="Programming",
                description="Practice Python",
            )
            self.skill_to_add = Skill(
                name="Journey Design",
                category="Design",
                description="Practice design",
            )
            db.session.add_all(
                [self.teacher, self.learner, self.other, self.skill, self.skill_to_add]
            )
            db.session.flush()
            self.request = SkillRequest(
                sender_id=self.learner.id,
                receiver_id=self.teacher.id,
                skill_id=self.skill.id,
                status="accepted",
            )
            db.session.add_all(
                [
                    self.request,
                    UserSkill(
                        user_id=self.teacher.id,
                        skill_id=self.skill.id,
                        skill_type="teach",
                        experience_level="intermediate",
                        availability="weekends",
                    ),
                    UserSkill(
                        user_id=self.learner.id,
                        skill_id=self.skill.id,
                        skill_type="learn",
                    ),
                ]
            )
            db.session.commit()
            self.teacher_id = self.teacher.id
            self.learner_id = self.learner.id
            self.other_id = self.other.id
            self.skill_id = self.skill.id
            self.skill_to_add_id = self.skill_to_add.id
            self.request_id = self.request.id

        self.teacher_client = self._client_for(self.teacher_id)
        self.learner_client = self._client_for(self.learner_id)
        self.other_client = self._client_for(self.other_id)

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        app.instance_path = self.original_instance_path
        self.upload_directory.cleanup()

    @staticmethod
    def _client_for(user_id):
        client = app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def test_experience_and_availability_filters_query_real_skill_listings(self):
        matched = app.test_client().get(
            "/find-skills?experience=intermediate&availability=weekends"
        )
        self.assertEqual(matched.status_code, 200)
        self.assertIn(b"Journey Teacher", matched.data)
        no_match = app.test_client().get(
            "/find-skills?experience=advanced&availability=weekends"
        )
        self.assertEqual(no_match.status_code, 200)
        self.assertNotIn(b"Journey Teacher</a>", no_match.data)
        self.assertEqual(
            app.test_client().get("/find-skills?availability=overnight").status_code,
            400,
        )
        self.assertEqual(
            app.test_client().get("/find-skills?experience=expert").status_code,
            400,
        )

    def test_teaching_listing_persists_filter_metadata(self):
        response = self.teacher_client.post(
            "/skills",
            data={
                "action": "add",
                "skill_id": self.skill_to_add_id,
                "skill_type": "teach",
                "experience_level": "advanced",
                "availability": "flexible",
            },
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            teach_listing = UserSkill.query.filter_by(
                user_id=self.teacher_id,
                skill_id=self.skill_to_add_id,
                skill_type="teach",
            ).one()
            self.assertEqual(teach_listing.experience_level, "advanced")
            self.assertEqual(teach_listing.availability, "flexible")
            existing_listing_id = UserSkill.query.filter_by(
                user_id=self.teacher_id,
                skill_id=self.skill_id,
                skill_type="teach",
            ).one().id
        updated = self.teacher_client.post(
            "/skills",
            data={
                "action": "update",
                "user_skill_id": str(existing_listing_id),
                "experience_level": "beginner",
                "availability": "evenings",
            },
        )
        self.assertEqual(updated.status_code, 302)
        filtered = app.test_client().get(
            "/find-skills?experience=beginner&availability=evenings&q=Journey+Python"
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertIn(b"Journey Teacher", filtered.data)

    def test_password_reset_email_token_is_private_expiring_and_single_use(self):
        with (
            patch.dict(
                os.environ,
                {
                    "SKILLSWAP_EMAIL_ENABLED": "true",
                    "SKILLSWAP_SMTP_HOST": "smtp.example.test",
                    "SKILLSWAP_EMAIL_FROM": "noreply@example.test",
                    "SKILLSWAP_PUBLIC_URL": "https://skillswap.example.test",
                },
            ),
            patch.object(app_module, "send_notification_email") as send_email,
        ):
            response = app.test_client().post(
                "/forgot-password",
                data={"email": "journey_learner@example.test"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"If an active account matches", response.data)
            send_email.assert_called_once()
            message = send_email.call_args.args[2]
            token_match = re.search(
                r"https://skillswap\.example\.test/reset-password/([A-Za-z0-9_-]+)",
                message,
            )
            self.assertIsNotNone(token_match)
            token = token_match.group(1)

        reset_page = app.test_client().get(f"/reset-password/{token}")
        self.assertEqual(reset_page.status_code, 200)
        reset_client = app.test_client()
        reset_response = reset_client.post(
            f"/reset-password/{token}",
            data={
                "password": "replacement-password",
                "confirm_password": "replacement-password",
            },
        )
        self.assertEqual(reset_response.status_code, 302)
        with app.app_context():
            learner = db.session.get(User, self.learner_id)
            self.assertTrue(
                check_password_hash(learner.password_hash, "replacement-password")
            )
            self.assertIsNotNone(
                PasswordResetToken.query.filter_by(user_id=self.learner_id)
                .one()
                .used_at
            )
        replay = app.test_client().get(f"/reset-password/{token}")
        self.assertEqual(replay.status_code, 400)

    def test_password_reset_request_does_not_disclose_unknown_accounts(self):
        with (
            patch.dict(
                os.environ,
                {
                    "SKILLSWAP_EMAIL_ENABLED": "true",
                    "SKILLSWAP_SMTP_HOST": "smtp.example.test",
                    "SKILLSWAP_EMAIL_FROM": "noreply@example.test",
                    "SKILLSWAP_PUBLIC_URL": "https://skillswap.example.test",
                },
            ),
            patch.object(app_module, "send_notification_email") as send_email,
        ):
            known = app.test_client().post(
                "/forgot-password",
                data={"email": "journey_learner@example.test"},
            )
            unknown = app.test_client().post(
                "/forgot-password",
                data={"email": "missing@example.test"},
            )
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(
            re.search(rb"If an active account matches[^<]*", known.data).group(0),
            re.search(rb"If an active account matches[^<]*", unknown.data).group(0),
        )
        self.assertEqual(send_email.call_count, 1)

    def test_password_reset_reports_missing_email_configuration_without_creating_token(self):
        response = app.test_client().post(
            "/forgot-password",
            data={"email": "journey_learner@example.test"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"no reset email was sent", response.data)
        with app.app_context():
            self.assertEqual(
                PasswordResetToken.query.filter_by(user_id=self.learner_id).count(),
                0,
            )

    def test_expired_password_reset_tokens_are_rejected(self):
        raw_token = "expired-reset-token"
        with app.app_context():
            db.session.add(
                PasswordResetToken(
                    user_id=self.learner_id,
                    token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                    expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                )
            )
            db.session.commit()
        response = app.test_client().get(f"/reset-password/{raw_token}")
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"invalid or expired", response.data)

    def test_profile_upload_is_reencoded_and_private_profiles_are_protected(self):
        image_buffer = BytesIO()
        Image.new("RGB", (4, 4), color="blue").save(image_buffer, format="PNG")
        image_buffer.seek(0)
        response = self.learner_client.post(
            "/profile/edit",
            data={
                "name": "Journey Learner",
                "username": "journey_learner",
                "location": "",
                "bio": "",
                "profile_image": "",
                "profile_image_file": (image_buffer, "avatar.png", "image/png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            learner = db.session.get(User, self.learner_id)
            image_url = learner.profile_image
            learner.profile_visibility = "private"
            db.session.commit()
        filename = image_url.rsplit("/", 1)[-1]
        image_response = self.learner_client.get(f"/profile-images/{filename}")
        self.assertEqual(image_response.status_code, 200)
        self.assertEqual(image_response.mimetype, "image/png")
        image_response.close()
        self.assertEqual(
            self.other_client.get(f"/profile-images/{filename}").status_code,
            404,
        )
        invalid = self.other_client.post(
            "/profile/edit",
            data={
                "name": "Unrelated Member",
                "username": "journey_other",
                "location": "",
                "bio": "",
                "profile_image": "",
                "profile_image_file": (BytesIO(b"not an image"), "bad.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertIn(b"Upload a valid PNG", invalid.data)

    def test_chat_attachment_is_downloadable_only_by_participants(self):
        sent = self.learner_client.post(
            "/messages",
            data={
                "receiver_id": str(self.teacher_id),
                "message": "",
                "attachment": (
                    BytesIO(b"hello from a controlled test"),
                    "../../notes.txt",
                    "text/plain",
                ),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(sent.status_code, 302)
        with app.app_context():
            message = Message.query.filter_by(
                sender_id=self.learner_id,
                receiver_id=self.teacher_id,
            ).one()
            message_id = message.id
            self.assertEqual(message.attachment_name, "notes.txt")
            self.assertRegex(message.attachment_path, r"^[0-9a-f]{32}\.txt$")
        download = self.teacher_client.get(
            f"/messages/attachments/{message_id}"
        )
        self.assertEqual(download.status_code, 200)
        self.assertIn("attachment", download.headers["Content-Disposition"])
        self.assertEqual(download.data, b"hello from a controlled test")
        download.close()
        self.assertEqual(
            self.other_client.get(
                f"/messages/attachments/{message_id}"
            ).status_code,
            403,
        )

    def test_chat_image_attachment_is_reencoded_before_download(self):
        image_buffer = BytesIO()
        Image.new("RGB", (8, 8), color="red").save(image_buffer, format="PNG")
        image_buffer.write(b"<script>not executable content</script>")
        image_buffer.seek(0)
        sent = self.learner_client.post(
            "/messages",
            data={
                "receiver_id": str(self.teacher_id),
                "message": "Image attached",
                "attachment": (image_buffer, "lesson.png", "image/png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(sent.status_code, 302)
        with app.app_context():
            message = Message.query.filter_by(
                sender_id=self.learner_id,
                receiver_id=self.teacher_id,
            ).one()
            message_id = message.id
        downloaded = self.teacher_client.get(
            f"/messages/attachments/{message_id}"
        )
        self.assertEqual(downloaded.status_code, 200)
        self.assertNotIn(b"<script>", downloaded.data)
        with Image.open(BytesIO(downloaded.data)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (8, 8))
        downloaded.close()

    def test_chat_rejects_executable_attachments_and_upload_limit(self):
        rejected = self.learner_client.post(
            "/messages",
            data={
                "receiver_id": str(self.teacher_id),
                "attachment": (BytesIO(b"\x00\x01\x02\x03"), "malware.exe"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(rejected.status_code, 302)
        with app.app_context():
            self.assertEqual(Message.query.count(), 0)
        for filename, payload, content_type in (
            ("mismatch.png", b"not image bytes", "text/plain"),
            ("mismatch.pdf", b"%PDF-1.7\n", "application/octet-stream"),
        ):
            mismatch = self.learner_client.post(
                "/messages",
                data={
                    "receiver_id": str(self.teacher_id),
                    "attachment": (
                        BytesIO(payload),
                        filename,
                        content_type,
                    ),
                },
                content_type="multipart/form-data",
            )
            self.assertEqual(mismatch.status_code, 302)
        with app.app_context():
            self.assertEqual(Message.query.count(), 0)
        previous_limit = app.config["MAX_CONTENT_LENGTH"]
        app.config["MAX_CONTENT_LENGTH"] = 1024
        try:
            oversized = self.learner_client.post(
                "/messages",
                data={
                    "receiver_id": str(self.teacher_id),
                    "attachment": (BytesIO(b"x" * 2048), "large.txt"),
                },
                content_type="multipart/form-data",
            )
        finally:
            app.config["MAX_CONTENT_LENGTH"] = previous_limit
        self.assertEqual(oversized.status_code, 413)
        oversized.close()

    def test_sqlite_foreign_keys_and_persisted_relationships(self):
        with app.app_context():
            foreign_key_violations = db.session.execute(
                text("PRAGMA foreign_key_check")
            ).all()
            self.assertEqual(foreign_key_violations, [])
            self.assertEqual(
                SkillSession.query.filter_by(skill_request_id=self.request_id).count(),
                0,
            )
            self.assertEqual(
                SkillRequest.query.filter_by(id=self.request_id).one().skill.name,
                "Journey Python",
            )
            session = app_module.SkillSession(
                skill_request_id=self.request_id,
                skill_id=self.skill_id,
                teacher_id=self.teacher_id,
                learner_id=self.learner_id,
                title="Constraint check",
                date=(datetime.now(timezone.utc).date() + timedelta(days=2)),
                start_time=datetime.strptime("10:00", "%H:%M").time(),
                end_time=datetime.strptime("11:00", "%H:%M").time(),
                status="SCHEDULED",
            )
            db.session.add(session)
            db.session.commit()
            self.assertEqual(
                SkillSession.query.filter_by(id=session.id).one().teacher.id,
                self.teacher_id,
            )
            duplicate_listing = UserSkill(
                user_id=self.teacher_id,
                skill_id=self.skill_id,
                skill_type="teach",
                experience_level="intermediate",
                availability="weekends",
            )
            db.session.add(duplicate_listing)
            with self.assertRaises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_development_server_uses_documented_defaults_and_validates_port(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(app, "run") as run_server,
        ):
            run_development_server()
        run_server.assert_called_once_with(
            host="127.0.0.1",
            port=5000,
            debug=False,
            use_reloader=False,
        )

        with (
            patch.dict(
                os.environ,
                {"SKILLSWAP_HOST": "127.0.0.1", "SKILLSWAP_PORT": "abc"},
                clear=True,
            ),
            patch.object(app, "run") as run_server,
        ):
            with self.assertRaisesRegex(RuntimeError, "SKILLSWAP_PORT"):
                run_development_server()
        run_server.assert_not_called()

    def test_upload_directories_are_created_and_write_checked(self):
        test_instance = os.path.join(self.upload_directory.name, "new-instance")
        app.instance_path = test_instance
        _ensure_upload_directories()
        for folder in ("", "messages", "profile"):
            directory = os.path.join(test_instance, "uploads", folder)
            self.assertTrue(os.path.isdir(directory))
            self.assertTrue(os.access(directory, os.W_OK))

    def test_additive_schema_migration_preserves_existing_skill_and_message_rows(self):
        with app.app_context():
            db.session.execute(text("DROP TABLE user_skill"))
            db.session.execute(
                text(
                    "CREATE TABLE user_skill ("
                    "id INTEGER PRIMARY KEY, "
                    "user_id INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE, "
                    "skill_id INTEGER NOT NULL REFERENCES skill(id) ON DELETE CASCADE, "
                    "skill_type VARCHAR(10) NOT NULL, "
                    "CONSTRAINT unique_user_skill_type "
                    "UNIQUE (user_id, skill_id, skill_type))"
                )
            )
            db.session.execute(
                text(
                    "INSERT INTO user_skill (user_id, skill_id, skill_type) "
                    "VALUES (:user_id, :skill_id, 'teach')"
                ),
                {"user_id": self.teacher_id, "skill_id": self.skill_id},
            )
            db.session.execute(text("DROP TABLE message"))
            db.session.execute(
                text(
                    "CREATE TABLE message ("
                    "id INTEGER PRIMARY KEY, "
                    "sender_id INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE, "
                    "receiver_id INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE, "
                    "message TEXT NOT NULL, "
                    "created_at DATETIME NOT NULL, "
                    "is_read BOOLEAN NOT NULL DEFAULT 0)"
                )
            )
            db.session.execute(
                text(
                    "INSERT INTO message "
                    "(sender_id, receiver_id, message, created_at, is_read) "
                    "VALUES (:sender_id, :receiver_id, 'Existing message', "
                    "'2026-01-01 10:00:00', 0)"
                ),
                {"sender_id": self.learner_id, "receiver_id": self.teacher_id},
            )
            db.session.commit()

            initialize_database()

            self.assertEqual(
                {
                    column["name"]
                    for column in inspect(db.engine).get_columns("user_skill")
                }
                & {"experience_level", "availability"},
                {"experience_level", "availability"},
            )
            self.assertEqual(
                {
                    column["name"]
                    for column in inspect(db.engine).get_columns("message")
                }
                & {"attachment_name", "attachment_path", "attachment_type"},
                {"attachment_name", "attachment_path", "attachment_type"},
            )
            self.assertEqual(UserSkill.query.filter_by(user_id=self.teacher_id).count(), 1)
            self.assertEqual(
                Message.query.filter_by(message="Existing message").count(),
                1,
            )
            self.assertTrue(inspect(db.engine).has_table("password_reset_token"))

    def test_controlled_two_user_swap_to_completed_rating_journey(self):
        created_request = self.learner_client.post(
            "/requests/create",
            data={
                "receiver_id": str(self.teacher_id),
                "skill_id": str(self.skill_id),
                "message": "Would you help me practice?",
            },
        )
        self.assertEqual(created_request.status_code, 302)
        with app.app_context():
            pending_request = SkillRequest.query.filter_by(
                sender_id=self.learner_id,
                receiver_id=self.teacher_id,
                status="pending",
            ).one()
            pending_id = pending_request.id
        accepted = self.teacher_client.post(f"/requests/{pending_id}/accept")
        self.assertEqual(accepted.status_code, 302)

        message = self.learner_client.post(
            "/messages",
            data={
                "receiver_id": str(self.teacher_id),
                "message": "Let's schedule a lesson.",
            },
        )
        self.assertEqual(message.status_code, 302)
        session_date = (datetime.now(timezone.utc).date() + timedelta(days=2)).isoformat()
        created_session = self.learner_client.post(
            "/api/sessions",
            json={
                "skill_request_id": pending_id,
                "teacher_id": self.teacher_id,
                "learner_id": self.learner_id,
                "title": "Python practice",
                "date": session_date,
                "start_time": "10:00",
                "end_time": "11:00",
            },
        )
        self.assertEqual(created_session.status_code, 201, created_session.get_json())
        session_id = created_session.get_json()["session"]["id"]
        self.assertEqual(
            self.teacher_client.post(f"/api/sessions/{session_id}/start").status_code,
            200,
        )
        first_confirmation = self.teacher_client.post(
            f"/api/sessions/{session_id}/confirm-completion"
        )
        self.assertEqual(
            first_confirmation.get_json()["session"]["status"],
            "IN_PROGRESS",
        )
        final_confirmation = self.learner_client.post(
            f"/api/sessions/{session_id}/confirm-completion"
        )
        self.assertEqual(
            final_confirmation.get_json()["session"]["status"],
            "COMPLETED",
        )
        rating = self.learner_client.post(
            "/api/ratings",
            json={
                "session_id": session_id,
                "rating": 5,
                "comment": "Clear and useful lesson.",
            },
        )
        self.assertEqual(rating.status_code, 201)
        teacher_notifications = self.teacher_client.get(
            "/api/notifications?unread=true"
        )
        self.assertEqual(teacher_notifications.status_code, 200)
        notification_types = {
            entry["type"]
            for entry in teacher_notifications.get_json()["notifications"]
        }
        self.assertTrue(
            {"skill_request", "message", "session_created", "rating"}
            .issubset(notification_types)
        )
        with app.app_context():
            self.assertEqual(
                SkillSession.query.filter_by(
                    id=session_id,
                    status="COMPLETED",
                ).count(),
                1,
            )
