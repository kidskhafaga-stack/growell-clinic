"""The number a clinic writes down, so an alert can start firing.

**This is the whole reason the specialty alerts were dormant.** The survey
asked every specialty *"متى ينبّهك البرنامج من نفسه؟"* and the answers name a
hundred and three alerts. Twenty-two of them are a threshold — HbA1c above a
figure, saturation below one, ferritin over a limit — and the survey itself
refuses to supply the figure: its own answer for cardiology is *"لا يوجد رقم
موحّد"*.

This program does not invent clinical numbers. So the alerts were declared and
did not fire, which was the honest state — and then stayed that way, because
**there was nowhere for a clinic to write its figure down.** A feature built
and no door to it, which is the failure this codebase keeps finding in itself.

**One row per clinic decision, and nothing shipped in it.** A fresh install has
no rows here and no threshold alerts, exactly as before. A clinic that writes
"HbA1c above 8" gets that alert and no other, and the number is theirs — shown
back to them on the screen that fires it, so nobody ever wonders where a
warning came from.

**Not merged into the catalogue.** The catalogue is a data file the program
ships and replaces on update; a clinic's own figure written into it would be
overwritten by the next release. It is a row, in their database, which an
upgrade never touches.
"""
from datetime import datetime

from app.extensions import db


class PanelAlertRule(db.Model):
    """One specialty alert, and the number this clinic set for it."""

    __tablename__ = "panel_alert_rules"
    __table_args__ = (
        # One number per alert per specialty. Two rows would mean two answers
        # to "when do you want to be told", and whichever the query happened
        # to read first would win silently.
        db.UniqueConstraint("panel_key", "alert_code", name="uq_panel_alert"),
    )

    id = db.Column(db.Integer, primary_key=True)
    panel_key = db.Column(db.String(40), nullable=False, index=True)
    alert_code = db.Column(db.String(40), nullable=False, index=True)

    # The figure itself. Nullable, and null means the same as no row at all:
    # the alert is not armed. Kept nullable rather than deleting the row so a
    # clinic can clear a number without losing that they once looked at it.
    threshold = db.Column(db.Float)

    # Switched off without losing the number. A clinic silencing an alert for
    # a month should not have to remember what it was set to.
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    note = db.Column(db.String(160))
    set_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    set_at = db.Column(db.DateTime, default=datetime.utcnow,
                       onupdate=datetime.utcnow, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    author = db.relationship("User", foreign_keys=[set_by])

    @property
    def is_armed(self):
        """Whether this alert will fire at all. A number and a yes."""
        return bool(self.is_active and self.threshold is not None)

    def __repr__(self):
        return f"<PanelAlertRule {self.panel_key}.{self.alert_code}>"
