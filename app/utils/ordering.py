"""Keeping a hand-ordered catalogue in order, without anybody typing a number.

The service-type and client-category managers each had a ``sort_order`` box to
fill in. Typing sort numbers looks like the simple option and is the one that
misbehaves:

* **They collide.** Two rows both numbered 3 sort by whatever their ids happen
  to be, so somebody types a number, presses save, and the list does not move.
  Nothing is broken enough to report — it just does not work.
* **They develop gaps.** After a few deletions the numbers read 0, 3, 4, 9, so
  "put this one second" means reading the other rows and working out a number
  that fits between two of them.
* **And they are not the question being asked.** Nobody wants row number 6;
  they want this row above that one.

So the number is the program's business now. The screen offers up and down, and
every change renumbers the whole list compactly — which is also what stops the
gaps and the collisions from ever accumulating.
"""


def renumber(rows):
    """Rewrite ``sort_order`` as 0, 1, 2 … over ``rows`` in their given order.

    Returns how many rows actually changed, so a caller can skip the commit
    when there was nothing to do.
    """
    changed = 0
    for index, row in enumerate(rows):
        if row.sort_order != index:
            row.sort_order = index
            changed += 1
    return changed


def ordered(model):
    """Every row of ``model``, in display order."""
    return model.query.order_by(model.sort_order, model.id).all()


def move(model, row, direction):
    """Move ``row`` one place up (-1) or down (+1) among its siblings.

    Returns ``True`` when something moved. Moving the first row up, or the last
    one down, is not an error — it is somebody pressing a button at the end of
    a list, and it does nothing.

    The list is renumbered afterwards rather than the two rows' numbers being
    swapped: a swap preserves whatever collisions and gaps were already in
    there, and the next move would misbehave for a reason nobody could see.
    """
    rows = ordered(model)
    try:
        index = next(i for i, r in enumerate(rows) if r.id == row.id)
    except StopIteration:
        return False
    target = index + (1 if direction > 0 else -1)
    if target < 0 or target >= len(rows):
        return False
    rows[index], rows[target] = rows[target], rows[index]
    renumber(rows)
    return True


def append_order(model):
    """The ``sort_order`` a newly added row should get: the end of the list."""
    rows = ordered(model)
    return len(rows)
