import os
import unittest

os.environ["SKILLSWAP_DATABASE_URL"] = "sqlite://"

from app import app
from datetime import date, time

from models import Skill, SkillRequest, SkillSession, User, UserSkill, db
from werkzeug.security import generate_password_hash


class FrontendIntegrationTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        with app.app_context():
            db.drop_all()
            db.create_all()
            self.teacher = User(
                name="Frontend Teacher",
                username="frontend_teacher",
                email="frontend_teacher@example.com",
                password_hash="unused",
                location="North City",
            )
            self.learner = User(
                name="Frontend Learner",
                username="frontend_learner",
                email="frontend_learner@example.com",
                password_hash=generate_password_hash("learner-password"),
            )
            self.other = User(
                name="Other Learner",
                username="frontend_other",
                email="frontend_other@example.com",
                password_hash="unused",
            )
            self.skill = Skill(
                name="Frontend Design",
                category="Design",
                description="Accessible interface design",
            )
            db.session.add_all([self.teacher, self.learner, self.other, self.skill])
            db.session.flush()
            self.accepted_request = SkillRequest(
                sender_id=self.learner.id,
                receiver_id=self.teacher.id,
                skill_id=self.skill.id,
                status="accepted",
            )
            db.session.add_all(
                [
                    self.accepted_request,
                    UserSkill(
                        user_id=self.teacher.id,
                        skill_id=self.skill.id,
                        skill_type="teach",
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
            self.request_id = self.accepted_request.id

        self.client = self._client_for(self.learner_id)

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

    def test_public_home_is_database_backed_and_has_core_navigation(self):
        response = app.test_client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Frontend Design", response.data)
        self.assertIn(b"active skills", response.data)
        self.assertNotIn(b"Maya Chen", response.data)

    def test_favicon_resolves_to_existing_asset(self):
        response = app.test_client().get("/favicon.ico", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/svg+xml")
        response.close()

    def test_about_and_account_help_pages_render_truthfully(self):
        self.assertEqual(app.test_client().get("/about").status_code, 200)
        help_page = app.test_client().get("/forgot-password")
        self.assertEqual(help_page.status_code, 200)
        self.assertIn(b"Reset your password", help_page.data)
        self.assertIn(b'name="email"', help_page.data)

    def test_registration_login_and_session_cookie_security(self):
        registration = app.test_client()
        response = registration.post(
            "/register",
            data={
                "name": "New Member",
                "username": "new_frontend_member",
                "email": "new_frontend_member@example.com",
                "password": "valid-password",
                "confirm_password": "valid-password",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/dashboard", response.location)

        login = app.test_client()
        response = login.post(
            "/login",
            data={
                "identifier": "frontend_learner@example.com",
                "password": "learner-password",
            },
        )
        self.assertEqual(response.status_code, 302)
        cookie = response.headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertEqual(login.get("/dashboard").status_code, 200)

    def test_find_skills_filters_real_teacher_listings(self):
        response = app.test_client().get(
            "/find-skills?q=design&category=Design&location=North"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Frontend Teacher", response.data)
        self.assertIn(b"Frontend Design", response.data)
        self.assertNotIn(b"Frontend Learner</a>", response.data)
        self.assertEqual(
            app.test_client().get("/find-skills?min_rating=8").status_code,
            400,
        )

    def test_find_skills_respects_location_privacy(self):
        with app.app_context():
            teacher = db.session.get(User, self.teacher_id)
            teacher.location_visibility = False
            db.session.commit()
        response = app.test_client().get("/find-skills?location=North")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Frontend Teacher", response.data)

    def test_skill_detail_and_protected_screens(self):
        detail = app.test_client().get(f"/skills/{self.skill_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Frontend Teacher", detail.data)
        anonymous = app.test_client()
        for path in ("/sessions", "/privacy", "/blocked"):
            self.assertEqual(anonymous.get(path).status_code, 302)
        for path in ("/sessions", "/privacy", "/blocked"):
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_session_page_loads_only_accepted_participant_requests(self):
        response = self.client.get("/sessions")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Frontend Design", response.data)
        self.assertIn(b"/api/sessions", response.data)
        with app.app_context():
            self.assertEqual(SkillRequest.query.filter_by(status="accepted").count(), 1)

    def test_report_form_requires_auth_and_targets_real_user(self):
        self.assertEqual(
            app.test_client().get(f"/reports/new/{self.teacher_id}").status_code,
            302,
        )
        report_form = self.client.get(f"/reports/new/{self.teacher_id}")
        self.assertEqual(report_form.status_code, 200)
        self.assertIn(b"reported-user", report_form.data)
        self.assertEqual(
            self.client.get(f"/reports/new/{self.learner_id}").status_code,
            400,
        )

    def test_dashboard_and_profile_pages_link_to_integrated_features(self):
        dashboard = self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Upcoming sessions", dashboard.data)
        self.assertIn(b"Blocked users", dashboard.data)
        profile = app.test_client().get(f"/profile/{self.teacher_id}")
        self.assertEqual(profile.status_code, 200)

    def test_existing_request_message_and_rating_pages_render(self):
        self.assertEqual(self.client.get("/requests").status_code, 200)
        self.assertEqual(
            self.client.get(f"/messages?user_id={self.teacher_id}").status_code,
            200,
        )
        self.assertEqual(self.client.get("/reviews").status_code, 200)
        self.assertEqual(self.client.get("/notifications").status_code, 200)

    def test_completed_session_has_session_rating_form(self):
        with app.app_context():
            session = SkillSession(
                skill_request_id=self.request_id,
                skill_id=self.skill_id,
                teacher_id=self.teacher_id,
                learner_id=self.learner_id,
                title="Design review",
                date=date(2026, 1, 1),
                start_time=time(10, 0),
                end_time=time(11, 0),
                status="COMPLETED",
            )
            db.session.add(session)
            db.session.commit()
        response = self.client.get("/reviews")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"data-rating-form", response.data)
        self.assertIn(b"session rating", response.data.lower())


if __name__ == "__main__":
    unittest.main()
