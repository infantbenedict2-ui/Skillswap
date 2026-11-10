from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, Index, UniqueConstraint

db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    location = db.Column(db.String(120))
    bio = db.Column(db.Text)
    profile_image = db.Column(db.String(255))
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    profile_visibility = db.Column(db.String(10), nullable=False, default="public")
    location_visibility = db.Column(db.Boolean, nullable=False, default=True)
    online_status_visibility = db.Column(db.Boolean, nullable=False, default=True)
    notify_requests = db.Column(db.Boolean, nullable=False, default=True)
    notify_messages = db.Column(db.Boolean, nullable=False, default=True)
    notify_sessions = db.Column(db.Boolean, nullable=False, default=True)
    notify_ratings = db.Column(db.Boolean, nullable=False, default=True)

    user_skills = db.relationship(
        "UserSkill",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    sent_requests = db.relationship(
        "SkillRequest",
        foreign_keys="SkillRequest.sender_id",
        back_populates="sender",
        cascade="all, delete-orphan",
    )
    received_requests = db.relationship(
        "SkillRequest",
        foreign_keys="SkillRequest.receiver_id",
        back_populates="receiver",
        cascade="all, delete-orphan",
    )
    sent_messages = db.relationship(
        "Message",
        foreign_keys="Message.sender_id",
        back_populates="sender",
        cascade="all, delete-orphan",
    )
    received_messages = db.relationship(
        "Message",
        foreign_keys="Message.receiver_id",
        back_populates="receiver",
        cascade="all, delete-orphan",
    )
    reviews_written = db.relationship(
        "Review",
        foreign_keys="Review.reviewer_id",
        back_populates="reviewer",
        cascade="all, delete-orphan",
    )
    reviews_received = db.relationship(
        "Review",
        foreign_keys="Review.reviewed_user_id",
        back_populates="reviewed_user",
        cascade="all, delete-orphan",
    )
    notifications = db.relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="Notification.created_at.desc()",
    )
    blocked_users = db.relationship(
        "BlockedUser",
        foreign_keys="BlockedUser.blocker_id",
        back_populates="blocker",
        cascade="all, delete-orphan",
    )
    blocked_by_users = db.relationship(
        "BlockedUser",
        foreign_keys="BlockedUser.blocked_id",
        back_populates="blocked",
        cascade="all, delete-orphan",
    )
    submitted_reports = db.relationship(
        "Report",
        foreign_keys="Report.reporter_id",
        back_populates="reporter",
        cascade="all, delete-orphan",
    )
    received_reports = db.relationship(
        "Report",
        foreign_keys="Report.reported_user_id",
        back_populates="reported_user",
        cascade="all, delete-orphan",
    )


class Skill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    category = db.Column(db.String(80))
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    user_skills = db.relationship(
        "UserSkill",
        back_populates="skill",
        cascade="all, delete-orphan",
    )
    requests = db.relationship(
        "SkillRequest",
        back_populates="skill",
        cascade="all, delete-orphan",
    )


