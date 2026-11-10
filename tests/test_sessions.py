import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ["SKILLSWAP_DATABASE_URL"] = "sqlite://"

from app import app
from models import Notification, Skill, SkillRequest, SkillSession, User, db


class SessionApiTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        with app.app_context():
            db.drop_all()
            db.create_all()
            self.teacher = User(
                name="Teacher",
                username="teacher",
                email="teacher@example.com",
                password_hash="unused",
                is_active=True,
            )
            self.learner = User(
                name="Learner",
                username="learner",
                email="learner@example.com",
                password_hash="unused",
                is_active=True,
            )
            self.other = User(
                name="Other",
                username="other",
                email="other@example.com",
                password_hash="unused",
                is_active=True,
            )
            self.skill = Skill(name="Python", category="Programming")
            db.session.add_all([self.teacher, self.learner, self.other, self.skill])
            db.session.flush()
            self.request = SkillRequest(
                sender_id=self.learner.id,
                receiver_id=self.teacher.id,
                skill_id=self.skill.id,
                status="accepted",
            )
            db.session.add(self.request)
            db.session.commit()
            self.teacher_id = self.teacher.id
            self.learner_id = self.learner.id
            self.other_id = self.other.id
            self.request_id = self.request.id
            self.skill_id = self.skill.id

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

    def _session_payload(self, **overrides):
        session_date = (datetime.now(timezone.utc).date() + timedelta(days=2)).isoformat()
        payload = {
            "skill_request_id": self.request_id,
            "teacher_id": self.teacher_id,
            "learner_id": self.learner_id,
            "title": "Python basics",
            "date": session_date,
            "start_time": "14:00",
            "end_time": "15:00",
            "notes": "Bring examples",
        }
        payload.update(overrides)
        return payload

    def _create_session(self, client=None, **overrides):
        response = (client or self.teacher_client).post(
            "/api/sessions",
            json=self._session_payload(**overrides),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["session"]["id"]

    def test_create_session_for_accepted_request(self):
        response = self.teacher_client.post(
            "/api/sessions",
            json=self._session_payload(),
        )
        self.assertEqual(response.status_code, 201)
        session = response.get_json()["session"]
        self.assertEqual(session["skill"]["id"], self.skill_id)
        self.assertEqual(session["teacher"]["id"], self.teacher_id)
        self.assertEqual(session["learner"]["id"], self.learner_id)
        self.assertEqual(session["status"], "SCHEDULED")
        self.assertTrue(session["created_at"])
        self.assertTrue(session["updated_at"])

    def test_only_accepted_participants_can_create_and_view(self):
        response = app.test_client().get("/api/sessions")
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.get_json())

        payload = self._session_payload()
        response = self.other_client.post("/api/sessions", json=payload)
        self.assertEqual(response.status_code, 403)

        session_id = self._create_session()
        response = self.other_client.get(f"/api/sessions/{session_id}")
        self.assertEqual(response.status_code, 403)
        response = self.other_client.post(f"/api/sessions/{session_id}/cancel")
        self.assertEqual(response.status_code, 403)

        with app.app_context():
            accepted_request = db.session.get(SkillRequest, self.request_id)
            accepted_request.status = "pending"
            db.session.commit()
        response = self.learner_client.post(
            "/api/sessions",
            json=self._session_payload(),
        )
        self.assertEqual(response.status_code, 403)

    def test_invalid_date_and_time_are_rejected(self):
        for values in (
            {"date": "not-a-date"},
            {"date": "20270318"},
            {"start_time": "25:61"},
            {"start_time": "1400"},
            {"start_time": "15:00", "end_time": "14:00"},
        ):
            response = self.teacher_client.post(
                "/api/sessions",
                json=self._session_payload(**values),
            )
            self.assertEqual(response.status_code, 400, response.get_json())

    def test_update_session(self):
        session_id = self._create_session()
        new_date = (datetime.now(timezone.utc).date() + timedelta(days=3)).isoformat()
        response = self.learner_client.put(
            f"/api/sessions/{session_id}",
            json={"date": new_date, "start_time": "16:00", "end_time": "17:00", "notes": "Updated"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["session"]["date"], new_date)
        self.assertEqual(response.get_json()["session"]["notes"], "Updated")

    def test_cancel_session_and_prevent_completion(self):
        session_id = self._create_session()
        response = self.teacher_client.post(f"/api/sessions/{session_id}/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["session"]["status"], "CANCELLED")
        response = self.learner_client.post(
            f"/api/sessions/{session_id}/confirm-completion"
        )
        self.assertEqual(response.status_code, 409)

    def test_start_session(self):
        session_id = self._create_session()
        response = self.learner_client.post(f"/api/sessions/{session_id}/start")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["session"]["status"], "IN_PROGRESS")

    def test_one_sided_then_both_sided_completion(self):
        session_id = self._create_session()
        self.teacher_client.post(f"/api/sessions/{session_id}/start")
        response = self.teacher_client.post(
            f"/api/sessions/{session_id}/confirm-completion"
        )
        session = response.get_json()["session"]
        self.assertEqual(session["status"], "IN_PROGRESS")
        in_progress = self.teacher_client.get(
            "/api/sessions?filter=in_progress"
        ).get_json()["sessions"]
        self.assertEqual([item["id"] for item in in_progress], [session_id])
        self.assertTrue(session["teacher_confirmed"])
        self.assertFalse(session["learner_confirmed"])

        response = self.learner_client.post(
            f"/api/sessions/{session_id}/confirm-completion"
        )
        session = response.get_json()["session"]
        self.assertEqual(session["status"], "COMPLETED")
        self.assertTrue(session["teacher_confirmed"])
        self.assertTrue(session["learner_confirmed"])
        completed = self.teacher_client.get(
            "/api/sessions?filter=completed"
        ).get_json()["sessions"]
        self.assertEqual([item["id"] for item in completed], [session_id])

    def test_completed_session_cannot_be_edited_or_cancelled(self):
        session_id = self._create_session()
        self.teacher_client.post(f"/api/sessions/{session_id}/start")
        self.teacher_client.post(f"/api/sessions/{session_id}/confirm-completion")
        self.learner_client.post(f"/api/sessions/{session_id}/confirm-completion")

        response = self.teacher_client.put(
            f"/api/sessions/{session_id}",
            json={"notes": "Too late"},
        )
        self.assertEqual(response.status_code, 409)
        response = self.teacher_client.post(f"/api/sessions/{session_id}/cancel")
        self.assertEqual(response.status_code, 409)

    def test_pagination_and_filters(self):
        base_date = datetime.now(timezone.utc).date()
        for day in (2, 3, 4):
            self._create_session(
                date=(base_date + timedelta(days=day)).isoformat(),
                start_time=f"{10 + day}:00",
                end_time=f"{11 + day}:00",
            )
        first_page = self.teacher_client.get(
            "/api/sessions?filter=upcoming&page=1&per_page=2"
        ).get_json()
        self.assertEqual(len(first_page["sessions"]), 2)
        self.assertEqual(first_page["pagination"]["total"], 3)
        self.assertEqual(first_page["pagination"]["pages"], 2)
        self.assertEqual(
            len(
                self.teacher_client.get(
                    "/api/sessions?filter=upcoming&page=2&per_page=2"
                ).get_json()["sessions"]
            ),
            1,
        )

        session_id = first_page["sessions"][0]["id"]
        self.teacher_client.post(f"/api/sessions/{session_id}/cancel")
        cancelled = self.teacher_client.get(
            "/api/sessions?filter=cancelled"
        ).get_json()["sessions"]
        self.assertEqual([item["id"] for item in cancelled], [session_id])

    def test_notifications_for_session_lifecycle(self):
        session_id = self._create_session()
        self.teacher_client.put(
            f"/api/sessions/{session_id}",
            json={"notes": "Updated notes"},
        )
        self.teacher_client.post(f"/api/sessions/{session_id}/start")
        self.teacher_client.post(
            f"/api/sessions/{session_id}/confirm-completion"
        )
        self.learner_client.post(
            f"/api/sessions/{session_id}/confirm-completion"
        )

        with app.app_context():
            notifications = Notification.query.filter(
                Notification.type.like("session_%")
            ).all()
            types = {notification.type for notification in notifications}
        self.assertTrue(
            {
                "session_created",
                "session_updated",
                "session_started",
                "session_completion_confirmation",
                "session_completed",
            }.issubset(types)
        )

        another_id = self._create_session(
            date=(datetime.now(timezone.utc).date() + timedelta(days=8)).isoformat()
        )
        self.learner_client.post(f"/api/sessions/{another_id}/cancel")
        with app.app_context():
            self.assertTrue(
                Notification.query.filter_by(type="session_cancelled").first()
            )

    def test_overlapping_participant_session_is_rejected(self):
        self._create_session()
        response = self.learner_client.post(
            "/api/sessions",
            json=self._session_payload(
                title="Overlap",
                start_time="14:30",
                end_time="15:30",
            ),
        )
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
