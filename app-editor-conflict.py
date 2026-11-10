import os
import re
from functools import wraps
from urllib.parse import urlsplit

from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from sqlalchemy import and_, event, func, inspect, or_, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from models import Message, Notification, Review, Skill, SkillRequest, User, UserSkill, db

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///skillswap.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
os.makedirs(app.instance_path, exist_ok=True)
_secret_path = os.path.join(app.instance_path, "secret_key")
if os.environ.get("FLASK_SECRET_KEY"):
    app.config["SECRET_KEY"] = os.environ["FLASK_SECRET_KEY"]
elif os.path.exists(_secret_path):
    with open(_secret_path, "rb") as secret_file:
        app.config["SECRET_KEY"] = secret_file.read()
else:
    _generated_secret = os.urandom(32)
    with open(_secret_path, "wb") as secret_file:
        secret_file.write(_generated_secret)
    app.config["SECRET_KEY"] = _generated_secret
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "info"

@login_manager.user_loader
def load_user(user_id):
    try:
        user = db.session.get(User, int(user_id))
        return user if user is not None and user.is_active else None
    except (TypeError, ValueError):
        return None


def admin_required(view_function):
    @wraps(view_function)
    @login_required
    def wrapped_view(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view_function(*args, **kwargs)

    return wrapped_view

DEFAULT_SKILLS = [
    "Python",
    "Java",
    "C",
    "C++",
    "JavaScript",
    "HTML",
    "CSS",
    "SQL",
    "Web Development",
    "App Development",
    "UI/UX Design",
    "Graphic Design",
    "Video Editing",
    "Photography",
    "Public Speaking",
    "Communication",
    "English",
    "Mathematics",
    "Data Structures",
    "Machine Learning",
    "Artificial Intelligence",
    "Git",
    "GitHub",
    "Digital Marketing",
    "Excel",
    "PowerPoint",
    "Music",
    "Drawing",
    "Cooking",
    "Fitness",
    "Cybersecurity",
    "Cloud Computing",
    "Data Science",
    "Content Writing",
]

SKILL_CATEGORIES = {
    "Programming": ["Python", "Java", "C", "C++", "JavaScript", "Data Structures"],
    "Web Development": ["HTML", "CSS", "SQL", "Web Development", "App Development"],
    "Design": ["UI/UX Design", "Graphic Design"],
    "Business": ["Digital Marketing", "Excel", "PowerPoint"],
    "Communication": ["Public Speaking", "Communication", "English"],
    "Academic": ["Mathematics", "Machine Learning", "Artificial Intelligence", "Data Science"],
    "Creative": ["Video Editing", "Photography", "Music", "Drawing", "Content Writing"],
    "Technology": ["Git", "GitHub", "Cybersecurity", "Cloud Computing"],
    "Lifestyle": ["Cooking", "Fitness"],
}
SKILL_CATEGORY_BY_NAME = {
    skill_name: category
    for category, skill_names in SKILL_CATEGORIES.items()
    for skill_name in skill_names
}


def enable_sqlite_foreign_keys(connection, _connection_record):
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def initialize_database():
    os.makedirs(app.instance_path, exist_ok=True)

    with app.app_context():
        if not event.contains(db.engine, "connect", enable_sqlite_foreign_keys):
            event.listen(db.engine, "connect", enable_sqlite_foreign_keys)
        db.create_all()

        user_columns = {
            column["name"] for column in inspect(db.engine).get_columns("user")
        }
        if "is_active" not in user_columns:
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE user ADD COLUMN is_active "
                        "BOOLEAN NOT NULL DEFAULT 1"
                    )
                )

        review_columns = {
            column["name"] for column in inspect(db.engine).get_columns("review")
        }
        if "skill_request_id" not in review_columns:
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE review ADD COLUMN skill_request_id "
                        "INTEGER REFERENCES skill_request(id) ON DELETE CASCADE"
                    )
                )
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_review_request_reviewer "
                    "ON review (skill_request_id, reviewer_id)"
                )
            )

        existing_skills = {skill.name: skill for skill in Skill.query.all()}
        new_skills = [
            Skill(name=name, category=SKILL_CATEGORY_BY_NAME[name])
            for name in DEFAULT_SKILLS
            if name not in existing_skills
        ]
        db.session.add_all(new_skills)
        for skill in existing_skills.values():
            if not skill.category:
                skill.category = SKILL_CATEGORY_BY_NAME.get(skill.name)

        admin_email = (os.environ.get("SKILLSWAP_ADMIN_EMAIL") or "").strip().lower()
        if admin_email:
            designated_admin = User.query.filter(func.lower(User.email) == admin_email).first()
            if designated_admin is not None and not designated_admin.is_admin:
                designated_admin.is_admin = True
        elif User.query.filter_by(is_admin=True).count() == 0:
            first_user = User.query.order_by(User.id.asc()).first()
            if first_user is not None:
                first_user.is_admin = True
        db.session.commit()


