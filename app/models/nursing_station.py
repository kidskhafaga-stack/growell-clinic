"""Nursing stations — a place beside certain عيادات, not a person.

A nurse serving three of the clinic's eight rooms was shown all eight, and
had to find their children in somebody else's list every time.

**The scope belongs to the station, not to the nurse.** That is the whole
design decision here, and it came from the clinic rather than from me: I
first proposed remembering a set of rooms per *user*, and was corrected —
nursing staff rotate between stations, so a preference stored on the person
walks off with them the day they cover somebody else's shift. The station is
the thing that stays beside the same doors.

**Rooms, not doctors**, for the mirror-image reason. Doctors move between
rooms; the station does not. So a station holds عيادات, and which doctors it
covers today is read from the day's room assignments — which means nobody has
to remember to update anything when the rota changes.
"""
from datetime import datetime

from app.extensions import db

# Which rooms a station covers. A plain link table: a room can be shared by
# two stations (a corridor with a station at each end is a real layout), and a
# station covering nothing is a station somebody has not finished setting up
# rather than an error.
station_rooms = db.Table(
    "nursing_station_rooms",
    db.Column("station_id", db.Integer, db.ForeignKey("nursing_stations.id"),
              primary_key=True),
    db.Column("room_id", db.Integer, db.ForeignKey("clinic_rooms.id"),
              primary_key=True),
)


class NursingStation(db.Model):
    __tablename__ = "nursing_stations"

    id = db.Column(db.Integer, primary_key=True)
    name_ar = db.Column(db.String(80), nullable=False)
    name_en = db.Column(db.String(80))
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    rooms = db.relationship("ClinicRoom", secondary=station_rooms,
                            lazy="selectin",
                            order_by="ClinicRoom.sort_order")

    def display_name(self, lang="ar"):
        if lang == "en" and self.name_en:
            return self.name_en
        return self.name_ar

    @property
    def room_ids(self):
        return {room.id for room in self.rooms}

    def doctor_ids_on(self, on_date):
        """Whose patients this station is responsible for on ``on_date``.

        Derived from the day's room assignments rather than stored, so a
        doctor moving room is followed automatically. A station with no rooms
        yet covers nobody — deliberately: showing it the whole clinic while
        somebody is halfway through setting it up is how a nurse ends up
        weighing a child from the other end of the corridor.
        """
        from app.models import RoomAssignment

        mine = self.room_ids
        if not mine:
            return set()
        rows = (RoomAssignment.query
                .filter(RoomAssignment.on_date == on_date,
                        RoomAssignment.room_id.in_(mine))
                .all())
        return {row.doctor_id for row in rows}
