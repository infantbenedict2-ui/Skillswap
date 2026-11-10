import os
import unittest
from datetime import date, time

os.environ["SKILLSWAP_DATABASE_URL"] = "sqlite://"

from app import app
from models import Notification, Review, Skill, SkillRequest, SkillSession, User, db


class RatingApiTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        with app.app_context():
            db.drop_all()
            db.create_all()
            self.teacher = User(
                name="Teacher",
                username="rating_teacher",
                email="rating_teacher@example.com",
                password_hash="unused",
            )
            self.learner = User(
                name="Learner",
                username="rating_learner",
                email="rating_learner@example.com",
                password_hash="unused",
            )
            self.other = User(
                name="Other",
                username="rating_other",
                email="rating_other@example.com",
                password_hash="unused",
            )
            self.skill = Skill(name="Rating Python", category="Programming")
            db.session.add_all([self.teacher, self.learner, self.other, self.skill])
            db.session.flush()
            self.request = SkillRequest(
                sender_id=self.learner.id,
                receiver_id=self.teacher.id,
                skill_id=self.skill.id,
                status="accepted",
            )
            self.other_request = SkillRequest(
                sender_id=self.other.id,
                receiver_id=self.teacher.id,
                skill_id=self.skill.id,
                status="accepted",
            )
            db.session.add_all([self.request, self.other_request])
            db.session.commit()
            self.skill_id = self.skill.id
            self.teacher_id = self.teacher.id
            self.learner_id = self.learner.id
            self.other_id = self.other.id
            self.request_id = self.request.id
            self.other_request_id = self.other_request.id

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

    def _create_session(self, *, status="COMPLETED", use_other=False):
        with app.app_context():
            session = SkillSession(
                skill_request_id=self.other_request_id if use_other else self.request_id,
                skill_id=self.skill_id,
                teacher_id=self.teacher_id,
                learner_id=self.other_id if use_other else self.learner_id,
                title="Rating test session",
                date=date(2027, 3, 18),
                start_time=time(14, 0),
                end_time=time(15, 0),
                status=status,
                teacher_confirmed=status == "COMPLETED",
                learner_confirmed=status == "COMPLETED",
            )
            db.session.add(session)
            db.session.commit()
            return session.id

    def _submit_rating(self, client=None, *, session_id=None, rating=4, **values):
        payload = {"session_id": session_id or self._create_session(), "rating": rating}
        payload.update(values)
        return (client or self.learner_client).post("/api/ratings", json=payload)

    def test_successful_rating_submission(self):
        session_id = self._create_session()
        response = self._submit_rating(session_id=session_id, rating=4)
        self.assertEqual(response.status_code, 201, response.get_json())
        rating = response.get_json()["rating"]
        self.assertEqual(rating["session_id"], session_id)
        self.assertEqual(rating["reviewer"]["id"], self.learner_id)
        self.assertEqual(rating["reviewed_user"]["id"], self.teacher_id)
        self.assertEqual(rating["rating"], 4)
        reverse_response = self._submit_rating(
            self.teacher_client,
            session_id=session_id,
            rating=5,
        )
        self.assertEqual(reverse_response.status_code, 201)
        self.assertEqual(
            reverse_response.get_json()["rating"]["reviewed_user"]["id"],
            self.learner_id,
        )

    def test_five_star_rating(self):
        response = self._submit_rating(rating=5)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["rating"]["rating"], 5)

    def test_one_star_rating(self):
        response = self._submit_rating(rating=1)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["rating"]["rating"], 1)

    def test_invalid_rating_values(self):
        for value in (0, 6, -1, 2.5, True, "5"):
            response = self._submit_rating(rating=value)
            self.assertEqual(response.status_code, 400, response.get_json())
        response = self.learner_client.post(
            "/api/ratings",
            json={"session_id": 1.5, "rating": 5},
        )
        self.assertEqual(response.status_code, 400)

    def test_rating_before_session_completion(self):
        session_id = self._create_session(status="IN_PROGRESS")
        response = self._submit_rating(session_id=session_id)
        self.assertEqual(response.status_code, 409)

    def test_duplicate_rating_is_prevented(self):
        session_id = self._create_session()
        self.assertEqual(
            self._submit_rating(session_id=session_id).status_code,
            201,
        )
        response = self._submit_rating(session_id=session_id)
        self.assertEqual(response.status_code, 409)

    def test_unauthorized_rating_submission(self):
        session_id = self._create_session()
        response = self._submit_rating(
            self.other_client,
            session_id=session_id,
        )
        self.assertEqual(response.status_code, 403)
        response = app.test_client().post(
            "/api/ratings",
            json={"session_id": session_id, "rating": 4},
        )
        self.assertEqual(response.status_code, 401)

    def test_self_rating_is_not_client_selectable(self):
        session_id = self._create_session()
        response = self.learner_client.post(
            "/api/ratings",
            json={
                "session_id": session_id,
                "rating": 5,
                "reviewed_user_id": self.learner_id,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self.learner_client.get(
                f"/api/ratings/session/{session_id}"
            ).status_code,
            200,
        )

    def test_average_rating_calculation(self):
        first_session = self._create_session()
        second_session = self._create_session()
        self._submit_rating(session_id=first_session, rating=5)
        self._submit_rating(session_id=second_session, rating=1)
        response = self.learner_client.get(
            f"/api/ratings/user/{self.teacher_id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["average_rating"], 3.0)

    def test_rating_count_and_distribution(self):
        self._submit_rating(rating=5)
        self._submit_rating(
            self.other_client,
            session_id=self._create_session(use_other=True),
            rating=1,
        )
        response = self.teacher_client.get(
            f"/api/ratings/user/{self.teacher_id}"
        )
        data = response.get_json()
        self.assertEqual(data["rating_count"], 2)
        self.assertEqual(data["rating_distribution"]["1"], 1)
        self.assertEqual(data["rating_distribution"]["5"], 1)
        self.assertEqual(data["rating_distribution"]["3"], 0)
        profile = self.other_client.get(f"/profile/{self.teacher_id}")
        self.assertEqual(profile.status_code, 200)
        self.assertIn(b"2 reviews", profile.data)
        self.assertIn(b"3.0", profile.data)

    def test_rating_notification_and_read_endpoints(self):
        session_id = self._create_session()
        self._submit_rating(session_id=session_id, rating=5)
        with app.app_context():
            notification = Notification.query.filter_by(
                user_id=self.teacher_id,
                type="rating",
            ).first()
            self.assertIsNotNone(notification)
            self.assertEqual(Review.query.filter_by(session_id=session_id).count(), 1)

        session_ratings = self.teacher_client.get(
            f"/api/ratings/session/{session_id}"
        )
        self.assertEqual(session_ratings.status_code, 200)
        self.assertEqual(session_ratings.get_json()["rating_count"], 1)
        self.assertEqual(self.learner_client.get("/api/ratings/me").status_code, 200)
        self.assertEqual(
            self.other_client.get(
                f"/api/ratings/session/{session_id}"
            ).status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()
