/*
 * What a match group needs to know about the scrub it is riding: the round
 * position `pos` (a shared value), the column and row it is in, the measured
 * geometry, half the distance between a settled group's two boxes, and the
 * scroll offset and viewport height it uses to tell whether it can be seen
 * at all. A group reads these in worklets to stretch or condense itself
 * (bracket.jsx); RoundScrub's Row provides them. The default is a group at
 * rest, for anywhere a group is drawn with no scrub around it.
 */
import { createContext } from 'react'

export const ScrubContext = createContext({
  pos: null, ri: 0, i: 0, geo: null, e: 0, scrollY: null, viewportH: null, margin: 0,
})
