import json
import os
import subprocess
import sys
import unittest

from app import app, db
from models import User
from sqlalchemy import inspect


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class MySQLConfigurationTests(unittest.TestCase):
    def _import_with_database_url(
        self, database_url, environment_variable="SKILLSWAP_DATABASE_URL"
    ):
        environment = os.environ.copy()
        environment.pop("SKILLSWAP_DATABASE_URL", None)
        environment.pop("DATABASE_URL", None)
        environment.update(
            {
                "SKILLSWAP_ENV": "development",
                environment_variable: database_url,
                "SKILLSWAP_SKIP_DATABASE_INIT": "true",
            }
        )
        script = (
            "import json; import app; "
            "print(json.dumps({"
            "'uri': app.app.config['SQLALCHEMY_DATABASE_URI'], "
            "'engine_options': app.app.config['SQLALCHEMY_ENGINE_OPTIONS']"
            "}))"
        )
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_generic_mysql_url_uses_pymysql_utf8mb4_and_utc(self):
        result = self._import_with_database_url(
            "mysql://skillswap:placeholder@db.example.invalid/skillswap"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(settings["uri"].startswith("mysql+pymysql://"))
        self.assertTrue(settings["engine_options"]["pool_pre_ping"])
        self.assertGreater(settings["engine_options"]["pool_recycle"], 0)
        self.assertEqual(
            settings["engine_options"]["connect_args"],
            {
                "charset": "utf8mb4",
                "init_command": "SET time_zone = '+00:00'",
            },
        )

    def test_database_url_environment_variable_is_supported(self):
        result = self._import_with_database_url(
            "mysql://skillswap:placeholder@db.example.invalid/skillswap",
            environment_variable="DATABASE_URL",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(settings["uri"].startswith("mysql+pymysql://"))

    def test_unsupported_mysql_driver_fails_before_connecting(self):
        result = self._import_with_database_url(
            "mysql+mysqlconnector://skillswap:placeholder@db.example.invalid/skillswap"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("supported PyMySQL driver", result.stderr)

    def test_read_only_database_check_cli_is_registered(self):
        with app.app_context():
            result = app.test_cli_runner().invoke(args=["db-check"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Connection successful", result.output)

    def test_database_metadata_contains_foreign_keys_and_indexes(self):
        self.assertEqual(len(db.metadata.tables), 12)
        for table in db.metadata.tables.values():
            for constraint in table.foreign_key_constraints:
                self.assertTrue(constraint.elements)
                for foreign_key in constraint.elements:
                    self.assertIsNotNone(foreign_key.column)
            for index in table.indexes:
                self.assertTrue(index.columns)

        self.assertIn("user", db.metadata.tables)
        self.assertEqual(
            set(inspect(User).relationships.keys()),
            {
                "user_skills",
                "sent_requests",
                "received_requests",
                "sent_messages",
                "received_messages",
                "reviews_written",
                "reviews_received",
                "notifications",
                "blocked_users",
                "blocked_by_users",
                "submitted_reports",
                "received_reports",
            },
        )


if __name__ == "__main__":
    unittest.main()
