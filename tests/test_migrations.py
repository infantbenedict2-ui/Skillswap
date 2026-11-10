import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from flask import Flask
from flask_migrate import Migrate
from sqlalchemy import func, inspect, select, text

from models import Report, Review, Skill, SkillRequest, User, db


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


class MigrationConfigurationTests(unittest.TestCase):
    def _migration_app(self, database_path):
        test_app = Flask(__name__)
        test_app.config.update(
            TESTING=True,
            SECRET_KEY="migration-tests-only",
            SQLALCHEMY_DATABASE_URI=f"sqlite:///{Path(database_path).as_posix()}",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(test_app)
        Migrate(
            test_app,
            db,
            directory=str(MIGRATIONS_DIR),
            compare_type=True,
            render_as_batch=True,
        )
        return test_app

    def test_initial_migration_creates_schema_and_default_skills(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "fresh.sqlite"
            test_app = self._migration_app(database_path)
            try:
                result = test_app.test_cli_runner().invoke(args=["db", "upgrade"])
                self.assertEqual(result.exit_code, 0, result.output)

                with test_app.app_context():
                    inspector = inspect(db.engine)
                    self.assertTrue(
                        set(db.metadata.tables).issubset(inspector.get_table_names())
                    )
                    self.assertEqual(
                        db.session.scalar(select(func.count()).select_from(Skill)), 34
                    )

                check = test_app.test_cli_runner().invoke(args=["db", "check"])
                self.assertEqual(check.exit_code, 0, check.output)

                downgrade = test_app.test_cli_runner().invoke(
                    args=["db", "downgrade", "base"]
                )
                self.assertNotEqual(downgrade.exit_code, 0)
                with test_app.app_context():
                    self.assertIn("user", inspect(db.engine).get_table_names())
                    self.assertEqual(
                        db.session.scalar(select(func.count()).select_from(Skill)), 34
                    )
            finally:
                with test_app.app_context():
                    db.session.remove()
                    db.engine.dispose()

    def test_stamping_existing_schema_preserves_existing_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "existing.sqlite"
            test_app = self._migration_app(database_path)
            try:
                with test_app.app_context():
                    db.create_all()
                    db.session.add(
                        User(
                            name="Existing User",
                            username="migration_existing",
                            email="migration-existing@example.test",
                            password_hash="test-hash",
                        )
                    )
                    db.session.commit()

                stamp = test_app.test_cli_runner().invoke(args=["db", "stamp", "head"])
                self.assertEqual(stamp.exit_code, 0, stamp.output)
                check = test_app.test_cli_runner().invoke(args=["db", "check"])
                self.assertEqual(check.exit_code, 0, check.output)

                with test_app.app_context():
                    self.assertEqual(
                        db.session.scalar(
                            select(func.count()).select_from(User).where(
                                User.username == "migration_existing"
                            )
                        ),
                        1,
                    )
                    self.assertEqual(
                        db.session.scalar(
                            text("SELECT version_num FROM alembic_version")
                        ),
                        "6c4015073ed2",
                    )
            finally:
                with test_app.app_context():
                    db.session.remove()
                    db.engine.dispose()

    def test_baseline_adoption_and_forward_upgrade_preserve_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "baseline.sqlite"
            test_app = self._migration_app(database_path)
            try:
                baseline = test_app.test_cli_runner().invoke(
                    args=["db", "upgrade", "07abe9ce39eb"]
                )
                self.assertEqual(baseline.exit_code, 0, baseline.output)

                with test_app.app_context():
                    teacher = User(
                        name="Baseline Teacher",
                        username="migration_teacher",
                        email="migration-teacher@example.test",
                        password_hash="test-hash",
                    )
                    learner = User(
                        name="Baseline Learner",
                        username="migration_baseline",
                        email="migration-baseline@example.test",
                        password_hash="test-hash",
                    )
                    skill = Skill(name="Baseline Skill", category="Programming")
                    db.session.add_all([teacher, learner, skill])
                    db.session.flush()
                    request = SkillRequest(
                        sender_id=learner.id,
                        receiver_id=teacher.id,
                        skill_id=skill.id,
                        status="accepted",
                    )
                    db.session.add(request)
                    db.session.flush()
                    review = Review(
                        reviewer_id=learner.id,
                        reviewed_user_id=teacher.id,
                        skill_request_id=request.id,
                        rating=5,
                        comment="Migration data must remain",
                    )
                    report = Report(
                        reporter_id=learner.id,
                        reported_user_id=teacher.id,
                        reason="spam",
                        description="Migration data must remain",
                    )
                    db.session.add_all([review, report])
                    db.session.commit()
                    review_id = review.id
                    report_id = report.id
                    db.session.execute(text("DROP TABLE alembic_version"))
                    db.session.commit()

                stamp = test_app.test_cli_runner().invoke(
                    args=["db", "stamp", "07abe9ce39eb"]
                )
                self.assertEqual(stamp.exit_code, 0, stamp.output)
                upgrade = test_app.test_cli_runner().invoke(args=["db", "upgrade"])
                self.assertEqual(upgrade.exit_code, 0, upgrade.output)
                check = test_app.test_cli_runner().invoke(args=["db", "check"])
                self.assertEqual(check.exit_code, 0, check.output)

                with test_app.app_context():
                    user = db.session.scalar(
                        select(User).where(User.username == "migration_baseline")
                    )
                    self.assertIsNotNone(user)
                    self.assertIsNotNone(db.session.get(Review, review_id))
                    self.assertIsNotNone(db.session.get(Report, report_id))
                    foreign_keys = inspect(db.engine).get_foreign_keys("user_report")
                    moderator_fk = next(
                        fk
                        for fk in foreign_keys
                        if fk["constrained_columns"] == ["moderator_id"]
                    )
                    self.assertEqual(
                        moderator_fk["options"].get("ondelete"), "SET NULL"
                    )
            finally:
                with test_app.app_context():
                    db.session.remove()
                    db.engine.dispose()

    def test_production_requires_startup_database_initialization_to_be_skipped(self):
        environment = os.environ.copy()
        environment.update(
            {
                "SKILLSWAP_ENV": "production",
                "SKILLSWAP_DATABASE_URL": "mysql+pymysql://user:password@localhost/skillswap",
                "FLASK_SECRET_KEY": "test-secret-key-with-at-least-thirty-two-bytes",
                "SKILLSWAP_PUBLIC_URL": "https://skillswap.example",
                "SKILLSWAP_TRUSTED_HOSTS": "skillswap.example",
                "SKILLSWAP_COOKIE_SECURE": "true",
                "SKILLSWAP_ADMIN_EMAIL": "admin@example.test",
            }
        )
        environment.pop("SKILLSWAP_SKIP_DATABASE_INIT", None)
        result = subprocess.run(
            [sys.executable, "-c", "import app"],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "SKILLSWAP_SKIP_DATABASE_INIT=true",
            result.stderr + result.stdout,
        )


if __name__ == "__main__":
    unittest.main()
