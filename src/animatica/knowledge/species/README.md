# Species notes — how to read them

Notes the Asset, Animator and Director agents use for the savannah cast. Written from legal sources
only: peer-reviewed papers and abstracts, zoo/conservation/educational fact sheets, Wikipedia text, and
public-domain Muybridge plates (studied, not copied). **No images or videos are in the repo.** Every
number cites its source at the end of the note.

## Gait vocabulary

* **Stride**: one full cycle of a reference limb (touchdown to the next touchdown).
* **Duty factor (β)**: the fraction of the stride a foot is on the ground. β > 0.5 = walking (some foot
  always down); β < 0.5 = running gaits with airborne phases.
* **Footfall phase**: when each foot touches down, as a fraction of the stride after the left hind (LH).
  Order of limbs in the tables: LH, LF, RH, RF.
* **Limb phase**: how long after a hind touchdown the *same-side* fore touches down (fraction of the
  stride). 0.25 = an evenly spaced four-beat "singlefoot". < 0.25 = "lateral couplets" (giraffe). Near 0.5
  = diagonal couplets (tortoise, trot).
* **Lateral-sequence (LS) walk**: a hind touchdown is followed by the fore on the same side. Most
  quadrupeds use it: horses, zebras, elephants, giraffes.

## Production rules that follow from the research

1. A stance foot is **locked to the ground** (foot-lock). The body moves over it; it never slides.
2. Stride length comes from speed and stride frequency (`L = v / f`). Never scale the cycle to fit a path.
3. Body motion is derived from the footfalls: the hips and shoulders drop slightly when a limb pair is in
   double support and rise in single support. They roll toward the stance side.
4. Use the gait whose duty factor fits the speed: walk β ≈ 0.6–0.8, trot β ≈ 0.4, and run below that.
   Elephants never leave the ground.
