import os
import unittest
from datetime import date, time, timedelta, timezone
from unittest.mock import patch

os.environ["SKILLSWAP_DATABASE_URL"] = "sqlite://"

from app import app
from models import (
    Notification,
    Skill,
    SkillRequest,
    SkillSession,
    User,
    UserSkill,
    db,
)
from services.email_notifications import send_notification_email


class NotificationApiTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        with app.app_context():
            db.drop_all()
            db.create_all()
            self.teacher = User(
                name="Notify Teacher",
                username="notify_teacher",
                email="notify_teacher@example.com",
                password_hash="unused",
            )
            self.learner = User(
                name="Notify Learner",
                username="notify_learner",
                email="notify_learner@example.com",
                password_hash="unused",
            )
            self.other = User(
                name="Notify Other",
                username="notify_other",
                email="notify_other@example.com",
                password_hash="unused",
            )
            self.skill = Skill(name="Notification Python", category="Programming")
            db.session.add_all([self.teacher, self.learner, self.other, self.skill])
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
                        user_id=self.learner.id,
                        skill_id=self.skill.id,
                        skill_type="learn",
                    ),
                    UserSkill(
                        user_id=self.teacher.id,
                        skill_id=self.skill.id,
                        skill_type="teach",
                    ),
                ]
            )
            db.session.commit()
            self.teacher_id = self.teacher.id
            self.learner_id = self.learner.id
            self.other_id = self.other.id
            self.skill_id = self.skill.id
            self.request_id = self.request.id

        self.teacher_client = self._client_for(self.teacher_id)
        self.learner_client = self._client_for(self.learner_id)
        self.other_client = self._client_for(self.other_id)

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    @staticmethod
    def _client_for(user_id):
        client = app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def _add_notification(self, user_id, message="Test update", kind="message"):
        with app.app_context():
            notification = Notification(
                user_id=user_id,
                title="Test notification",
                message=message,
                type=kind,
                related_entity_id=17,
            )
            db.session.add(notification)
            db.session.commit()
            return notification.id

    def test_create_list_filter_unread_count_and_pagination(self):
        read_id = self._add_notification(self.learner_id, kind="message")
        unread_id = self._add_notification(self.learner_id, kind="rating")
        with app.app_context():
            db.session.get(Notification, read_id).is_read = True
            db.session.commit()

        all_response = self.learner_client.get(
            "/api/notifications?page=1&per_page=1"
        )
        self.assertEqual(all_response.status_code, 200)
        self.assertEqual(all_response.get_json()["pagination"]["total"], 2)
        self.assertEqual(len(all_response.get_json()["notifications"]), 1)

        unread_response = self.learner_client.get("/api/notifications?unread=true")
        self.assertEqual(
            [item["id"] for item in unread_response.get_json()["notifications"]],
            [unread_id],
        )
        self.assertEqual(
            self.learner_client.get("/api/notifications/unread-count").get_json(),
            {"unread_count": 1},
        )
        self.assertIn("title", unread_response.get_json()["notifications"][0])
        self.assertIn("created_at", unread_response.get_json()["notifications"][0])
        self.assertIn("href", unread_response.get_json()["notifications"][0])
        self.assertEqual(
            self.learner_client.get("/api/notifications?unread=yes").status_code,
            400,
        )

    def test_mark_single_read_mark_all_and_delete(self):
        first_id = self._add_notification(self.learner_id)
        second_id = self._add_notification(self.learner_id)
        response = self.learner_client.post(
            f"/api/notifications/{first_id}/read"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["notification"]["is_read"])

        response = self.learner_client.post("/api/notifications/read-all")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["updated_count"], 1)
        self.assertEqual(
            self.learner_client.get("/api/notifications/unread-count").get_json(),
            {"unread_count": 0},
        )
        response = self.learner_client.delete(f"/api/notifications/{second_id}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            self.learner_client.delete(f"/api/notifications/{second_id}").status_code,
            404,
        )

    def test_authentication_and_user_isolation(self):
        notification_id = self._add_notification(self.learner_id)
        anonymous = app.test_client()
        self.assertEqual(anonymous.get("/api/notifications").status_code, 401)
        self.assertEqual(
            self.other_client.get("/api/notifications").get_json()["pagination"]["total"],
            0,
        )
        self.assertEqual(
            self.other_client.post(
                f"/api/notifications/{notification_id}/read"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.other_client.delete(
                f"/api/notifications/{notification_id}"
            ).status_code,
            404,
        )
        with app.app_context():
            self.assertIsNotNone(db.session.get(Notification, notification_id))

    def test_request_message_session_and_rating_triggers(self):
        # New request, acceptance, and cancellation notifications.
        with app.app_context():
            pending_skill = Skill(name="Notification Java", category="Programming")
            db.session.add(pending_skill)
            db.session.flush()
            db.session.add_all(
                [
                    UserSkill(
                        user_id=self.learner_id,
                        skill_id=pending_skill.id,
                        skill_type="learn",
                    ),
                    UserSkill(
                        user_id=self.teacher_id,
                        skill_id=pending_skill.id,
                        skill_type="teach",
                    ),
                ]
            )
            db.session.commit()
            pending_skill_id = pending_skill.id

        response = self.learner_client.post(
            "/requests/create",
            data={
                "receiver_id": self.teacher_id,
                "skill_id": pending_skill_id,
                "message": "Could you teach me Java?",
            },
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            request_id = (
                SkillRequest.query.filter_by(
                    sender_id=self.learner_id,
                    skill_id=pending_skill_id,
                )
                .order_by(SkillRequest.id.desc())
                .first()
                .id
            )
            self.assertTrue(
                Notification.query.filter_by(
                    user_id=self.teacher_id,
                    type="skill_request",
                    related_entity_id=request_id,
                ).first()
            )
        self.teacher_client.post(f"/requests/{request_id}/accept")
        with app.app_context():
            self.assertTrue(
                Notification.query.filter_by(
                    user_id=self.learner_id,
                    type="request_accepted",
                    related_entity_id=request_id,
                ).first()
            )

        response = self.learner_client.post(
            "/requests/create",
            data={
                "receiver_id": self.teacher_id,
                "skill_id": pending_skill_id,
                "message": "Second request for rejection notification.",
            },
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            rejected_request_id = (
                SkillRequest.query.filter_by(
                    sender_id=self.learner_id,
                    skill_id=pending_skill_id,
                    status="pending",
                )
                .order_by(SkillRequest.id.desc())
                .first()
                .id
            )
        self.teacher_client.post(f"/requests/{rejected_request_id}/reject")
        with app.app_context():
            self.assertTrue(
                Notification.query.filter_by(
                    user_id=self.learner_id,
                    type="request_rejected",
                    related_entity_id=rejected_request_id,
                ).first()
            )

        response = self.learner_client.post(
            "/requests/create",
            data={
                "receiver_id": self.teacher_id,
                "skill_id": self.skill_id,
                "message": "Please swap Python skills.",
            },
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            cancel_request_id = (
                SkillRequest.query.filter_by(
                    sender_id=self.learner_id,
                    skill_id=self.skill_id,
                    status="pending",
                )
                .order_by(SkillRequest.id.desc())
                .first()
                .id
            )
        self.learner_client.post(f"/requests/{cancel_request_id}/cancel")
        with app.app_context():
            self.assertTrue(
                Notification.query.filter_by(
                    user_id=self.teacher_id,
                    type="request_cancelled",
                ).first()
            )

        # A new message emits a notification tied to the message record.
        response = self.learner_client.post(
            "/messages",
            data={"receiver_id": self.teacher_id, "message": "Hello"},
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertTrue(
                Notification.query.filter_by(
                    user_id=self.teacher_id,
                    type="message",
                ).first()
            )

        # Session lifecycle and rating notifications use their related IDs.
        future_date = (date.today() + timedelta(days=3)).isoformat()
        response = self.teacher_client.post(
            "/api/sessions",
            json={
                "skill_request_id": self.request_id,
                "teacher_id": self.teacher_id,
                "learner_id": self.learner_id,
                "title": "Notification session",
                "date": future_date,
                "start_time": "12:00",
                "end_time": "13:00",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        session_id = response.get_json()["session"]["id"]
        with app.app_context():
            self.assertTrue(
                Notification.query.filter_by(
                    user_id=self.learner_id,
                    type="session_created",
                    related_entity_id=session_id,
                ).first()
            )

        self.teacher_client.put(
            f"/api/sessions/{session_id}",
            json={"notes": "Revised"},
        )
        self.teacher_client.post(f"/api/sessions/{session_id}/start")
        self.teacher_client.post(
            f"/api/sessions/{session_id}/confirm-completion"
        )
        self.learner_client.post(
            f"/api/sessions/{session_id}/confirm-completion"
        )
        self.learner_client.post(
            "/api/ratings",
            json={"session_id": session_id, "rating": 5},
        )
        with app.app_context():
            emitted_types = {
                notification.type
                for notification in Notification.query.all()
            }
        self.assertTrue(
            {
                "session_updated",
                "session_started",
                "session_completion_confirmation",
                "session_completed",
                "rating",
            }.issubset(emitted_types)
        )

        cancel_session_response = self.teacher_client.post(
            "/api/sessions",
            json={
                "skill_request_id": self.request_id,
                "teacher_id": self.teacher_id,
                "learner_id": self.learner_id,
                "title": "To cancel",
                "date": (date.today() + timedelta(days=5)).isoformat(),
                "start_time": "14:00",
                "end_time": "15:00",
            },
        )
        cancel_session_id = cancel_session_response.get_json()["session"]["id"]
        self.teacher_client.post(
            f"/api/sessions/{cancel_session_id}/cancel"
        )
        with app.app_context():
            self.assertTrue(
                Notification.query.filter_by(
                    user_id=self.learner_id,
                    type="session_cancelled",
                    related_entity_id=cancel_session_id,
                ).first()
            )

    def test_email_service_is_disabled_during_tests(self):
        with app.app_context(), patch.dict(
            os.environ,
            {
                "SKILLSWAP_EMAIL_ENABLED": "true",
                "SKILLSWAP_SMTP_HOST": "smtp.example.com",
                "SKILLSWAP_EMAIL_FROM": "noreply@example.com",
            },
        ):
            self.assertFalse(
                send_notification_email(
                    "user@example.com",
                    "Test",
                    "Do not send",
                )
            )


if __name__ == "__main__":
    unittest.main()
