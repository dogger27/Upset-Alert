/*
 * What a match group needs to know about the scrub it is riding: ONE shared
 * value, `stretch` — how far each of its halves has moved from where it sits
 * settled, positive apart, negative together. RoundScrub's reaction writes
 * it for the rows on screen; the group reads it in its worklets to stretch
 * or condense itself (bracket.jsx). The default is a group at rest, for
 * anywhere a group is drawn with no scrub around it.
 */
import { createContext } from 'react'

export const ScrubContext = createContext({ stretch: null })
