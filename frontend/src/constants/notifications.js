/*
 * The canonical list of notification types.
 *
 * Two places need it and neither can derive it from the other: Navbar's
 * settings grid pairs each key with a label, a description and its group, while
 * PushPrompt only needs the keys so it can switch every type on at once. The
 * server has the same list a third time (main.py's unsubscribe labels, auth.py's
 * defaults), but exposes no endpoint that enumerates it.
 *
 * ADDING A TYPE: add the key here AND the full row to Navbar's NOTIF_GROUPS.
 * Miss this file and the new type silently stays off for everyone who enables
 * push from the prompt — a notification nobody ever receives and nothing
 * reports as broken.
 */
export const ALL_NOTIFICATION_KEYS = [
  'draw_released',
  'draw_changed',
  'qualifiers_added',
  'standout_pick',
  'round_standings',
  // Kept alongside round_standings rather than treated as covered by it. The
  // settings grid greys this row out while Round completion is on, but the
  // round digest picks exactly one preference per batch — tournament_end for a
  // final, round_standings otherwise — so holding only the latter means no push
  // at all for the round people care most about.
  'tournament_end',
  'league_member_joined',
]

/** The push twin of an email preference key. Mirrors push.py's PUSH_PREFIX. */
export const pushKey = (key) => `push_${key}`
