/*
 * What a match group needs to know about the scrub it is riding: the round
 * position `pos` (a shared value), the index of the column it is in, the
 * measured geometry, and half the distance between a settled group's two
 * boxes. A group reads these in worklets to stretch or condense itself
 * (bracket.jsx); RoundScrub's Column provides them. The default is a group
 * at rest, for anywhere a group is drawn with no scrub around it.
 */
import { createContext } from 'react'

export const ScrubContext = createContext({ pos: null, ri: 0, geo: null, e: 0 })