initialize_database()


def _add_notification(user_id, message, notification_type):
    db.session.add(
        Notification(
            user_id=user_id,
            message=message,
            type=notification_type,
        )
    )


def _safe_next_url():
    target = request.values.get("next", "").strip()
    if not target:
        return None
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/"):
        return None
    return target


def _redirect_after_login():
    next_url = _safe_next_url()
    return redirect(next_url or url_for("dashboard"))


def _active_users():
    return User.query.filter_by(is_active=True)


def notification_href(notification):
    targets = {
        "message": url_for("messages"),
        "review": url_for("reviews"),
        "skill_request": url_for("view_requests"),
        "request_accepted": url_for("view_requests"),
        "request_rejected": url_for("view_requests"),
        "request_completed": url_for("view_requests"),
    }
    return targets.get(notification.type, url_for("view_notifications"))


@app.context_processor
def inject_template_helpers():
    return {"notification_href": notification_href}


@app.errorhandler(400)
def handle_bad_request(error):
    app.logger.info("Bad request for %s %s: %s", request.method, request.path, error)
    return render_template("400.html"), 400


@app.errorhandler(403)
def handle_forbidden(error):
    app.logger.info("Forbidden request for %s %s", request.method, request.path)
    return render_template("403.html"), 403


@app.errorhandler(404)
def handle_not_found(error):
    app.logger.info("Page or record not found: %s %s", request.method, request.path)
    return render_template("404.html"), 404


@app.errorhandler(SQLAlchemyError)
def handle_database_error(error):
    db.session.rollback()
    app.logger.error(
        "Database error while handling %s %s",
        request.method,
        request.path,
        exc_info=(type(error), error, error.__traceback__),
    )
    return render_template("500.html"), 500


