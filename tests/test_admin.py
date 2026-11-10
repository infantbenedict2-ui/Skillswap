import os
import unittest
from datetime import date, time

os.environ["SKILLSWAP_DATABASE_URL"] = "sqlite://"

from app import app
from models import ActivityLog, Report, Skill, SkillRequest, SkillSession, User, UserSkill, db


class AdminDashboardTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        with app.app_context():
            db.drop_all()
            db.create_all()
            self.admin = User(
                name="Site Admin",
                username="dashboard_admin",
                email="dashboard_admin@example.com",
                password_hash="do-not-return-this",
                is_admin=True,
            )
            self.member = User(
                name="Regular Member",
                username="dashboard_member",
                email="dashboard_member@example.com",
                password_hash="member-hash",
            )
            self.other = User(
                name="Other Member",
                username="dashboard_other",
                email="dashboard_other@example.com",
                password_hash="other-hash",
            )
            self.skill = Skill(name="Dashboard Python", category="Programming")
            db.session.add_all([self.admin, self.member, self.other, self.skill])
            db.session.flush()
            self.swap_request = SkillRequest(
                sender_id=self.member.id,
                receiver_id=self.other.id,
                skill_id=self.skill.id,
                status="accepted",
            )
            db.session.add_all(
                [
                    self.swap_request,
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
            db.session.flush()
            self.session = SkillSession(
                skill_request_id=self.swap_request.id,
                skill_id=self.skill.id,
                teacher_id=self.other.id,
                learner_id=self.member.id,
                title="Python basics",
                date=date(2030, 1, 2),
                start_time=time(10, 0),
                end_time=time(11, 0),
                status="COMPLETED",
            )
            self.report = Report(
                reporter_id=self.member.id,
                reported_user_id=self.other.id,
                reason="spam",
                description="Repeated unsolicited messages",
            )
            db.session.add_all([self.session, self.report])
            db.session.commit()
            self.admin_id = self.admin.id
            self.member_id = self.member.id
            self.other_id = self.other.id
            self.skill_id = self.skill.id
            self.report_id = self.report.id
            self.session_id = self.session.id

        self.admin_client = self._client_for(self.admin_id)
        self.member_client = self._client_for(self.member_id)

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

    def test_admin_authentication_and_dashboard_statistics(self):
        self.assertEqual(app.test_client().get("/api/admin/dashboard").status_code, 401)
        self.assertEqual(app.test_client().get("/admin").status_code, 302)
        self.assertEqual(
            self.member_client.get("/api/admin/dashboard").status_code,
            403,
        )
        self.assertEqual(self.member_client.get("/admin").status_code, 403)
        response = self.admin_client.get("/api/admin/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["total_users"], 3)
        self.assertEqual(response.json["active_users"], 3)
        self.assertEqual(response.json["total_skills"], 1)
        self.assertEqual(response.json["total_requests"], 1)
        self.assertEqual(response.json["completed_sessions"], 1)
        self.assertEqual(response.json["unresolved_reports"], 1)

    def test_user_search_status_and_safe_serialization(self):
        response = self.admin_client.get("/api/admin/users?search=dashboard_member")
        self.assertEqual(response.status_code, 200)
        users = response.json["users"]
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["id"], self.member_id)
        self.assertNotIn("password_hash", users[0])
        self.assertEqual(
            self.admin_client.get("/api/admin/users?status=unknown").status_code,
            400,
        )
        self.assertEqual(
            self.admin_client.get("/api/admin/users?per_page=101").status_code,
            400,
        )

    def test_suspend_reactivate_and_activity_logging(self):
        response = self.admin_client.put(
            f"/api/admin/users/{self.member_id}/status",
            json={"is_active": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["user"]["is_active"])
        self.assertEqual(
            self.admin_client.put(
                f"/api/admin/users/{self.member_id}/status",
                json={"is_active": True},
            ).status_code,
            200,
        )
        with app.app_context():
            log = ActivityLog.query.filter_by(
                entity_type="user",
                entity_id=self.member_id,
                action="user_status_changed",
            ).first()
            self.assertIsNotNone(log)
            self.assertEqual(log.admin_id, self.admin_id)

    def test_skill_usage_filter_and_validation(self):
        self.assertEqual(
            self.admin_client.get("/api/admin/skills?active=unknown").status_code,
            400,
        )
        result = self.admin_client.get("/api/admin/skills?category=Programming")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["skills"][0]["id"], self.skill_id)
        self.assertEqual(
            self.member_client.get("/api/admin/skills").status_code,
            403,
        )

    def test_skill_management_and_audit_logging(self):
        created = self.admin_client.post(
            "/admin/skills",
            data={
                "name": "Admin Created Skill",
                "category": "Programming",
                "description": "Created by admin test",
            },
        )
        self.assertEqual(created.status_code, 302)
        with app.app_context():
            skill = Skill.query.filter_by(name="Admin Created Skill").one()
            skill_id = skill.id
        edited = self.admin_client.post(
            f"/admin/skills/{skill_id}/edit",
            data={
                "name": "Admin Updated Skill",
                "category": "Programming",
                "description": "Edited by admin test",
            },
        )
        self.assertEqual(edited.status_code, 302)
        with app.app_context():
            self.assertIsNotNone(Skill.query.filter_by(name="Admin Updated Skill").first())
            self.assertGreaterEqual(
                ActivityLog.query.filter_by(entity_type="skill").count(),
                2,
            )

    def test_deactivated_skills_are_hidden_and_cannot_be_requested(self):
        response = self.admin_client.post(f"/admin/skills/{self.skill_id}/toggle")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.admin_client.get("/api/admin/skills?active=false").json["skills"][0][
                "is_active"
            ],
            False,
        )
        self.member_client.post(
            "/requests/create",
            data={
                "receiver_id": self.other_id,
                "skill_id": self.skill_id,
                "message": "Please teach me",
            },
        )
        with app.app_context():
            self.assertEqual(SkillRequest.query.count(), 1)

    def test_report_moderation_and_admin_page(self):
        result = self.admin_client.put(
            f"/api/admin/reports/{self.report_id}/status",
            json={
                "status": "resolved",
                "moderation_notes": "Reviewed and actioned.",
            },
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["report"]["status"], "resolved")
        self.assertEqual(
            result.json["report"]["moderation_notes"],
            "Reviewed and actioned.",
        )
        self.assertEqual(
            self.member_client.put(
                f"/api/admin/reports/{self.report_id}/status",
                json={"status": "rejected"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.admin_client.put(
                f"/api/admin/reports/{self.report_id}/status",
                json={"status": "invalid"},
            ).status_code,
            400,
        )
        page = self.admin_client.get("/admin")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Analytics", page.data)
        self.assertIn(b"Recent admin actions", page.data)

    def test_analytics_return_real_database_data(self):
        response = self.admin_client.get("/api/admin/analytics")
        self.assertEqual(response.status_code, 200)
        analytics = response.json
        self.assertIn("user_registrations", analytics)
        self.assertIn("monthly_swap_requests", analytics)
        self.assertEqual(analytics["session_statuses"]["COMPLETED"], 1)
        self.assertEqual(analytics["popular_skills"][0]["name"], "Dashboard Python")
        self.assertEqual(analytics["rating_distribution"]["5"], 0)


if __name__ == "__main__":
    unittest.main()
