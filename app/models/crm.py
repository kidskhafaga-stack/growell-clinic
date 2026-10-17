"""Who is talking to the clinic, and the families who asked but have not come.

``CONNECTHUB_PLAN.md``, stage one. A question under a post, a call asking
which doctor sees asthma, a walk-in at the desk — each is somebody who might
become a patient, and until now there was nowhere to write them down unless
they already had a file or wrote on WhatsApp.

* **A contact** is the person, whatever channel they used. A family that
  wrote on Instagram and then called is one contact with two identities.
* **An identity** is one way to reach them: a phone, an e-mail, a handle on
  one platform. ``(kind, value)`` is unique, and the value is stored the way
  it is compared (a number in its international digits, a handle without its
  ``@``). **A name is never an identity**: two mothers called «منى أحمد» are
  two people, and a program that merges them has mixed two children's files.
* **The file** (``patient_id``) is set only by a person pressing "link", and
  who did it is kept — the same rule the inbox keeps for a number.
* **A lead** is the open question: where they came from, what they asked
  for, who is following them up and when, and how it ended — a booking
  request made from it, or not completed and why.
"""
from datetime import datetime

from app.extensions import db

#: The kinds of identity a contact may carry. Not the channel: a WhatsApp
#: message, a phone call and the request page all reach the same phone.
IDENTITY_KINDS = ("phone", "email", "instagram", "messenger", "tiktok",
                  "telegram",
                  # The ids a platform gives the person who wrote to the
                  # clinic — never typed by anybody, only received
                  # (``CONNECTHUB_PLAN.md`` stage two): the Page-scoped id on
                  # Messenger, the Instagram-scoped id (the same in a direct
                  # message and a comment), Telegram's user id, and the id
                  # of someone who commented on the Facebook Page — which is
                  # not their Messenger id, so it is kept apart.
                  "messenger_psid", "instagram_igsid", "telegram_id",
                  "facebook_user")
#: The kinds a person types into a form.
TYPED_KINDS = ("phone", "email", "instagram", "messenger", "tiktok",
               "telegram")

#: جديد، تم التواصل، مهتم، في انتظار الرد، تم التحويل، غير مكتمل.
LEAD_STAGES = ("new", "contacted", "interested", "waiting", "converted",
               "lost")
#: Still somebody's job.
OPEN_STAGES = ("new", "contacted", "interested", "waiting")
#: What a person may move a lead to by hand. ``converted`` is not one of
#: them: it happens when a booking request is actually made from it.
MANUAL_STAGES = ("new", "contacted", "interested", "waiting", "lost")

#: How the question reached us — the "what", beside the channel's "where".
SOURCE_KINDS = ("message", "comment", "call", "walk_in", "form", "ad",
                "referral", "other")

#: Why a lead ended without a booking. Kept short and countable, with a
#: free note beside it, so "why do we lose them" has an answer.
LOST_REASONS = ("no_reply", "price", "no_slot", "went_elsewhere",
                "not_needed", "out_of_area", "other")


class Contact(db.Model):
    __tablename__ = "crm_contacts"

    id = db.Column(db.Integer, primary_key=True)
    # The name they gave — shown, never matched on.
    name = db.Column(db.String(120), nullable=False)
    note = db.Column(db.String(255))
    # Set only by a person, with who and when.
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           index=True)
    linked_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    linked_at = db.Column(db.DateTime)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    patient = db.relationship("Patient")
    linker = db.relationship("User", foreign_keys=[linked_by])
    identities = db.relationship("ContactIdentity", backref="contact",
                                 order_by="ContactIdentity.id",
                                 cascade="all, delete-orphan")

    def identity(self, kind):
        """The first identity of ``kind``, or ``None``."""
        for row in self.identities:
            if row.kind == kind:
                return row
        return None

    @property
    def phone(self):
        row = self.identity("phone")
        return row.value if row is not None else None

    def __repr__(self):
        return f"<Contact {self.id}>"


class ContactIdentity(db.Model):
    __tablename__ = "crm_contact_identities"
    __table_args__ = (db.UniqueConstraint("kind", "value",
                                          name="uq_crm_identity"),)

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey("crm_contacts.id"),
                           nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False)
    # As compared: international digits, lower-case e-mail, handle without @.
    value = db.Column(db.String(160), nullable=False)
    # As they wrote it, for showing.
    shown = db.Column(db.String(160))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    def __repr__(self):
        return f"<ContactIdentity {self.kind}:{self.value}>"


class Lead(db.Model):
    __tablename__ = "crm_leads"

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey("crm_contacts.id"),
                           nullable=False, index=True)
    stage = db.Column(db.String(12), default="new", nullable=False,
                      index=True)
    # Where (``utils/channels.CHANNELS``) and what (``SOURCE_KINDS``).
    channel = db.Column(db.String(16), nullable=False, index=True)
    source_kind = db.Column(db.String(12), default="message", nullable=False)
    # The campaign, post or ad it came from — free text the clinic names
    # (the request page fills it from ``?src=``), and the post's link.
    campaign = db.Column(db.String(80), index=True)
    source_url = db.Column(db.String(300))
    # What they asked about.
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    interest = db.Column(db.String(200))
    message = db.Column(db.Text)

    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    follow_up_on = db.Column(db.Date, index=True)
    lost_reason = db.Column(db.String(16))
    # The WhatsApp conversation it was taken from, when it was.
    conversation_key = db.Column(db.String(64), index=True)
    booking_request_id = db.Column(db.Integer,
                                   db.ForeignKey("booking_requests.id"))

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)
    # The first time anybody moved it past "new" — how long a family waited
    # for somebody to get back to them is read from this.
    first_contact_at = db.Column(db.DateTime)
    stage_at = db.Column(db.DateTime, default=datetime.utcnow,
                         nullable=False)
    closed_at = db.Column(db.DateTime)

    contact = db.relationship("Contact", backref="leads")
    doctor = db.relationship("User", foreign_keys=[doctor_id])
    owner = db.relationship("User", foreign_keys=[owner_id])
    creator = db.relationship("User", foreign_keys=[created_by])
    booking_request = db.relationship("BookingRequest")
    events = db.relationship("LeadEvent", backref="lead",
                             order_by="LeadEvent.id.desc()",
                             cascade="all, delete-orphan")

    @property
    def is_open(self):
        return self.stage in OPEN_STAGES

    def __repr__(self):
        return f"<Lead {self.id} {self.stage}>"


class LeadEvent(db.Model):
    """One step on a lead: opened, moved, handed over, a call, a note."""
    __tablename__ = "crm_lead_events"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("crm_leads.id"),
                        nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False)
    detail = db.Column(db.String(255))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User")

    def __repr__(self):
        return f"<LeadEvent {self.lead_id} {self.kind}>"
