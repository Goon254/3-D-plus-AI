# Savannah set — time-of-day tests

`set_dawn.jpg`, `set_midday.jpg`, `set_sunset.jpg`, `set_night.jpg`: the same layout under four skies, with Tembo and Neema
standing in the action area (Cycles on OptiX, 1280×720, ~3 s per still).

* **Grass**: a clump of curved, tapering blades (root olive to straw tip), scattered with geometry nodes. It sways in a wind
  that travels across the field (noise over position + scene time). It stays short in the action area so feet stay
  visible, and it is cleared around the water.
* **Acacias**: a skinned trunk forking into spreading branches under a flat-topped metaball canopy.
* **Termite mounds, rocks, watering hole** (water, wet-mud rim, reed bed), **distant mountains** dissolving into
  the horizon haze.
* **Sky**: a gradient with a glow band and cumulus wisps; the night sky has a starfield and blue moonlight.

`python scripts/savannah_set_test.py --tod sunset` (module: `src/animatica/sets/savannah.py`).
