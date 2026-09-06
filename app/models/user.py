"""User model and authentication helpers."""
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager
from app.models.permissions import ROLES, role_can_access, role_modules


# The printed size of a doctor's signature and stamp at 100%, as
# ``(max_height_px, max_width_px)``. These were two pairs of numbers written
# into the prescription template; a clinic that wanted a bigger stamp had to
# be told "that is not something the program does".
PRINT_IMAGE_BOX = {"signature_file": (60, 200), "stamp_file": (90, 140)}
PRINT_SCALE_MIN, PRINT_SCALE_MAX = 40, 250


def clamp_print_scale(value, fallback=100):
    """A percentage that cannot make an image vanish or eat the page."""
    try:
        pct = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(PRINT_SCALE_MIN, min(PRINT_SCALE_MAX, pct))


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # Bilingual display names.
    full_name = db.Column(db.String(120), nullable=False)
    full_name_en = db.Column(db.String(120))

    role = db.Column(db.String(20), nullable=False, default="reception")
    # Owner / super-admin: an admin who also controls the institution-level
    # settings (facility setup, multi-doctor config, data reset). A plain admin
    # runs everything else but cannot reshape the clinic itself.
    is_super_admin = db.Column(db.Boolean, default=False, nullable=False)
    # Non-doctor roles (e.g. an admin who also sees patients) can be flagged as
    # practitioners so they appear in the appointments / doctor pickers without
    # every admin showing up as a doctor.
    is_practitioner = db.Column(db.Boolean, default=False, nullable=False)

    @staticmethod
    def sees_patients(role, is_practitioner):
        """Whether somebody with this role and flag consults.

        Stated once because two things ask it and they must not drift: the
        licence counts these as doctor seats, and the pickers show them. A
        doctor is `role == "doctor"`; the flag is what lets a non-doctor role
        — an admin who also sees patients — join them without every admin
        being counted as a doctor.
        """
        return role == "doctor" or bool(is_practitioner)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    # Preferred UI language, applied on login (doctors default to English).
    language = db.Column(db.String(5))

    # Profile.
    photo = db.Column(db.String(255))          # profile picture filename
    job_title = db.Column(db.String(120))      # المسمى الوظيفي
    branch = db.Column(db.String(120))         # الفرع

    # Doctor profile / branding.
    rx_display_name = db.Column(db.String(160))     # الاسم الظاهر في الروشتة
    professional_title = db.Column(db.String(40))   # Professor/Consultant/...
    specialty = db.Column(db.String(160))           # التخصص الرئيسي
    sub_specialties = db.Column(db.String(255))     # التخصصات الفرعية

    # **How this doctor is settled: on what was billed, or on what came in.**
    #
    # The agreement with them, not a rule in any file. Cash work is collected
    # at the desk the same hour, so for most clinics the two are one number
    # and this stays empty. Contract work is paid when the insurer sends the
    # money, and settling that at billing pays a doctor out of money the
    # clinic has not got.
    #
    # Null means the program's default, which is "billed" — what every figure
    # in this program has always meant, so a clinic that updates and sets
    # nothing settles exactly as it did yesterday.
    settlement_basis = db.Column(db.String(10))

    # The coded panel this doctor's visits open on — a key from
    # app/data/specialty_panels.json, and a different thing from `specialty`
    # above. That one is free text and prints on the prescription; a doctor has
    # typed anything into it, and matching a panel against prose is a lookup
    # that works in testing and fails on a real clinic.
    specialty_panel = db.Column(db.String(40))
    # And the rest of them. A doctor works more than one specialty — general
    # paediatrics and gastroenterology follow the same children — and the
    # single column above could only hold one, so the visit screen offered one
    # and the doctor changed it by hand every time.
    #
    # Comma-separated keys rather than a join table: it is a handful of keys
    # per doctor, read on every visit render and written on a settings screen,
    # and three files to answer what one column answers is not a better shape.
    # `specialty_panel` stays as *which of them opens first*.
    specialty_panels = db.Column(db.String(255))
    # Free multi-line titles printed under the doctor's name on the Rx — one
    # qualification per line (consultant / hospital / fellowship…), AR & EN.
    print_title_ar = db.Column(db.Text)
    print_title_en = db.Column(db.Text)
    license_no = db.Column(db.String(60))           # رقم الترخيص/النقابة
    signature_file = db.Column(db.String(255))      # التوقيع الرقمي
    stamp_file = db.Column(db.String(255))          # الختم الطبي
    # How big each of those prints, as a percentage of the built-in size. A
    # scan is whatever size the scanner made it, and the two that matter are
    # the two nobody can retake: a signature that came out postage-stamp
    # sized, and a stamp that swallows the bottom of the page.
    signature_scale = db.Column(db.Integer, default=100)
    stamp_scale = db.Column(db.Integer, default=100)
    personal_logo = db.Column(db.String(255))       # شعار شخصي (اختياري)
    accent_color = db.Column(db.String(20))         # لون مميز
    rx_template_id = db.Column(db.Integer, db.ForeignKey("rx_print_templates.id"), nullable=True)
    # Which nursing station this person last worked at. Remembered so nobody
    # re-picks it every morning — the scope itself belongs to the station, not
    # to them, and one press on the screen moves them to another.
    nursing_station_id = db.Column(db.Integer,
                                   db.ForeignKey("nursing_stations.id"),
                                   nullable=True)
    # A doctor's own quick phrases for the visit screen. They used to be one
    # list for the whole clinic, which is the wrong shape: the sentences a
    # paediatrician reaches for are not a dermatologist's, and a shared list
    # grows until typing is faster than finding. Blank means "use the
    # clinic's", so nobody starts from an empty palette.
    visit_complaint_chips = db.Column(db.Text)
    visit_exam_chips = db.Column(db.Text)
    visit_plan_chips = db.Column(db.Text)

    # UI personalization (per user).
    theme = db.Column(db.String(10))                # light | dark
    # Sidebar width preference. A collapse that comes back open on the next
    # page is worse than no collapse: you re-do it all day and it never sticks.
    sidebar = db.Column(db.String(10))              # full | rail
    font_scale = db.Column(db.String(4))            # sm | md | lg
    default_landing = db.Column(db.String(30))      # module key after login

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # --- Password handling -------------------------------------------------
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # --- Permissions -------------------------------------------------------
    def _role_record(self):
        """Look up the editable Role row, or None (pre-seed / DB not ready).

        Read once per request: every permission check on every row of every
        list asks for it, so an appointment board was fetching one role row a
        hundred and forty times to draw one page.
        """
        from app.utils.request_cache import remember

        def load():
            try:
                from app.models.role import Role
                return Role.query.filter_by(name=self.role).first()
            except Exception:  # noqa: BLE001 - DB not ready / outside context
                return None

        return remember(f"role:{self.role}", load)

    @property
    def is_admin(self):
        rec = self._role_record()
        if rec is not None:
            return rec.is_admin
        return self.role == "admin"

    @property
    def is_owner(self):
        """Super-admin: an admin flagged as the institution's owner. Owners
        reach the facility/institution settings a plain admin cannot."""
        return bool(self.is_super_admin) and self.is_admin

    def can_access(self, module):
        """Whether this user's role may reach ``module``."""
        rec = self._role_record()
        if rec is not None:
            return rec.is_admin or module in rec.module_list
        return role_can_access(self.role, module)  # static fallback

    @property
    def can_collect(self):
        """Whether this person may take money — the till, not the ledger.

        The same test ``cashier_access`` applies to the routes, said once so
        the buttons and the doors cannot disagree. They did: the collect
        button on the appointment board, the "invoice this visit" button on
        the visit, and the invoice link on the patient profile were all drawn
        only for ``can_access('finance')`` — the whole finance module — while
        every route behind them accepts the ``cashier`` capability on its own.

        So a receptionist who could open the checkout by typing its address
        was shown no way to reach it: reported as "the collect button doesn't
        appear after a booking", and again as "the money owed doesn't show
        when the doctor has done something". One condition, three copies of
        it, and all three were the wrong one.
        """
        return self.can_access("finance") or self.can("cashier")

    def can(self, capability):
        """Whether this user has a fine-grained capability.

        Their role first, then anything granted to **them personally** — the
        clinic's "the reception does certain things in finance" case, without
        giving every receptionist the capability and without inventing a role
        for one person.

        Grants can only add. There is deliberately no way to take a capability
        away from one holder of a role: a role whose list did not mean what it
        said would have to be checked holder by holder, and the honest way to
        stop somebody is to change their role where everyone can see it.
        """
        from app.models.permissions import role_has_capability
        rec = self._role_record()
        if rec is not None and rec.is_admin:
            return True
        # The role's own list, then the built-in table, then this person's
        # grants — a union, deliberately. A clinic upgrading has roles whose
        # new `capabilities` column is empty, and reading only the column
        # would take the till away from every receptionist on the morning of
        # the upgrade. Reading only the built-in table is the bug this fixes:
        # a role the clinic invented is in no table in the code, so it could
        # hold nothing at all.
        if rec is not None and capability in rec.capability_list:
            return True
        if role_has_capability(self.role, capability):
            return True
        return capability in self.granted_capabilities

    @property
    def granted_capabilities(self):
        """Capabilities given to this person beyond their role."""
        try:
            from app.models.user_capability import UserCapability

            rows = UserCapability.query.filter_by(user_id=self.id).all()
            return {row.capability for row in rows}
        except Exception:                                   # pragma: no cover
            # A permission screen is not worth a 500, and falling back to the
            # role alone is the safe direction: it can only ever allow less.
            return set()

    @property
    def modules(self):
        """Modules visible to this user (drives the sidebar)."""
        rec = self._role_record()
        if rec is not None:
            return rec.module_list
        return role_modules(self.role)

    def display_name(self, lang="ar"):
        """Return the localized display name with a sensible fallback."""
        if lang == "en" and self.full_name_en:
            return self.full_name_en
        return self.full_name

    # How a doctor is addressed, per language. Everybody is "د/" — except a
    # professor, who is "أ.د/". Asked for in exactly those words, and it is
    # the convention every Egyptian prescription follows.
    HONORIFICS = {
        "Professor": {"ar": "أ.د/", "en": "Prof. Dr."},
    }
    DEFAULT_HONORIFIC = {"ar": "د/", "en": "Dr."}

    def doctor_honorific(self, lang="ar"):
        """"د/" or "أ.د/" — derived from the doctor's classification.

        Derived, not typed. It used to print ``professional_title`` verbatim,
        which put the English word *Consultant* in front of an Arabic name on
        an Arabic prescription; and every screen that wanted a doctor's name
        with a title had to remember to add one itself, so most of them did
        not. One rule here means the same doctor reads the same way on a
        prescription, a report and a screen.
        """
        table = self.HONORIFICS.get(self.professional_title or "",
                                    self.DEFAULT_HONORIFIC)
        return table.get(lang, table.get("ar", ""))

    def print_image_box(self, field):
        """``(max_height, max_width)`` in px for a signature or stamp.

        Scaled in both directions, so the image keeps its shape — a box that
        grew in height alone would squash a wide signature rather than
        enlarge it, which is the failure this exists to fix.
        """
        base_h, base_w = PRINT_IMAGE_BOX[field]
        pct = clamp_print_scale(
            getattr(self, field.replace("_file", "_scale"), None) or 100)
        return round(base_h * pct / 100), round(base_w * pct / 100)

    # A name that already carries its own title. Checked before one is added,
    # so "د/ أحمد" never prints as "د/ د/ أحمد" — which is how this sort of
    # rule usually announces itself.
    CARRIES_TITLE = ("د/", "د.", "د ", "أ.د", "أ/", "Dr", "Prof", "Pr.")

    def doctor_print_name(self, lang="ar"):
        """Name shown on the doctor's prescriptions and printouts, with title.

        **The title is added here so nobody has to type it into their name.**
        Asked for in exactly those terms: *"المستخدم دكتور يحط ده جنب اسمه، مش
        لازم أكتب في اسمه د.أحمد"*.

        ``rx_display_name`` — the prescription-specific name — used to be
        returned untouched on the reasoning that somebody who typed there had
        chosen their exact wording. That is true of the clinics who put their
        *practice* name on the paper ("العيادة التخصصية للأطفال"), which must
        never be addressed as a doctor. It was not true of the doctor who
        typed their own plain name into a box labelled "the name shown on the
        prescription", and silently lost their title on every sheet.

        So the two are told apart rather than guessed at: when that field
        holds **this person's own name**, it is a name and gets the title;
        when it holds anything else, it is somebody's exact wording and is
        printed as written.
        """
        chosen = (self.rx_display_name or "").strip()
        base = chosen or self.display_name(lang)
        honorific = self.doctor_honorific(lang)
        if not honorific:
            return base
        if chosen and not self._is_own_name(chosen):
            return chosen
        if any(base.strip().startswith(known) for known in self.CARRIES_TITLE):
            return base
        return f"{honorific} {base}"

    def _is_own_name(self, text):
        """Is this the doctor's own name, or a different piece of wording?

        The one question that separates a doctor who typed their name into the
        prescription-name box from a clinic that put its practice name there.
        Compared on the whitespace-collapsed strings, because the difference
        that matters is never a double space.
        """
        def flat(value):
            return " ".join((value or "").split()).casefold()

        needle = flat(text)
        return bool(needle) and needle in {flat(self.full_name),
                                           flat(self.full_name_en)}

    def doctor_title_lines(self, lang="ar"):
        """Qualification lines printed under the name (one per line).

        Uses the free multi-line ``print_title_*`` when set, otherwise falls
        back to the structured specialty / sub-specialties fields."""
        raw = (self.print_title_en if lang == "en" else self.print_title_ar) or ""
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if lines:
            return lines
        fallback = []
        if self.specialty:
            fallback.append(self.specialty
                            + (f" — {self.sub_specialties}" if self.sub_specialties else ""))
        return fallback

    def role_label(self, lang="ar"):
        rec = self._role_record()
        if rec is not None:
            return rec.label(lang)
        return self.role

    @staticmethod
    def valid_role(role):
        try:
            from app.models.role import Role
            if Role.query.filter_by(name=role).first():
                return True
        except Exception:  # noqa: BLE001
            pass
        return role in ROLES

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
