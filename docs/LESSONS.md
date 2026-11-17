# LESSONS — every human catch becomes a check (DESIGN_STAGE.md §8)

| caught by a human | class | automatic check now | test |
|---|---|---|---|
| meerkat reads as a rat / hamster / weasel | species read | `read:silhouette`, `read:thumbnail`: unprompted name, known confusions fail (`animatica.design.critic.reads_as`) | `test_species_read_needs_the_name_without_a_confusion` |
| elephant head melted into the body | head separation | `silhouette:neck_notch` on the side silhouette (dip, throat, or a head raised ≥ half a head above the back), plus the `neck_head` ratio | `test_neck_notch_separates_a_clear_head_from_a_melted_one`, `test_a_head_carried_high_on_a_sloping_neck_counts_as_separate` |
| meerkat "sunglasses" patches, black boot legs | flat black blocks | `materials:flat_black` (near-black body regions not in `dark_ok`), `materials:dark_blob` | `test_meerkat_black_legs_are_flagged_and_the_lift_fixes_them`, `test_floating_parts_and_dark_blobs` |
| googly side eyes, eyes not in sockets | eye seating | `rig_checks` eye embed/drift (`animatica.creatures.qa`) | `test_eye_socket_snap_carry_and_seating` |
| textures sliding on the skin | texture swim | `texture_swim` (rest-position pin) | `test_texture_swim_check_and_rest_position_pin` |
| floating brows / parts | floating parts | `silhouette:floating`, brow/lid gap in `rig_checks` | `test_floating_parts_and_dark_blobs` |
| expressions barely change the face (cloud review 11-17) | weak acting | `face:happy`, `face:surprised` (share of the close-up that changes) | `test_expression_change_and_the_face_check` |
| meerkat sentinel leaned forward with a dangling paw (cloud review 11-17 06:36) | signature-pose read | the sentinel silhouette is the `read:silhouette` input; the pose itself is now straight with paws tucked and the tail as a tripod (DECISIONS #53) | none automatic yet (recorded critique `design/kiki/v2/critique.json`); the rig stress test should measure paw-to-chest distance and tail-ground contact |
| a critique of an old render passing a new one | stale review | recorded critiques carry the sheet's SHA-256 | `test_recorded_critique_only_applies_to_the_sheet_it_was_written_for` |

Still caught only by eye (open): stripe bullseyes on front/back views, edge-on disc ears, a ball-shaped shell,
broccoli acacias, a horizon stripe, a static 22-second opening (the last three belong to the animatic gate).
