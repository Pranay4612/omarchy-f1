# Circuits

Intentionally empty.

Circuit outlines are **learned at runtime** from the live feed's own
`Position.z` data and cached in `~/.cache/omarchy/f1/circuits/`, not shipped
here. The reasoning is in the top-level README under "How live positions
work"; briefly:

- Formula 1 publishes no circuit vector data.
- OpenStreetMap raceway relations contain the track, but a relation also
  carries the pit lane, access roads and the paddock. The recoverable loop came
  out at 7.8 km for Baku against a 6.0 km lap, and the real lap could not be
  separated reliably. It is also ODbL.
- The public static archive keeps only about three position samples per
  session, which is not enough to order points into a lap.

Learning from a live session sidesteps all three: the outline is derived from
the same coordinate frame the car markers are drawn in, so there is no
projection, no fit and no way for a marker to end up off the track. It is also
correct for circuits that did not exist when this plugin was written.

Inspect and manage what has been learned:

```bash
bin/f1-learn-circuit --list
bin/f1-learn-circuit --live
bin/f1-learn-circuit --capture <dir>
```
