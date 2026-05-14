/**
 * Merge nodes that share identical text across conversations into single canonical nodes.
 * shared    — true if the node appears in more than one conversation
 * recurring — true if the node appears in more than 5 turns within any single conversation
 */
export function buildMergedGraph(perConversation) {
  const textToCanon = new Map()  // normalized text → canonical node id
  const idToCanon   = new Map()  // original prefixed id → canonical id
  const canonMap    = new Map()  // canonical id → merged node object

  for (const conv of perConversation) {
    for (const node of conv.nodes) {
      const key = node.text.toLowerCase().trim()
      const turnSpan = new Set(node.turn_indices ?? []).size
      const isRecurring = turnSpan >= 5
      if (!textToCanon.has(key)) {
        textToCanon.set(key, node.id)
        canonMap.set(node.id, {
          ...node,
          conversations: [{ id: conv.id, title: conv.title, date: conv.date }],
          frequency: 1,
          firstDate: node.date,
          shared: false,
          recurring: isRecurring,
        })
      } else {
        const cid = textToCanon.get(key)
        const cn  = canonMap.get(cid)
        if (!cn.conversations.some(c => c.id === conv.id)) {
          cn.conversations.push({ id: conv.id, title: conv.title, date: conv.date })
          cn.frequency++
          cn.shared = true
          if (isRecurring) cn.recurring = true
          if (node.date && (!cn.firstDate || node.date < cn.firstDate)) {
            cn.firstDate = node.date
          }
        }
      }
      idToCanon.set(node.id, textToCanon.get(key))
    }
  }

  // Remap edges to canonical IDs, deduplicate by src→tgt:relation
  const seen  = new Set()
  const edges = []
  for (const conv of perConversation) {
    for (const e of conv.edges) {
      const src = idToCanon.get(e.source)
      const tgt = idToCanon.get(e.target)
      if (!src || !tgt || src === tgt) continue
      const key = `${src}→${tgt}:${e.relation}`
      if (seen.has(key)) continue
      seen.add(key)
      edges.push({ ...e, source: src, target: tgt, _key: key })
    }
  }

  return { nodes: Array.from(canonMap.values()), edges, idToCanon }
}

/**
 * Return canonical node IDs belonging to a specific conversation.
 */
export function convNodeSet(convId, perConversation, idToCanon) {
  const conv = perConversation.find(c => c.id === convId)
  if (!conv) return new Set()
  return new Set(conv.nodes.map(n => idToCanon.get(n.id)).filter(Boolean))
}

// ── Stop-word list for tokenizer ─────────────────────────────────────────────
const STOP = new Set([
  'the','a','an','is','are','was','were','be','been','being','have','has','had',
  'do','does','did','will','would','could','should','may','might','shall','can',
  'to','of','in','on','at','by','for','with','about','from','into','and','but',
  'or','not','i','you','he','she','it','we','they','this','that','these','those',
  'what','which','who','my','your','his','its','our','their','me','him','her',
])

// Extract content-word unigrams and adjacent-content-word bigrams (≤2 function
// words between each pair). Consistent with the phrase matching in DetailPanel.
function extractTerms(text) {
  const words = (text ?? '').toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter(w => w.length >= 3)

  const isContent = w => w.length > 2 && !STOP.has(w)
  const unigrams = new Set(words.filter(isContent))

  const bigrams = new Set()
  for (let i = 0; i < words.length; i++) {
    if (!isContent(words[i])) continue
    for (let j = i + 1; j < words.length && j <= i + 3; j++) {
      if (isContent(words[j])) {
        bigrams.add(words.slice(i, j + 1).join(' '))
        break
      }
    }
  }

  return { unigrams, bigrams }
}

// Bigram-weighted similarity: shared phrases count 2× over shared single words.
// Falls back to unigram Jaccard when one side has no bigrams.
function phraseSimilarity(termsA, termsB) {
  const { unigrams: uA, bigrams: bA } = termsA
  const { unigrams: uB, bigrams: bB } = termsB

  let biInter = 0
  for (const bg of bA) if (bB.has(bg)) biInter++
  const biUnion = bA.size + bB.size - biInter

  let uniInter = 0
  for (const w of uA) if (uB.has(w)) uniInter++
  const uniUnion = uA.size + uB.size - uniInter

  if (biUnion > 0 && uniUnion > 0) {
    return (2 * biInter / biUnion + uniInter / uniUnion) / 3
  }
  return uniUnion > 0 ? uniInter / uniUnion : 0
}

/**
 * Given a source node id and the visible node/edge sets, return the top-N
 * candidate target nodes from *other* conversations, ranked by phrase similarity
 * and type match. Used to power cross-network link suggestions.
 */
export function recommendLinks(sourceId, allNodes, visibleEdges, topN = 6) {
  const src = allNodes.find(n => n.id === sourceId)
  if (!src) return []

  const srcConvIds = new Set((src.conversations ?? []).map(c => c.id))

  // Already-connected node ids (exclude from candidates)
  const connected = new Set([sourceId])
  for (const e of visibleEdges) {
    const s = typeof e.source === 'object' ? e.source.id : e.source
    const t = typeof e.target === 'object' ? e.target.id : e.target
    if (s === sourceId) connected.add(t)
    if (t === sourceId) connected.add(s)
  }

  const srcTerms = extractTerms(src.text ?? '')

  return allNodes
    .filter(n => {
      if (connected.has(n.id)) return false
      // Must belong to at least one conversation not shared with the source
      return (n.conversations ?? []).some(c => !srcConvIds.has(c.id))
    })
    .map(n => {
      const sim  = phraseSimilarity(srcTerms, extractTerms(n.text ?? ''))
      const type = n.type === src.type ? 0.08 : 0
      return { node: n, score: sim + type }
    })
    .filter(r => r.score > 0.08)   // require actual text overlap, not type bonus alone
    .sort((a, b) => b.score - a.score)
    .slice(0, topN)
    .map(r => r.node)
}

/**
 * Compute summary stats for the network panel.
 */
export function computeStats(nodes, edges) {
  const now = new Date()
  const weekAgo = new Date(now - 7 * 86400_000).toISOString().slice(0, 10)
  return {
    totalNodes: nodes.length,
    totalEdges: edges.length,
    contradictions: edges.filter(e => e.relation === 'tension').length,
    newThisWeek:    nodes.filter(n => n.firstDate && n.firstDate >= weekAgo).length,
  }
}
