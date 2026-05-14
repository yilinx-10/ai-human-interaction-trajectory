import { writable } from 'svelte/store'


// Selected item for the detail panel — null or { type, data }
export const selectedItem = writable(null)

// Cached data (avoid re-fetching on tab switch)
export const topicData = writable(null)

export const beliefData = writable(null)

// Belief layer date range filter: indices into BELIEF_DATES array
export const beliefFilter = writable({ startIdx: 0, endIdx: 11 })

// Belief view mode: 'global' (all networks) | 'conversation' (single network zoom)
export const beliefViewMode = writable('global')

// Which conversation is zoomed in conversation mode
export const beliefFocusedConvId = writable(null)

// Edit mode in conversation view: 'none' | 'addNode' | 'addEdge' | 'delete'
export const beliefEditMode = writable('none')

// User edits layered on top of pipeline data (in-memory)
export const beliefEdits = writable({
  nodes: [],              // { id, text, type, convId, frequency, shared, firstDate, conversations }
  edges: [],              // { source, target, relation }
  deletedNodes: new Set(),
  deletedEdges: new Set(),  // keys: "src→tgt:relation"
  texts: new Map(),         // nodeId → edited text
})

// Unified view: null = scatter map, string convId = expanded conversation network
export const expandedConvId = writable(null)
// Screen position (relative to main element) of last clicked scatter bubble
export const bubbleOrigin = writable(null)