class UserSkill(db.Model):
    __table_args__ = (
        CheckConstraint(
            "skill_type IN ('teach', 'learn')",
            name="check_user_skill_type",
        ),
        UniqueConstraint(
            "user_id",
            "skill_id",
            "skill_type",
            name="unique_user_skill_type",
        ),
        CheckConstraint(
            "experience_level IS NULL OR experience_level IN "
            "('beginner', 'intermediate', 'advanced')",
            name="check_user_skill_experience_level",
        ),
        CheckConstraint(
            "availability IS NULL OR availability IN "
            "('weekdays', 'weekends', 'evenings', 'flexible')",
            name="check_user_skill_availability",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    skill_id = db.Column(db.Integer, db.ForeignKey("skill.id", ondelete="CASCADE"), nullable=False)
    skill_type = db.Column(db.String(10), nullable=False)
    experience_level = db.Column(db.String(20))
    availability = db.Column(db.String(20))

    user = db.relationship("User", back_populates="user_skills")
    skill = db.relationship("Skill", back_populates="user_skills")


class SkillRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    skill_id = db.Column(db.Integer, db.ForeignKey("skill.id", ondelete="CASCADE"), nullable=False)
    message = db.Column(db.Text)
    status = db.Column(db.String(20), default="pending", nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    reviews = db.relationship(
        "Review",
        back_populates="skill_request",
        cascade="all, delete-orphan",
    )

    sender = db.relationship(
        "User",
        foreign_keys=[sender_id],
        back_populates="sent_requests",
    )
    receiver = db.relationship(
        "User",
        foreign_keys=[receiver_id],
        back_populates="received_requests",
    )
    skill = db.relationship("Skill", back_populates="requests")


class SkillSession(db.Model):
    __tablename__ = "skill_session"
    __table_args__ = (
        CheckConstraint(
            "status IN ('SCHEDULED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')",
            name="check_skill_session_status",
        ),
        Index(
            "ix_skill_session_learner_schedule",
            "learner_id",
            "date",
            "start_time",
        ),
        Index(
            "ix_skill_session_teacher_schedule",
            "teacher_id",
            "date",
            "start_time",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    skill_request_id = db.Column(
        db.Integer,
        db.ForeignKey("skill_request.id", ondelete="CASCADE"),
        nullable=False,
    )
    skill_id = db.Column(
        db.Integer,
        db.ForeignKey("skill.id", ondelete="CASCADE"),
        nullable=False,
    )
    teacher_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    learner_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = db.Column(db.String(200), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="SCHEDULED")
    teacher_confirmed = db.Column(db.Boolean, nullable=False, default=False)
    learner_confirmed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    skill_request = db.relationship("SkillRequest")
    skill = db.relationship("Skill")
    teacher = db.relationship("User", foreign_keys=[teacher_id])
    learner = db.relationship("User", foreign_keys=[learner_id])
    ratings = db.relationship(
        "Review",
        back_populates="session",
        cascade="all, delete-orphan",
    )


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    message = db.Column(db.Text, nullable=False)
    attachment_name = db.Column(db.String(255))
    attachment_path = db.Column(db.String(255))
    attachment_type = db.Column(db.String(100))
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    is_read = db.Column(db.Boolean, default=False, nullable=False)

    sender = db.relationship(
        "User",
        foreign_keys=[sender_id],
        back_populates="sent_messages",
    )
    receiver = db.relationship(
        "User",
        foreign_keys=[receiver_id],
        back_populates="received_messages",
    )


class Review(db.Model):
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="check_review_rating"),
        Index(
            "uq_review_request_reviewer",
            "skill_request_id",
            "reviewer_id",
            unique=True,
        ),
        Index(
            "uq_review_session_reviewer",
            "session_id",
            "reviewer_id",
            unique=True,
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    reviewed_user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    skill_request_id = db.Column(
        db.Integer,
        db.ForeignKey("skill_request.id", ondelete="CASCADE"),
    )
    session_id = db.Column(
        db.Integer,
        db.ForeignKey("skill_session.id", ondelete="CASCADE"),
    )
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    reviewer = db.relationship(
        "User",
        foreign_keys=[reviewer_id],
        back_populates="reviews_written",
    )
    reviewed_user = db.relationship(
        "User",
        foreign_keys=[reviewed_user_id],
        back_populates="reviews_received",
    )
    skill_request = db.relationship("SkillRequest", back_populates="reviews")
    session = db.relationship("SkillSession", back_populates="ratings")


class Notification(db.Model):
    __table_args__ = (
        Index(
            "ix_notification_user_read_created",
            "user_id",
            "is_read",
            "created_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(200), nullable=False, default="")
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), nullable=False)
    related_entity_id = db.Column(db.Integer)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user = db.relationship("User", back_populates="notifications")


class BlockedUser(db.Model):
    __tablename__ = "blocked_user"
    __table_args__ = (
        CheckConstraint("blocker_id != blocked_id", name="check_blocked_user_not_self"),
        UniqueConstraint("blocker_id", "blocked_id", name="uq_blocked_user_pair"),
        Index("ix_blocked_user_blocked_id", "blocked_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    blocked_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    blocker = db.relationship(
        "User",
        foreign_keys=[blocker_id],
        back_populates="blocked_users",
    )
    blocked = db.relationship(
        "User",
        foreign_keys=[blocked_id],
        back_populates="blocked_by_users",
    )


class Report(db.Model):
    __tablename__ = "user_report"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('inappropriate_behaviour', 'spam', 'fake_profile', 'harassment', 'other')",
            name="check_report_reason",
        ),
        CheckConstraint(
            "status IN ('submitted', 'under_review', 'resolved', 'rejected')",
            name="check_report_status",
        ),
        CheckConstraint("reporter_id != reported_user_id", name="check_report_not_self"),
        Index("ix_user_report_status_created", "status", "created_at"),
        Index("ix_user_report_reported_user", "reported_user_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    reported_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason = db.Column(db.String(40), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="submitted")
    moderation_notes = db.Column(db.Text)
    moderator_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="SET NULL"),
    )
    reviewed_at = db.Column(db.DateTime)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    reporter = db.relationship(
        "User",
        foreign_keys=[reporter_id],
        back_populates="submitted_reports",
    )
    reported_user = db.relationship(
        "User",
        foreign_keys=[reported_user_id],
        back_populates="received_reports",
    )
    moderator = db.relationship("User", foreign_keys=[moderator_id])


class ActivityLog(db.Model):
    __tablename__ = "activity_log"
    __table_args__ = (
        Index("ix_activity_log_created_at", "created_at"),
        Index("ix_activity_log_entity", "entity_type", "entity_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="SET NULL"),
    )
    action = db.Column(db.String(80), nullable=False)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.Integer)
    details = db.Column(db.Text)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    admin = db.relationship("User")


class PasswordResetToken(db.Model):
    __tablename__ = "password_reset_token"
    __table_args__ = (
        Index("ix_password_reset_user_expires", "user_id", "expires_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    user = db.relationship("User")