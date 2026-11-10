import os
import unittest

os.environ["SKILLSWAP_DATABASE_URL"] = "sqlite://"

from app import app
from models import (
    BlockedUser,
    Message,
    Notification,
    Report,
    Skill,
    SkillRequest,
    User,
    UserSkill,
    db,
)


class PrivacyAndReportingTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        with app.app_context():
            db.drop_all()
            db.create_all()
            self.member = User(
                name="Member",
                username="privacy_member",
                email="privacy_member@example.com",
                password_hash="unused",
            )
            self.other = User(
                name="Other member",
                username="privacy_other",
                email="privacy_other@example.com",
                password_hash="unused",
            )
            self.admin = User(
                name="Administrator",
                username="privacy_admin",
                email="privacy_admin@example.com",
                password_hash="unused",
                is_admin=True,
            )
            self.skill = Skill(name="Privacy Python", category="Programming")
            db.session.add_all([self.member, self.other, self.admin, self.skill])
            db.session.flush()
            self.request = SkillRequest(
                sender_id=self.member.id,
                receiver_id=self.other.id,
                skill_id=self.skill.id,
                status="accepted",
            )
            db.session.add_all(
                [
                    self.request,
                    UserSkill(
                        user_id=self.member.id,
                        skill_id=self.skill.id,
                        skill_type="learn",
                    ),
                    UserSkill(
                        user_id=self.other.id,
                        skill_id=self.skill.id,
                        skill_type="teach",
                    ),
                ]
            )
            self.member.location = "Private City"
            db.session.commit()
            self.member_id = self.member.id
            self.other_id = self.other.id
            self.admin_id = self.admin.id
            self.skill_id = self.skill.id
            self.request_id = self.request.id

        self.member_client = self._client_for(self.member_id)
        self.other_client = self._client_for(self.other_id)
        self.admin_client = self._client_for(self.admin_id)

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

    def test_privacy_settings_update_and_validation(self):
        self.assertEqual(self.member_client.get("/api/privacy").status_code, 200)
        response = self.member_client.put(
            "/api/privacy",
            json={
                "profile_visibility": "private",
                "location_visibility": False,
                "online_status_visibility": False,
                "notification_preferences": {
                    "messages": False,
                    "ratings": False,
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        settings = response.get_json()
        self.assertEqual(settings["profile_visibility"], "private")
        self.assertFalse(settings["location_visibility"])
        self.assertFalse(settings["online_status_visibility"])
        self.assertFalse(settings["notification_preferences"]["messages"])
        self.assertFalse(settings["notification_preferences"]["ratings"])
        self.assertTrue(settings["notification_preferences"]["requests"])

        for invalid_body in (
            {"profile_visibility": ["public"]},
            {"location_visibility": "false"},
            {"notification_preferences": {"messages": "off"}},
            {"unsupported": True},
            [],
        ):
            response = self.member_client.put("/api/privacy", json=invalid_body)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(app.test_client().get("/api/privacy").status_code, 401)

    def test_private_profile_and_location_are_protected(self):
        self.member_client.put(
            "/api/privacy",
            json={
                "profile_visibility": "private",
                "location_visibility": False,
            },
        )
        self.assertEqual(
            self.other_client.get(f"/profile/{self.member_id}").status_code,
            404,
        )
        self.assertEqual(
            self.member_client.get(f"/profile/{self.member_id}").status_code,
            200,
        )
        self.member_client.put(
            "/api/privacy",
            json={"profile_visibility": "public"},
        )
        public_profile = self.other_client.get(f"/profile/{self.member_id}")
        self.assertEqual(public_profile.status_code, 200)
        self.assertNotIn(b"Private City", public_profile.data)

    def test_block_list_and_unblock(self):
        response = self.member_client.post(f"/api/users/{self.other_id}/block")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            self.member_client.post(f"/api/users/{self.other_id}/block").status_code,
            200,
        )
        blocked = self.member_client.get("/api/users/me/blocked")
        self.assertEqual(blocked.status_code, 200)
        self.assertEqual(
            [user["id"] for user in blocked.get_json()["blocked_users"]],
            [self.other_id],
        )
        self.assertEqual(
            self.member_client.post(f"/api/users/{self.member_id}/block").status_code,
            400,
        )
        self.assertEqual(
            self.other_client.delete(f"/api/users/{self.member_id}/block").status_code,
            404,
        )
        self.assertEqual(
            self.member_client.delete(f"/api/users/{self.other_id}/block").status_code,
            204,
        )
        with app.app_context():
            self.assertEqual(BlockedUser.query.count(), 0)

    def test_blocked_users_hidden_from_match_results(self):
        self.member_client.post(f"/api/users/{self.other_id}/block")
        response = self.member_client.get("/matches")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"privacy_other", response.data)

    def test_private_profiles_are_hidden_from_matching(self):
        self.other_client.put(
            "/api/privacy",
            json={"profile_visibility": "private"},
        )
        response = self.member_client.get("/matches")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"privacy_other", response.data)

    def test_blocked_users_cannot_send_swap_requests(self):
        self.other_client.post(f"/api/users/{self.member_id}/block")
        response = self.member_client.post(
            "/requests/create",
            data={
                "receiver_id": self.other_id,
                "skill_id": self.skill_id,
                "message": "I want to learn this.",
            },
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertEqual(
                SkillRequest.query.filter_by(
                    sender_id=self.member_id,
                    receiver_id=self.other_id,
                    status="pending",
                ).count(),
                0,
            )

    def test_blocked_users_cannot_message_or_see_conversation(self):
        self.member_client.post(f"/api/users/{self.other_id}/block")
        response = self.member_client.post(
            "/messages",
            data={"receiver_id": self.other_id, "message": "Hello"},
        )
        self.assertEqual(response.status_code, 302)
        response = self.member_client.get(
            f"/messages?user_id={self.other_id}"
        )
        self.assertEqual(response.status_code, 404)
        with app.app_context():
            self.assertEqual(Message.query.count(), 0)

    def test_report_submission_admin_moderation_and_duplicate_protection(self):
        response = self.member_client.post(
            "/api/reports",
            json={
                "reported_user_id": self.other_id,
                "reason": "harassment",
                "description": "Repeated unwanted messages.",
            },
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        report_id = response.get_json()["report"]["id"]
        self.assertEqual(
            self.member_client.post(
                "/api/reports",
                json={
                    "reported_user_id": self.other_id,
                    "reason": "spam",
                    "description": "Another report.",
                },
            ).status_code,
            409,
        )
        self.assertEqual(
            self.member_client.get("/api/reports").status_code,
            403,
        )
        self.assertEqual(
            self.other_client.get(f"/api/reports/{report_id}").status_code,
            403,
        )
        listed = self.admin_client.get("/api/reports?status=submitted")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.get_json()["pagination"]["total"], 1)
        detail = self.admin_client.get(f"/api/reports/{report_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.get_json()["report"]["reason"], "harassment")
        updated = self.admin_client.put(
            f"/api/reports/{report_id}/status",
            json={"status": "under_review"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["report"]["status"], "under_review")
        self.assertEqual(
            self.admin_client.put(
                f"/api/reports/{report_id}/status",
                json={"status": "resolved"},
            ).status_code,
            200,
        )

    def test_report_validation_and_authentication(self):
        for payload in (
            {
                "reported_user_id": self.other_id,
                "reason": "invalid",
                "description": "description",
            },
            {
                "reported_user_id": self.other_id,
                "reason": "spam",
                "description": " ",
            },
            {
                "reported_user_id": self.member_id,
                "reason": "spam",
                "description": "Self report",
            },
            {
                "reported_user_id": 1.5,
                "reason": "spam",
                "description": "Bad id",
            },
        ):
            response = self.member_client.post("/api/reports", json=payload)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(
            app.test_client().post(
                "/api/reports",
                json={
                    "reported_user_id": self.other_id,
                    "reason": "spam",
                    "description": "Report",
                },
            ).status_code,
            401,
        )
        self.assertEqual(
            self.member_client.post("/api/reports", json=[]).status_code,
            400,
        )

    def test_notification_preferences_are_enforced(self):
        self.other_client.put(
            "/api/privacy",
            json={"notification_preferences": {"requests": False}},
        )
        with app.app_context():
            pending_skill = Skill(
                name="No request notification",
                category="Programming",
            )
            db.session.add(pending_skill)
            db.session.flush()
            db.session.add_all(
                [
                    UserSkill(
                        user_id=self.member_id,
                        skill_id=pending_skill.id,
                        skill_type="learn",
                    ),
                    UserSkill(
                        user_id=self.other_id,
                        skill_id=pending_skill.id,
                        skill_type="teach",
                    ),
                ]
            )
            db.session.commit()
            pending_skill_id = pending_skill.id

        self.member_client.post(
            "/requests/create",
            data={
                "receiver_id": self.other_id,
                "skill_id": pending_skill_id,
                "message": "Please teach me.",
            },
        )
        with app.app_context():
            self.assertIsNone(
                Notification.query.filter_by(
                    user_id=self.other_id,
                    type="skill_request",
                ).first()
            )


if __name__ == "__main__":
    unittest.main()