@app.errorhandler(500)
def handle_internal_error(error):
    db.session.rollback()
    original_error = getattr(error, "original_exception", None) or error
    app.logger.error(
        "Unexpected server error while handling %s %s",
        request.method,
        request.path,
        exc_info=(type(original_error), original_error, original_error.__traceback__),
    )
    return render_template("500.html"), 500


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        location = request.form.get("location", "").strip()
        bio = request.form.get("bio", "").strip()

        if not all((name, username, email, password, confirm_password)):
            flash("Please complete all required fields.", "error")
            return render_template("register.html")

        if len(name) > 120 or len(username) > 80 or len(email) > 255 or len(location) > 120:
            flash("One or more fields are longer than allowed.", "error")
            return render_template("register.html")

        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Please enter a valid email address.", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Your passwords do not match.", "error")
            return render_template("register.html")

        if len(password) < 8:
            flash("Please choose a password with at least 8 characters.", "error")
            return render_template("register.html")

        if User.query.filter(func.lower(User.username) == username).first():
            flash("That username is already taken. Please choose another.", "error")
            return render_template("register.html")

        if User.query.filter(func.lower(User.email) == email).first():
            flash("That email is already registered. Please use another.", "error")
            return render_template("register.html")

        user = User(
            name=name,
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            location=location or None,
            bio=bio or None,
            is_admin=User.query.filter_by(is_admin=True).count() == 0,
        )
        db.session.add(user)

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("That username or email is already registered.", "error")
            return render_template("register.html")

        login_user(user)
        flash("Your account has been created. Welcome to SkillSwap.", "success")
        return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter(
            or_(
                func.lower(User.username) == identifier,
                func.lower(User.email) == identifier,
            )
        ).first()

        if user and check_password_hash(user.password_hash, password):
            if login_user(user):
                return _redirect_after_login()
            flash("This account is disabled. Contact an administrator.", "error")
        elif user and not user.is_active:
            flash("This account is disabled. Contact an administrator.", "error")
        else:
            flash("Invalid username/email or password.", "error")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    user_id = current_user.id
    user_skills = (
        UserSkill.query.filter_by(user_id=user_id)
        .join(Skill)
        .order_by(Skill.name.asc())
        .all()
    )
    skills_to_teach = sum(user_skill.skill_type == "teach" for user_skill in user_skills)
    skills_to_learn = sum(user_skill.skill_type == "learn" for user_skill in user_skills)

    related_requests = or_(
        SkillRequest.sender_id == user_id,
        SkillRequest.receiver_id == user_id,
    )
    pending_requests = SkillRequest.query.filter(
        related_requests,
        func.lower(SkillRequest.status) == "pending",
    ).count()
    accepted_pairs = SkillRequest.query.with_entities(
        SkillRequest.sender_id,
        SkillRequest.receiver_id,
    ).filter(
        related_requests,
        func.lower(SkillRequest.status) == "accepted",
    ).all()
    accepted_connections = {
        receiver_id if sender_id == user_id else sender_id
        for sender_id, receiver_id in accepted_pairs
    }
    accepted_connections.discard(user_id)

    review_query = Review.query.filter_by(reviewed_user_id=user_id)
    review_count = review_query.count()
    average_rating = db.session.query(func.avg(Review.rating)).filter(
        Review.reviewed_user_id == user_id
    ).scalar()
    average_rating = round(float(average_rating), 1) if average_rating is not None else None

    learning_skill_ids = {
        user_skill.skill_id
        for user_skill in user_skills
        if user_skill.skill_type == "learn"
    }
    teaching_skill_ids = {
        user_skill.skill_id
        for user_skill in user_skills
        if user_skill.skill_type == "teach"
    }
    match_conditions = []
    if learning_skill_ids:
        match_conditions.append(
            and_(
                UserSkill.skill_type == "teach",
                UserSkill.skill_id.in_(learning_skill_ids),
            )
        )
    if teaching_skill_ids:
        match_conditions.append(
            and_(
                UserSkill.skill_type == "learn",
                UserSkill.skill_id.in_(teaching_skill_ids),
            )
        )

    match_groups = {}
    if match_conditions:
        match_rows = (
            db.session.query(User, Skill.name)
            .join(UserSkill, UserSkill.user_id == User.id)
            .join(Skill, Skill.id == UserSkill.skill_id)
            .filter(User.id != user_id, User.is_active.is_(True), or_(*match_conditions))
            .all()
        )
        for matched_user, skill_name in match_rows:
            match = match_groups.setdefault(
                matched_user.id,
                {"user": matched_user, "skills": set()},
            )
            match["skills"].add(skill_name)

    recommended_matches = sorted(
        (
            {"user": match["user"], "skills": sorted(match["skills"])}
            for match in match_groups.values()
        ),
        key=lambda match: (-len(match["skills"]), match["user"].name.lower()),
    )[:4]

    recent_requests = (
        SkillRequest.query.filter(related_requests)
        .order_by(SkillRequest.created_at.desc())
        .limit(4)
        .all()
    )
    recent_messages = (
        Message.query.filter(
            or_(Message.sender_id == user_id, Message.receiver_id == user_id)
        )
        .order_by(Message.created_at.desc())
        .limit(4)
        .all()
    )
    recent_notifications = (
        Notification.query.filter_by(user_id=user_id)
        .order_by(Notification.created_at.desc())
        .limit(4)
        .all()
    )
    unread_notifications = Notification.query.filter_by(
        user_id=user_id,
        is_read=False,
    ).count()
    recent_reviews = review_query.order_by(Review.created_at.desc()).limit(4).all()

    return render_template(
        "dashboard.html",
        user_skills=user_skills,
        skills_to_teach=skills_to_teach,
        skills_to_learn=skills_to_learn,
        pending_requests=pending_requests,
        accepted_connections=len(accepted_connections),
        average_rating=average_rating,
        review_count=review_count,
        recommended_matches=recommended_matches,
        recent_requests=recent_requests,
        recent_messages=recent_messages,
        recent_notifications=recent_notifications,
        unread_notifications=unread_notifications,
        recent_reviews=recent_reviews,
    )


@app.route("/admin")
@admin_required
def admin_panel():
    return render_template(
        "admin.html",
        total_users=User.query.count(),
        total_skills=Skill.query.count(),
        total_requests=SkillRequest.query.count(),
        total_messages=Message.query.count(),
        total_reviews=Review.query.count(),
        users=User.query.order_by(User.created_at.desc()).all(),
        skills=Skill.query.order_by(Skill.category, Skill.name).all(),
        skill_requests=SkillRequest.query.order_by(
            SkillRequest.created_at.desc()
        ).all(),
        skill_categories=sorted(SKILL_CATEGORIES),
        active_admin_count=User.query.filter_by(is_admin=True, is_active=True).count(),
    )


@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def admin_toggle_user(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash("You cannot disable your own administrator account.", "error")
        return redirect(url_for("admin_panel"))
    if (
        user.is_admin
        and user.is_active
        and User.query.filter_by(is_admin=True, is_active=True).count() <= 1
    ):
        flash("The last active administrator cannot be disabled.", "error")
        return redirect(url_for("admin_panel"))

    user.is_active = not user.is_active
    db.session.commit()
    state = "enabled" if user.is_active else "disabled"
    flash(f"{user.username} has been {state}.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash("You cannot delete your own administrator account.", "error")
        return redirect(url_for("admin_panel"))
    if (
        user.is_admin
        and user.is_active
        and User.query.filter_by(is_admin=True, is_active=True).count() <= 1
    ):
        flash("The last active administrator cannot be deleted.", "error")
        return redirect(url_for("admin_panel"))

    username = user.username
    db.session.delete(user)
    db.session.commit()
    flash(f"{username} and their account data have been deleted.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/users/<int:user_id>/role", methods=["POST"])
@admin_required
def admin_toggle_role(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash("You cannot change your own administrator role.", "error")
        return redirect(url_for("admin_panel"))
    if (
        user.is_admin
        and user.is_active
        and User.query.filter_by(is_admin=True, is_active=True).count() <= 1
    ):
        flash("The last active administrator cannot be demoted.", "error")
        return redirect(url_for("admin_panel"))

    user.is_admin = not user.is_admin
    db.session.commit()
    state = "an administrator" if user.is_admin else "a member"
    flash(f"{user.username} is now {state}.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/skills", methods=["POST"])
@admin_required
def admin_add_skill():
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    description = request.form.get("description", "").strip()

    if not name or len(name) > 120 or len(description) > 2000:
        flash("Enter a skill name and keep fields within their length limits.", "error")
        return redirect(url_for("admin_panel") + "#skills")
    if category not in SKILL_CATEGORIES:
        flash("Choose a category from the list.", "error")
        return redirect(url_for("admin_panel") + "#skills")
    if Skill.query.filter(func.lower(Skill.name) == name.lower()).first():
        flash("A skill with that name already exists.", "error")
        return redirect(url_for("admin_panel") + "#skills")

    db.session.add(Skill(name=name, category=category, description=description or None))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("A skill with that name already exists.", "error")
        return redirect(url_for("admin_panel") + "#skills")

    flash(f"{name} has been added to the skill catalog.", "success")
    return redirect(url_for("admin_panel") + "#skills")


@app.route("/admin/skills/<int:skill_id>/edit", methods=["POST"])
@admin_required
def admin_edit_skill(skill_id):
    skill = db.get_or_404(Skill, skill_id)
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    description = request.form.get("description", "").strip()

    if not name or len(name) > 120 or len(description) > 2000:
        flash("Enter a skill name and keep fields within their length limits.", "error")
        return redirect(url_for("admin_panel") + "#skills")
    if category not in SKILL_CATEGORIES:
        flash("Choose a category from the list.", "error")
        return redirect(url_for("admin_panel") + "#skills")
    duplicate = Skill.query.filter(
        func.lower(Skill.name) == name.lower(),
        Skill.id != skill.id,
    ).first()
    if duplicate:
        flash("A skill with that name already exists.", "error")
        return redirect(url_for("admin_panel") + "#skills")

    skill.name = name
    skill.category = category
    skill.description = description or None
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("A skill with that name already exists.", "error")
        return redirect(url_for("admin_panel") + "#skills")

    flash(f"{name} has been updated.", "success")
    return redirect(url_for("admin_panel") + "#skills")


@app.route("/admin/skills/<int:skill_id>/delete", methods=["POST"])
@admin_required
def admin_delete_skill(skill_id):
    skill = db.get_or_404(Skill, skill_id)
    skill_name = skill.name
    db.session.delete(skill)
    db.session.commit()
    flash(f"{skill_name} and its related skill records have been deleted.", "success")
    return redirect(url_for("admin_panel") + "#skills")


@app.route("/skills", methods=["GET", "POST"])
@login_required
def manage_skills():
    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "add":
            try:
                skill_id = int(request.form.get("skill_id", ""))
            except ValueError:
                flash("Choose a skill from the list.", "error")
                return redirect(url_for("manage_skills"))

            skill_type = request.form.get("skill_type", "")
            if skill_type not in {"teach", "learn"}:
                flash("Choose whether you can teach or want to learn this skill.", "error")
                return redirect(url_for("manage_skills"))

            skill = db.session.get(Skill, skill_id)
            if skill is None:
                flash("That skill could not be found. Please choose another.", "error")
                return redirect(url_for("manage_skills"))

            existing_link = UserSkill.query.filter_by(
                user_id=current_user.id,
                skill_id=skill.id,
                skill_type=skill_type,
            ).first()
            if existing_link:
                flash(f"{skill.name} is already in your {skill_type} list.", "info")
                return redirect(url_for("manage_skills"))

            db.session.add(
                UserSkill(
                    user_id=current_user.id,
                    skill_id=skill.id,
                    skill_type=skill_type,
                )
            )
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash(f"{skill.name} is already in your {skill_type} list.", "info")
                return redirect(url_for("manage_skills"))

            flash(f"{skill.name} added to your {skill_type} list.", "success")

        elif action == "remove":
            try:
                user_skill_id = int(request.form.get("user_skill_id", ""))
            except ValueError:
                flash("That skill entry could not be found.", "error")
                return redirect(url_for("manage_skills"))

            user_skill = UserSkill.query.filter_by(
                id=user_skill_id,
                user_id=current_user.id,
            ).first()
            if user_skill is None:
                flash("That skill entry could not be found.", "error")
                return redirect(url_for("manage_skills"))

            skill_name = user_skill.skill.name
            skill_type = user_skill.skill_type
            db.session.delete(user_skill)
            db.session.commit()
            flash(f"{skill_name} removed from your {skill_type} list.", "success")

        else:
            flash("Choose a valid skill action.", "error")

        return redirect(url_for("manage_skills"))

    catalog = Skill.query.order_by(Skill.category, Skill.name).all()
    skills_by_category = {}
    for skill in catalog:
        skills_by_category.setdefault(skill.category or "Other", []).append(skill)

    user_skills = (
        UserSkill.query.filter_by(user_id=current_user.id)
        .join(Skill)
        .order_by(Skill.category, Skill.name)
        .all()
    )
    return render_template(
        "skills.html",
        skills_by_category=skills_by_category,
        skills_to_teach=[item for item in user_skills if item.skill_type == "teach"],
        skills_to_learn=[item for item in user_skills if item.skill_type == "learn"],
    )


@app.route("/matches")
@login_required
def matches():
    learning_skills = (
        UserSkill.query.filter_by(user_id=current_user.id, skill_type="learn")
        .join(Skill)
        .order_by(Skill.name.asc())
        .all()
    )
    learning_skill_ids = {item.skill_id for item in learning_skills}
    match_groups = {}

    if learning_skill_ids:
        match_rows = (
            db.session.query(User, Skill)
            .join(UserSkill, UserSkill.user_id == User.id)
            .join(Skill, Skill.id == UserSkill.skill_id)
            .filter(
                User.id != current_user.id,
                User.is_active.is_(True),
                UserSkill.skill_type == "teach",
                UserSkill.skill_id.in_(learning_skill_ids),
            )
            .all()
        )
        for matched_user, skill in match_rows:
            match = match_groups.setdefault(
                matched_user.id,
                {"user": matched_user, "skills": {}},
            )
            match["skills"][skill.id] = skill

    matched_user_ids = list(match_groups)
    average_ratings = {}
    if matched_user_ids:
        rating_rows = (
            db.session.query(Review.reviewed_user_id, func.avg(Review.rating))
            .filter(Review.reviewed_user_id.in_(matched_user_ids))
            .group_by(Review.reviewed_user_id)
            .all()
        )
        average_ratings = {
            user_id: round(float(rating), 1)
            for user_id, rating in rating_rows
        }

    learning_skill_count = len(learning_skill_ids)
    matches = [
        {
            "user": match["user"],
            "skills": sorted(match["skills"].values(), key=lambda skill: skill.name.lower()),
            "match_percentage": round(len(match["skills"]) * 100 / learning_skill_count),
            "average_rating": average_ratings.get(user_id),
        }
        for user_id, match in match_groups.items()
    ]
    matches.sort(
        key=lambda match: (
            -match["match_percentage"],
            -(match["average_rating"] or 0),
            match["user"].name.lower(),
        )
    )

    return render_template(
        "matches.html",
        learning_skills=[item.skill for item in learning_skills],
        matches=matches,
    )


@app.route("/requests/create", methods=["POST"])
@login_required
def create_skill_request():
    try:
        receiver_id = int(request.form.get("receiver_id", ""))
        skill_id = int(request.form.get("skill_id", ""))
    except ValueError:
        flash("Choose a valid skill match.", "error")
        return redirect(url_for("matches"))

    message = request.form.get("message", "").strip()
    if not message:
        flash("Add a personal message before sending your request.", "error")
        return redirect(url_for("matches"))
    if len(message) > 1000:
        flash("Keep your personal message under 1,000 characters.", "error")
        return redirect(url_for("matches"))

    receiver = db.session.get(User, receiver_id)
    skill = db.session.get(Skill, skill_id)
    if receiver is None or skill is None or receiver.id == current_user.id or not receiver.is_active:
        flash("That skill match is no longer available.", "error")
        return redirect(url_for("matches"))

    can_learn = UserSkill.query.filter_by(
        user_id=current_user.id,
        skill_id=skill.id,
        skill_type="learn",
    ).first()
    can_teach = UserSkill.query.filter_by(
        user_id=receiver.id,
        skill_id=skill.id,
        skill_type="teach",
    ).first()
    if not can_learn or not can_teach:
        flash("That skill is no longer a match for your profile.", "error")
        return redirect(url_for("matches"))

    existing_request = SkillRequest.query.filter_by(
        sender_id=current_user.id,
        receiver_id=receiver.id,
        skill_id=skill.id,
    ).filter(func.lower(SkillRequest.status) == "pending").first()
    if existing_request:
        flash("You already have a pending request for this skill.", "info")
        return redirect(url_for("matches"))

    db.session.add(
        SkillRequest(
            sender_id=current_user.id,
            receiver_id=receiver.id,
            skill_id=skill.id,
            message=message,
        )
    )
    _add_notification(
        receiver.id,
        f"{current_user.name} sent you a request to learn {skill.name}.",
        "skill_request",
    )
    db.session.commit()
    flash(f"Your request to learn {skill.name} has been sent.", "success")
    return redirect(url_for("matches"))


@app.route("/requests")
@login_required
def view_requests():
    sent_requests = (
        SkillRequest.query.filter_by(sender_id=current_user.id)
        .order_by(SkillRequest.created_at.desc())
        .all()
    )
    received_requests = (
        SkillRequest.query.filter_by(receiver_id=current_user.id)
        .order_by(SkillRequest.created_at.desc())
        .all()
    )
    return render_template(
        "requests.html",
        sent_requests=sent_requests,
        received_requests=received_requests,
    )


def _update_received_request(request_id, status):
    skill_request = db.session.get(SkillRequest, request_id)
    if skill_request is None or skill_request.receiver_id != current_user.id:
        flash("You do not have permission to update that request.", "error")
        return redirect(url_for("view_requests"))
    if skill_request.status.lower() != "pending":
        flash("Only pending requests can be updated.", "error")
        return redirect(url_for("view_requests"))

    skill_request.status = status
    _add_notification(
        skill_request.sender_id,
        f"{current_user.name} {status} your request to learn {skill_request.skill.name}.",
        f"request_{status}",
    )
    db.session.commit()
    flash(f"Request {status}.", "success")
    return redirect(url_for("view_requests"))


@app.route("/requests/<int:request_id>/accept", methods=["POST"])
@login_required
def accept_skill_request(request_id):
    return _update_received_request(request_id, "accepted")


@app.route("/requests/<int:request_id>/reject", methods=["POST"])
@login_required
def reject_skill_request(request_id):
    return _update_received_request(request_id, "rejected")


@app.route("/requests/<int:request_id>/complete", methods=["POST"])
@login_required
def complete_skill_request(request_id):
    skill_request = db.session.get(SkillRequest, request_id)
    if skill_request is None or current_user.id not in {
        skill_request.sender_id,
        skill_request.receiver_id,
    }:
        flash("You do not have permission to update that request.", "error")
        return redirect(url_for("view_requests"))
    if skill_request.status.lower() != "accepted":
        flash("Only accepted requests can be marked complete.", "error")
        return redirect(url_for("view_requests"))

    skill_request.status = "completed"
    other_user_id = (
        skill_request.receiver_id
        if current_user.id == skill_request.sender_id
        else skill_request.sender_id
    )
    _add_notification(
        other_user_id,
        f"{current_user.name} marked your {skill_request.skill.name} exchange as completed.",
        "request_completed",
    )
    db.session.commit()
    flash("Skill exchange marked as completed.", "success")
    return redirect(url_for("view_requests"))


def _get_connected_users(user_id):
    connection_pairs = SkillRequest.query.with_entities(
        SkillRequest.sender_id,
        SkillRequest.receiver_id,
    ).filter(
        func.lower(SkillRequest.status).in_({"accepted", "completed"}),
        or_(
            SkillRequest.sender_id == user_id,
            SkillRequest.receiver_id == user_id,
        ),
    ).all()
    connected_user_ids = {
        receiver_id if sender_id == user_id else sender_id
        for sender_id, receiver_id in connection_pairs
    }
    connected_user_ids.discard(user_id)
    if not connected_user_ids:
        return []
    return User.query.filter(User.id.in_(connected_user_ids)).order_by(User.name.asc()).all()


def _users_are_connected(first_user_id, second_user_id):
    if first_user_id == second_user_id:
        return False
    return SkillRequest.query.filter(
        func.lower(SkillRequest.status).in_({"accepted", "completed"}),
        or_(
            and_(
                SkillRequest.sender_id == first_user_id,
                SkillRequest.receiver_id == second_user_id,
            ),
            and_(
                SkillRequest.sender_id == second_user_id,
                SkillRequest.receiver_id == first_user_id,
            ),
        ),
    ).first() is not None


@app.route("/messages", methods=["GET", "POST"])
@login_required
def messages():
    connected_users = _get_connected_users(current_user.id)

    if request.method == "POST":
        try:
            receiver_id = int(request.form.get("receiver_id", ""))
        except ValueError:
            flash("Choose a connected member to message.", "error")
            return redirect(url_for("messages"))

        receiver = next((user for user in connected_users if user.id == receiver_id), None)
        if receiver is None:
            flash("You can only message a connected member.", "error")
            return redirect(url_for("messages"))

        message_text = request.form.get("message", "").strip()
        if not message_text:
            flash("Write a message before sending.", "error")
            return redirect(url_for("messages", user_id=receiver.id))
        if len(message_text) > 2000:
            flash("Keep messages under 2,000 characters.", "error")
            return redirect(url_for("messages", user_id=receiver.id))

        db.session.add(
            Message(
                sender_id=current_user.id,
                receiver_id=receiver.id,
                message=message_text,
            )
        )
        _add_notification(
            receiver.id,
            f"{current_user.name} sent you a message.",
            "message",
        )
        db.session.commit()
        return redirect(url_for("messages", user_id=receiver.id))

    conversations = []
    for connected_user in connected_users:
        conversation_filter = or_(
            and_(
                Message.sender_id == current_user.id,
                Message.receiver_id == connected_user.id,
            ),
            and_(
                Message.sender_id == connected_user.id,
                Message.receiver_id == current_user.id,
            ),
        )
        last_message = (
            Message.query.filter(conversation_filter)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .first()
        )
        unread_count = Message.query.filter_by(
            sender_id=connected_user.id,
            receiver_id=current_user.id,
            is_read=False,
        ).count()
        conversations.append(
            {
                "user": connected_user,
                "last_message": last_message,
                "unread_count": unread_count,
            }
        )

    active_user = None
    requested_user_id = request.args.get("user_id")
    if requested_user_id:
        try:
            requested_user_id = int(requested_user_id)
        except ValueError:
            abort(404)
        active_user = next(
            (user for user in connected_users if user.id == requested_user_id),
            None,
        )
        if active_user is None:
            abort(404)
    elif conversations:
        conversations.sort(
            key=lambda conversation: (
                conversation["last_message"] is not None,
                conversation["last_message"].created_at
                if conversation["last_message"] is not None
                else 0,
            ),
            reverse=True,
        )
        active_user = conversations[0]["user"]

    thread_messages = []
    if active_user is not None:
        thread_messages = (
            Message.query.filter(
                or_(
                    and_(
                        Message.sender_id == current_user.id,
                        Message.receiver_id == active_user.id,
                    ),
                    and_(
                        Message.sender_id == active_user.id,
                        Message.receiver_id == current_user.id,
                    ),
                )
            )
            .order_by(Message.created_at.asc(), Message.id.asc())
            .all()
        )
        unread_messages = [
            message
            for message in thread_messages
            if message.receiver_id == current_user.id and not message.is_read
        ]
        if unread_messages:
            for message in unread_messages:
                message.is_read = True
            db.session.commit()

    return render_template(
        "messages.html",
        conversations=conversations,
        active_user=active_user,
        thread_messages=thread_messages,
    )


@app.route("/reviews", methods=["GET", "POST"])
@login_required
def reviews():
    if request.method == "POST":
        try:
            skill_request_id = int(request.form.get("skill_request_id", ""))
            rating = int(request.form.get("rating", ""))
        except ValueError:
            flash("Choose a completed exchange and a rating from 1 to 5.", "error")
            return redirect(url_for("reviews"))

        skill_request = db.session.get(SkillRequest, skill_request_id)
        if (
            skill_request is None
            or skill_request.status.lower() != "completed"
            or current_user.id not in {skill_request.sender_id, skill_request.receiver_id}
        ):
            flash("You can only review a completed exchange you participated in.", "error")
            return redirect(url_for("reviews"))

        if rating < 1 or rating > 5:
            flash("Choose a rating from 1 to 5 stars.", "error")
            return redirect(url_for("reviews"))

        comment = request.form.get("comment", "").strip()
        if len(comment) > 1000:
            flash("Keep your review under 1,000 characters.", "error")
            return redirect(url_for("reviews"))

        existing_review = Review.query.filter_by(
            skill_request_id=skill_request.id,
            reviewer_id=current_user.id,
        ).first()
        if existing_review:
            flash("You have already reviewed this skill exchange.", "info")
            return redirect(url_for("reviews"))

        reviewed_user_id = (
            skill_request.receiver_id
            if skill_request.sender_id == current_user.id
            else skill_request.sender_id
        )
        db.session.add(
            Review(
                reviewer_id=current_user.id,
                reviewed_user_id=reviewed_user_id,
                skill_request_id=skill_request.id,
                rating=rating,
                comment=comment or None,
            )
        )
        _add_notification(
            reviewed_user_id,
            f"{current_user.name} left you a {rating}-star review.",
            "review",
        )
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("You have already reviewed this skill exchange.", "info")
            return redirect(url_for("reviews"))

        flash("Your review has been submitted.", "success")
        return redirect(url_for("reviews"))

    completed_exchanges = (
        SkillRequest.query.filter(
            func.lower(SkillRequest.status) == "completed",
            or_(
                SkillRequest.sender_id == current_user.id,
                SkillRequest.receiver_id == current_user.id,
            ),
        )
        .order_by(SkillRequest.created_at.desc())
        .all()
    )
    completed_request_ids = [exchange.id for exchange in completed_exchanges]
    existing_reviews = (
        Review.query.filter(
            Review.reviewer_id == current_user.id,
            Review.skill_request_id.in_(completed_request_ids),
        ).all()
        if completed_request_ids
        else []
    )
    reviews_by_request = {
        review.skill_request_id: review for review in existing_reviews
    }
    reviewable_exchanges = [
        {
            "request": exchange,
            "other_user": (
                exchange.receiver
                if exchange.sender_id == current_user.id
                else exchange.sender
            ),
            "review": reviews_by_request.get(exchange.id),
        }
        for exchange in completed_exchanges
    ]

    review_count = Review.query.filter_by(reviewed_user_id=current_user.id).count()
    average_rating = db.session.query(func.avg(Review.rating)).filter(
        Review.reviewed_user_id == current_user.id
    ).scalar()
    recent_reviews = (
        Review.query.filter_by(reviewed_user_id=current_user.id)
        .order_by(Review.created_at.desc())
        .limit(8)
        .all()
    )

    return render_template(
        "reviews.html",
        reviewable_exchanges=reviewable_exchanges,
        average_rating=round(float(average_rating), 1) if average_rating is not None else None,
        review_count=review_count,
        recent_reviews=recent_reviews,
    )


@app.route("/notifications")
@login_required
def view_notifications():
    notifications = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    unread_count = sum(not notification.is_read for notification in notifications)
    return render_template(
        "notifications.html",
        notifications=notifications,
        unread_count=unread_count,
    )


@app.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.filter_by(
        id=notification_id,
        user_id=current_user.id,
    ).first()
    if notification is None:
        abort(404)

    if not notification.is_read:
        notification.is_read = True
        db.session.commit()
    return redirect(url_for("view_notifications"))


@app.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_notifications_read():
    Notification.query.filter_by(
        user_id=current_user.id,
        is_read=False,
    ).update({Notification.is_read: True}, synchronize_session=False)
    db.session.commit()
    flash("All notifications marked as read.", "success")
    return redirect(url_for("view_notifications"))


@app.route("/profile")
@login_required
def my_profile():
    return redirect(url_for("user_profile", user_id=current_user.id))


@app.route("/profile/<int:user_id>")
def user_profile(user_id):
    profile_user = db.get_or_404(User, user_id)
    is_own_profile = current_user.is_authenticated and current_user.id == profile_user.id
    if not profile_user.is_active and not is_own_profile and not (
        current_user.is_authenticated and current_user.is_admin
    ):
        abort(404)
    user_skills = (
        UserSkill.query.filter_by(user_id=profile_user.id)
        .join(Skill)
        .order_by(Skill.name.asc())
        .all()
    )
    reviews_query = Review.query.filter_by(reviewed_user_id=profile_user.id)
    review_count = reviews_query.count()
    average_rating = db.session.query(func.avg(Review.rating)).filter(
        Review.reviewed_user_id == profile_user.id
    ).scalar()

    return render_template(
        "profile.html",
        profile_user=profile_user,
        skills_to_teach=[item for item in user_skills if item.skill_type == "teach"],
        skills_to_learn=[item for item in user_skills if item.skill_type == "learn"],
        average_rating=round(float(average_rating), 1) if average_rating is not None else None,
        review_count=review_count,
        recent_reviews=reviews_query.order_by(Review.created_at.desc()).limit(6).all(),
        is_own_profile=is_own_profile,
    )


@app.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        location = request.form.get("location", "").strip()
        bio = request.form.get("bio", "").strip()
        profile_image = request.form.get("profile_image", "").strip()

        if not name or not username:
            flash("Name and username are required.", "error")
            return render_template("edit_profile.html")

        if len(name) > 120 or len(username) > 80 or len(location) > 120 or len(bio) > 1000 or len(profile_image) > 255:
            flash("One or more fields are longer than allowed.", "error")
            return render_template("edit_profile.html")

        if profile_image:
            image_url = urlsplit(profile_image)
            if image_url.scheme != "https" or not image_url.netloc:
                flash("Please use a valid public HTTPS image URL.", "error")
                return render_template("edit_profile.html")

        duplicate_username = User.query.filter(
            func.lower(User.username) == username,
            User.id != current_user.id,
        ).first()
        if duplicate_username:
            flash("That username is already taken. Please choose another.", "error")
            return render_template("edit_profile.html")

        current_user.name = name
        current_user.username = username
        current_user.location = location or None
        current_user.bio = bio or None
        current_user.profile_image = profile_image or None

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("That username is already taken. Please choose another.", "error")
            return render_template("edit_profile.html")

        flash("Your profile has been updated.", "success")
        return redirect(url_for("my_profile"))

    return render_template("edit_profile.html")


if __name__ == "__main__":
    app.run()